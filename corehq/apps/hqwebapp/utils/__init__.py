import logging

from django.conf import settings
from django.template.loader import render_to_string
from django.templatetags.i18n import language_name
from django.utils.translation import LANGUAGE_SESSION_KEY, activate
from django.views.decorators.debug import sensitive_variables

from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_PSS
from memoized import memoized

from corehq.apps.hqwebapp.forms import BulkUploadForm
from corehq.apps.hqwebapp.tasks import send_html_email_async
from corehq.apps.users.models import WebUser
from custom.nic_compliance.utils import get_raw_password


logger = logging.getLogger(__name__)


@memoized
def get_hq_private_key():
    if settings.HQ_PRIVATE_KEY:
        return RSA.importKey(settings.HQ_PRIVATE_KEY)

    raise Exception('No private key found in localsettings.HQ_PRIVATE_KEY')


@sensitive_variables('private_key')
def sign(message):
    """
    Signs the SHA256 hash of message with HQ's private key, and returns
    the binary signature. The scheme used is RSASSA-PSS.
    """
    private_key = get_hq_private_key()
    sha256_hash = SHA256.new(message)
    signature = PKCS1_PSS.new(private_key).sign(sha256_hash)
    return signature


def get_bulk_upload_form(context=None, context_key="bulk_upload", form_class=BulkUploadForm, app=None):
    context = context or {}
    form_context = context.get(context_key, {})
    return form_class(
        form_context.get('plural_noun', ''),
        form_context.get('action'),
        context_key + "_form",
        form_context,
        app,
    )


def csrf_inline(request):
    """
    Returns "<input type='hidden' name='csrfmiddlewaretoken' value='<csrf-token-value>' />",
    same as csrf_token template tag, but a shortcut without needing a Template or Context explicitly.

    Useful for adding inline forms in messages for e.g. while showing an "'undo' Archive Form" message
    """
    from django.template import Template, RequestContext
    node = "{% csrf_token %}"
    return Template(node).render(RequestContext(request))


def aliased_language_name(lang_code):
    """
    This is needed since we use non-standard language codes as alias, for e.g. 'fra' instead of 'fr' for French
    """
    try:
        return language_name(lang_code)
    except KeyError:
        for code, name in settings.LANGUAGES:
            if code == lang_code:
                return name
        raise KeyError('Unknown language code %s' % lang_code)


def decode_password(obfuscated_password):
    if settings.OBFUSCATE_PASSWORD_FOR_NIC_COMPLIANCE:
        return get_raw_password(obfuscated_password)
    else:
        return obfuscated_password


def get_environment_friendly_name():
    try:
        env = {
            "production": "",
            "india": "India",
        }[settings.SERVER_ENVIRONMENT]
    except KeyError:
        env = settings.SERVER_ENVIRONMENT
    return env


def update_session_language(req, old_lang, new_lang):
    # Update the language for this session if the user signing in has a different language than the current
    # session default
    if new_lang != old_lang:
        # update the current session's language setting
        req.session[LANGUAGE_SESSION_KEY] = new_lang
        # and activate it for the current thread so the response page is translated too
        activate(new_lang)
