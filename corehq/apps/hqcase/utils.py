import datetime
import uuid
from xml.etree import cElementTree as ElementTree

from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy

from casexml.apps.case.mock import CaseBlock
from casexml.apps.case.util import property_changed_in_action
from couchexport.deid import deid_date, deid_ID
from dimagi.utils.parsing import json_format_datetime

from corehq.apps.case_search.const import SPECIAL_CASE_PROPERTIES_MAP
from corehq.apps.data_interfaces.deduplication import DEDUPE_XMLNS
from corehq.apps.es import filters
from corehq.apps.es.cases import CaseES
from corehq.apps.export.const import DEID_DATE_TRANSFORM, DEID_ID_TRANSFORM
from corehq.apps.receiverwrapper.util import submit_form_locally
from corehq.apps.users.util import SYSTEM_USER_ID
from corehq.form_processor.exceptions import CaseNotFound, MissingFormXml
from corehq.form_processor.models import CommCareCase
from corehq.motech.dhis2.const import XMLNS_DHIS2
from corehq.apps.hqcase.constants import UPDATE_REASON_RESAVE

CASEBLOCK_CHUNKSIZE = 100
SYSTEM_FORM_XMLNS = 'http://commcarehq.org/case'
EDIT_FORM_XMLNS = 'http://commcarehq.org/case/edit'
AUTO_UPDATE_XMLNS = 'http://commcarehq.org/hq_case_update_rule'

SYSTEM_FORM_XMLNS_MAP = {
    SYSTEM_FORM_XMLNS: gettext_lazy('System Form'),
    EDIT_FORM_XMLNS: gettext_lazy('Data Cleaning Form'),
    AUTO_UPDATE_XMLNS: gettext_lazy('Automatic Case Update Rule'),
    DEDUPE_XMLNS: gettext_lazy('Deduplication Rule'),
    XMLNS_DHIS2: gettext_lazy('DHIS2 Integration')
}

ALLOWED_CASE_IDENTIFIER_TYPES = [
    "contact_phone_number",
    "external_id",
]


def submit_case_blocks(
    case_blocks,
    domain,
    username="system",
    user_id=None,
    xmlns=None,
    attachments=None,
    form_id=None,
    submission_extras=None,
    case_db=None,
    device_id=None,
    form_name=None,
    max_wait=...,
):
    """
    Submits casexml in a manner similar to how they would be submitted from a phone.

    :param xmlns: Form XMLNS. Format: IRI or URN. This should be used to
    identify the subsystem that posted the cases. This should be a constant
    value without any dynamic components. Ideally the XMLNS should be
    added to ``SYSTEM_FORM_XMLNS_MAP`` for more user-friendly display.
    See ``SYSTEM_FORM_XMLNS_MAP`` form examples.
    :param device_id: Identifier for the source of posted cases. Ideally
    this should uniquely identify the exact subsystem configuration that
    is posting cases to make it easier to trace the source. Used in combination with
    XMLNS this allows pinpointing the exact source. Example: If the cases are being
    generated by an Automatic Case Rule, then the device_id should be the rule's ID.
    :param form_name: Human readable version of the device_id. For example the
    Automatic Case Rule name.
    :param submission_extras: Dict of additional kwargs to pass through to ``SubmissionPost``
    :param max_wait: Maximum time (in seconds) to allow the process to be delayed if
    the project is over its submission rate limit.
    See the docstring for submit_form_locally for meaning of values.

    returns the UID of the resulting form.
    """
    submission_extras = submission_extras or {}
    attachments = attachments or {}
    now = json_format_datetime(datetime.datetime.utcnow())
    if not isinstance(case_blocks, str):
        case_blocks = ''.join(case_blocks)
    form_id = form_id or uuid.uuid4().hex
    form_xml = render_to_string('hqcase/xml/case_block.xml', {
        'xmlns': xmlns or SYSTEM_FORM_XMLNS,
        'name': form_name,
        'case_block': case_blocks,
        'time': now,
        'uid': form_id,
        'username': username,
        'user_id': user_id or "",
        'device_id': device_id or "",
    })

    result = submit_form_locally(
        instance=form_xml,
        domain=domain,
        attachments=attachments,
        case_db=case_db,
        max_wait=max_wait,
        **submission_extras
    )
    return result.xform, result.cases


def get_case_by_identifier(domain, identifier):
    # Try by any of the allowed identifiers
    for identifier_type in ALLOWED_CASE_IDENTIFIER_TYPES:
        result = CaseES().domain(domain).filter(
            filters.term(identifier_type, identifier)).get_ids()
        if result:
            return CommCareCase.objects.get_case(result[0], domain)
    # Try by case id
    try:
        case_by_id = CommCareCase.objects.get_case(identifier, domain)
        if case_by_id.domain == domain:
            return case_by_id
    except (CaseNotFound, KeyError):
        pass

    return None


def submit_case_block_from_template(
    domain,
    template,
    context,
    xmlns=None,
    user_id=None,
    device_id=None,
):
    case_block = render_to_string(template, context)
    # Ensure the XML is formatted properly
    # An exception is raised if not
    case_block = ElementTree.tostring(ElementTree.XML(case_block), encoding='utf-8').decode('utf-8')

    return submit_case_blocks(
        case_block,
        domain,
        user_id=user_id or SYSTEM_USER_ID,
        xmlns=xmlns,
        device_id=device_id,
    )


def _get_update_or_close_case_block(
    case_id,
    case_properties=None,
    close=False,
    owner_id=None,
):
    kwargs = {
        'create': False,
        'user_id': SYSTEM_USER_ID,
        'close': close,
    }
    if case_properties:
        if 'external_id' in case_properties:
            # `copy()` so as not to modify by reference
            case_properties = case_properties.copy()
            kwargs['external_id'] = case_properties.pop('external_id')
        kwargs['update'] = case_properties
    if owner_id:
        kwargs['owner_id'] = owner_id

    return CaseBlock.deprecated_init(case_id, **kwargs)


def update_case(
    domain,
    case_id,
    case_properties=None,
    close=False,
    xmlns=None,
    device_id=None,
    form_name=None,
    owner_id=None,
    max_wait=...,
):
    """
    Updates or closes a case (or both) by submitting a form.
    domain - the case's domain
    case_id - the case's id
    case_properties - to update the case, pass in a dictionary of {name1: value1, ...}
                      to ignore case updates, leave this argument out
    close - True to close the case, False otherwise
    xmlns - see submit_case_blocks xmlns docs
    device_id - see submit_case_blocks device_id docs
    form_name - see submit_case_blocks form_name docs
    max_wait - Maximum time (in seconds) to allow the process to be delayed if
               the project is over its submission rate limit.
               See the docstring for submit_form_locally for meaning of values
    """
    caseblock = _get_update_or_close_case_block(case_id, case_properties, close, owner_id)
    return submit_case_blocks(
        ElementTree.tostring(caseblock.as_xml(), encoding='utf-8').decode('utf-8'),
        domain,
        user_id=SYSTEM_USER_ID,
        xmlns=xmlns,
        device_id=device_id,
        form_name=form_name,
        max_wait=max_wait
    )


def bulk_update_cases(domain, case_changes, device_id, xmlns=None):
    """
    Updates or closes a list of cases (or both) by submitting a form.
    domain - the cases' domain
    case_changes - a tuple in the form (case_id, case_properties, close)
        case_id - id of the case to update
        case_properties - to update the case, pass in a dictionary of {name1: value1, ...}
                          to ignore case updates, leave this argument out
        close - True to close the case, False otherwise
    device_id - see submit_case_blocks device_id docs
    """
    case_blocks = []
    for case_id, case_properties, close in case_changes:
        case_block = _get_update_or_close_case_block(case_id, case_properties, close)
        case_blocks.append(case_block.as_text())
    return submit_case_blocks(case_blocks, domain, device_id=device_id, xmlns=xmlns)


def resave_case(domain, case, send_post_save_signal=True):
    from corehq.form_processor.change_publishers import publish_case_saved
    publish_case_saved(case, associated_form_id=UPDATE_REASON_RESAVE, send_post_save_signal=send_post_save_signal)


def get_last_non_blank_value(case, case_property):
    case_transactions = sorted(case.actions, key=lambda t: t.server_date, reverse=True)
    for case_transaction in case_transactions:
        try:
            property_changed_info = property_changed_in_action(
                case.domain,
                case_transaction,
                case.case_id,
                case_property
            )
        except MissingFormXml:
            property_changed_info = None
        if property_changed_info and property_changed_info.new_value:
            return property_changed_info.new_value


def get_case_value(case, value):
    """
    Returns the case's ``value`` and whether it's a property on the case
    (as opposed to attribute).

    :param case: the relevant case
    :param value: the value you want from the case
    :returns: A tuple containing the value and whether that value is a
        property on the case. If no value is found ``(None, None)`` is
        returned
    """
    if not value:
        return None, None

    if value in SPECIAL_CASE_PROPERTIES_MAP:
        return SPECIAL_CASE_PROPERTIES_MAP[value].get_value(case.to_json()), False
    elif value in case.case_json:
        return case.case_json.get(value, None), True
    return None, None


def get_deidentified_data(case, censor_data):
    """
    This function is used to get the data on the specified case, but
    with the ``censor_data`` properties censored.

    :param case: the case to censor the data for
    :param censor_data: a dictionary containing as key the case
        attribute or property to de-identify, and as value the name of
        the transform method to use to de-identify the data. An invalid
        transform name will result in a blank value.
    :returns: A tuple containing a dictionary of censored case
        attributes and their de-identified values, and a dictionary of
        censored case properties and their de-identified values.
    """
    attrs = {}
    props = {}

    if censor_data:
        for attr_or_prop, transform in censor_data.items():
            case_value, is_case_property = get_case_value(case, attr_or_prop)

            if not case_value:
                continue

            censored_value = ''
            if transform == DEID_DATE_TRANSFORM:
                censored_value = deid_date(case_value, None, key=case.case_id)
            if transform == DEID_ID_TRANSFORM:
                censored_value = deid_ID(case_value, None)

            if is_case_property:
                props[attr_or_prop] = censored_value
            else:
                attrs[attr_or_prop] = censored_value

    return attrs, props


def is_copied_case(case):
    """Returns True if the case was created by copying an existing case using the 'COPY_CASES' feature"""
    from corehq.apps.hqcase.case_helper import CaseCopier
    return CaseCopier.COMMCARE_CASE_COPY_PROPERTY_NAME in case.case_json
