from __future__ import absolute_import
from functools import wraps
import copy
import json
import re
import urllib
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from corehq.apps.settings.views import BaseSettingsView
from dimagi.utils.decorators.memoized import memoized
import langcodes
from datetime import datetime
from couchdbkit.exceptions import ResourceNotFound

from dimagi.utils.couch.database import get_db
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponseRedirect, HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django.contrib import messages
from django_digest.decorators import httpdigest

from dimagi.utils.web import json_response, get_ip

from corehq.apps.registration.forms import AdminInvitesUserForm
from corehq.apps.prescriptions.models import Prescription
from corehq.apps.domain.models import Domain
from corehq.apps.hqwebapp.utils import InvitationView
from corehq.apps.users.decorators import require_permission
from corehq.apps.users.forms import (UpdateUserRoleForm, BaseUserInfoForm, UpdateMyAccountInfoForm)
from corehq.apps.users.models import CouchUser, CommCareUser, WebUser, \
    DomainRemovalRecord, UserRole, AdminUserRole, DomainInvitation, PublicUser, DomainMembershipError
from corehq.apps.domain.decorators import login_and_domain_required, require_superuser, domain_admin_required
from corehq.apps.orgs.models import Team
from corehq.apps.reports.util import get_possible_reports
from corehq.apps.sms import verify as smsverify

from django.utils.translation import ugettext as _, ugettext_noop

require_can_edit_web_users = require_permission('edit_web_users')
require_can_edit_commcare_users = require_permission('edit_commcare_users')


def require_permission_to_edit_user(view_func):
    @wraps(view_func)
    def _inner(request, domain, couch_user_id, *args, **kwargs):
        go_ahead = False
        if hasattr(request, "couch_user"):
            user = request.couch_user
            if user.is_superuser or user.user_id == couch_user_id or (hasattr(user, "is_domain_admin") and user.is_domain_admin()):
                go_ahead = True
            else:
                couch_user = CouchUser.get_by_user_id(couch_user_id)
                if not couch_user:
                    raise Http404()
                if couch_user.is_commcare_user() and request.couch_user.can_edit_commcare_users():
                    go_ahead = True
                elif couch_user.is_web_user() and request.couch_user.can_edit_web_users():
                    go_ahead = True
        if go_ahead:
            return login_and_domain_required(view_func)(request, domain, couch_user_id, *args, **kwargs)
        else:
            raise Http404()
    return _inner


def _users_context(request, domain):
    couch_user = request.couch_user
    web_users = WebUser.by_domain(domain)
    teams = Team.get_by_domain(domain)
    for team in teams:
        for user in team.get_members():
            if user.get_id not in [web_user.get_id for web_user in web_users]:
                user.from_team = True
                web_users.append(user)

    for user in [couch_user] + list(web_users):
        user.current_domain = domain

    return {
        'web_users': web_users,
        'domain': domain,
        'couch_user': couch_user,
    }


class BaseUserSettingsView(BaseSettingsView):
    section_name = "Users"

    @property
    @memoized
    def couch_user(self):
        user = self.request.couch_user
        if user:
            user.current_domain = self.domain
        return user

    @property
    @memoized
    def web_users(self):
        web_users = WebUser.by_domain(self.domain)
        teams = Team.get_by_domain(self.domain)
        for team in teams:
            for user in team.get_members():
                if user.get_id not in [web_user.get_id for web_user in web_users]:
                    user.from_team = True
                    web_users.append(user)
        for user in web_users:
            user.current_domain = self.domain
        return web_users

    @property
    def main_context(self):
        context = super(BaseUserSettingsView, self).main_context
        context.update({
            'web_users': self.web_users,
        })
        return context

    @property
    @memoized
    def section_url(self):
        return reverse(DefaultProjectUserSettingsView.name, args=[self.domain])

    @property
    @memoized
    def page_url(self):
        if self.name:
            return reverse(self.name, args=[self.domain])


class DefaultProjectUserSettingsView(BaseUserSettingsView):
    name = "users_default"

    @property
    @memoized
    def redirect(self):
        redirect = None
        # good ol' public domain...
        if not isinstance(self.couch_user, PublicUser):
            user = CouchUser.get_by_user_id(self.couch_user._id, self.domain)
            if user:
                if user.has_permission(self.domain, 'edit_commcare_users'):
                    redirect = reverse("commcare_users", args=[self.domain])
                elif user.has_permission(self.domain, 'edit_web_users'):
                    redirect = reverse("web_users", args=[self.domain])
        return redirect

    def get(self, request, *args, **kwargs):
        if not self.redirect:
            raise Http404
        return HttpResponseRedirect(self.redirect)


class BaseEditUserView(BaseUserSettingsView):
    user_update_form_class = None

    @property
    @memoized
    def page_url(self):
        if self.name:
            return reverse(self.name, args=[self.domain, self.editable_user_id])

    @property
    def parent_pages(self):
        return [{
            'name': _("Web Users & Roles"),
            'url': '#,'
        }]

    @property
    def editable_user_id(self):
        return self.kwargs.get('couch_user_id')

    @property
    @memoized
    def editable_user(self):
        try:
            return WebUser.get(self.editable_user_id)
        except (ResourceNotFound, CouchUser.AccountTypeError):
            raise Http404

    @property
    def existing_role(self):
        try:
            return (self.editable_user.get_role(self.domain,
                                                include_teams=False).get_qualified_id() or '')
        except DomainMembershipError:
            raise Http404

    @property
    @memoized
    def form_user_update(self):
        if self.user_update_form_class is None:
            raise NotImplementedError("You must specify a form to update the user!")

        if self.request.method == "POST" and self.request.POST['form_type'] == "update-user":
            return self.user_update_form_class(data=self.request.POST)

        form = self.user_update_form_class()
        form.initialize_form(existing_user=self.editable_user)
        return form

    @property
    def page_context(self):
        return {
            'couch_user': self.editable_user,
            'form_user_update': self.form_user_update,
            'phonenumbers': self.editable_user.phone_numbers_extended(self.request.couch_user),
        }

    def post(self, request, *args, **kwargs):
        if self.request.POST['form_type'] == "update-user":
            if self.form_user_update.is_valid():
                if self.form_user_update.update_user(existing_user=self.editable_user, domain=self.domain):
                    messages.success(self.request, _('Changes saved for user "%s"') % self.editable_user.username)
        return super(BaseEditUserView, self).get(request, *args, **kwargs)


class EditWebUserView(BaseEditUserView):
    template_name = "users/edit_web_user.html"
    name = "user_account"
    page_name = ugettext_noop("Edit User Role")
    user_update_form_class = UpdateUserRoleForm

    @property
    def user_role_choices(self):
        return UserRole.role_choices(self.domain)

    @property
    @memoized
    def form_user_update(self):
        form = super(EditWebUserView, self).form_user_update
        form.load_roles(current_role=self.existing_role, role_choices=self.user_role_choices)
        return form

    @property
    def page_context(self):
        context = super(EditWebUserView, self).page_context
        context.update({
            'form_uneditable': BaseUserInfoForm(),
        })
        return context

    @method_decorator(require_can_edit_web_users)
    def dispatch(self, request, *args, **kwargs):
        return super(EditWebUserView, self).dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        if self.editable_user_id == self.couch_user._id:
            return HttpResponseRedirect(reverse(EditMyAccountView.name, args=[self.domain]))
        return super(EditWebUserView, self).get(request, *args, **kwargs)


class BaseFullEditUserView(BaseEditUserView):
    edit_user_form_title = ""

    @property
    def page_context(self):
        context = super(BaseFullEditUserView, self).page_context
        context.update({
            'edit_user_form_title': self.edit_user_form_title,
        })
        return context

    @property
    @memoized
    def language_choices(self):
        language_choices = []
        results = get_db().view('languages/list', startkey=[self.domain], endkey=[self.domain, {}], group='true').all()
        if results:
            for result in results:
                lang_code = result['key'][1]
                label = result['key'][1]
                long_form = langcodes.get_name(lang_code)
                if long_form:
                    label += " (" + langcodes.get_name(lang_code) + ")"
                language_choices.append((lang_code, label))
        else:
            language_choices = langcodes.get_all_langs_for_select()
        return language_choices

    @property
    @memoized
    def form_user_update(self):
        form = super(BaseFullEditUserView, self).form_user_update
        form.load_language(language_choices=self.language_choices)
        return form

    def post(self, request, *args, **kwargs):
        if self.request.POST['form_type'] == "add-phonenumber":
            phone_number = self.request.POST['phone_number']
            phone_number = re.sub('\s', '', phone_number)
            if re.match(r'\d+$', phone_number):
                self.editable_user.add_phone_number(phone_number)
                self.editable_user.save()
                messages.success(request, _("Phone number added!"))
            else:
                messages.error(request, _("Please enter digits only."))
        return super(BaseFullEditUserView, self).post(request, *args, **kwargs)


class EditMyAccountView(BaseFullEditUserView):
    # todo handle "My Settings for this Project"
    # todo handle "My Projects"
    template_name = "users/edit_full_user.html"
    name = "my_account"
    page_name = ugettext_noop("Edit My Information")
    edit_user_form_title = ugettext_noop("My Information")
    user_update_form_class = UpdateMyAccountInfoForm

    @property
    def editable_user_id(self):
        return self.couch_user._id

    @property
    def editable_user(self):
        return self.couch_user

    @property
    @memoized
    def page_url(self):
        if self.name:
            return reverse(self.name, args=[self.domain])

    @property
    def all_domains(self):
        # todo hook this in properly in the overall my account view
        all_domains = self.couch_user.get_domains()
        admin_domains = []
        for d in all_domains:
            if self.couch_user.is_domain_admin(d):
                admin_domains.append(d)
        return all_domains

    def get(self, request, *args, **kwargs):
        if self.couch_user.is_commcare_user():
            from corehq.apps.users.views.mobile import EditCommCareUserView
            return HttpResponseRedirect(reverse(EditCommCareUserView.name, args=[self.domain, self.editable_user_id]))
        return super(EditMyAccountView, self).get(request, *args, **kwargs)


@require_can_edit_web_users
def web_users(request, domain, template="users/web_users.html"):
    context = _users_context(request, domain)
    user_roles = [AdminUserRole(domain=domain)]
    user_roles.extend(sorted(UserRole.by_domain(domain), key=lambda role: role.name if role.name else u'\uFFFF'))

    role_labels = {}
    for r in user_roles:
        key = 'user-role:%s' % r.get_id if r.get_id else r.get_qualified_id()
        role_labels[key] = r.name

    invitations = DomainInvitation.by_domain(domain)
    for invitation in invitations:
        invitation.role_label = role_labels.get(invitation.role, "")

    context.update({
        'user_roles': user_roles,
        'default_role': UserRole.get_default(),
        'report_list': get_possible_reports(domain),
        'invitations': invitations
    })
    return render(request, template, context)

@require_can_edit_web_users
@require_POST
def remove_web_user(request, domain, couch_user_id):
    user = WebUser.get_by_user_id(couch_user_id, domain)
    # if no user, very likely they just pressed delete twice in rapid succession so
    # don't bother doing anything.
    if user:
        record = user.delete_domain_membership(domain, create_record=True)
        user.save()
        messages.success(request, 'You have successfully removed {username} from your domain. <a href="{url}" class="post-link">Undo</a>'.format(
            username=user.username,
            url=reverse('undo_remove_web_user', args=[domain, record.get_id])
        ), extra_tags="html")
    return HttpResponseRedirect(reverse('web_users', args=[domain]))

@require_can_edit_web_users
def undo_remove_web_user(request, domain, record_id):
    record = DomainRemovalRecord.get(record_id)
    record.undo()
    messages.success(request, 'You have successfully restored {username}.'.format(
        username=WebUser.get_by_user_id(record.user_id).username
    ))
    return HttpResponseRedirect(reverse('web_users', args=[domain]))

# If any permission less than domain admin were allowed here, having that permission would give you the permission
# to change the permissions of your own role such that you could do anything, and would thus be equivalent to having
# domain admin permissions.
@domain_admin_required
@require_POST
def post_user_role(request, domain):
    role_data = json.loads(request.raw_post_data)
    role_data = dict([(p, role_data[p]) for p in set(UserRole.properties().keys() + ['_id', '_rev']) if p in role_data])
    role = UserRole.wrap(role_data)
    role.domain = domain
    if role.get_id:
        old_role = UserRole.get(role.get_id)
        assert(old_role.doc_type == UserRole.__name__)
    role.save()
    return json_response(role)


class UserInvitationView(InvitationView):
    inv_type = DomainInvitation
    template = "users/accept_invite.html"
    need = ["domain"]

    def added_context(self):
        return {'domain': self.domain}

    def validate_invitation(self, invitation):
        assert invitation.domain == self.domain

    def is_invited(self, invitation, couch_user):
        return couch_user.is_member_of(invitation.domain)

    @property
    def inviting_entity(self):
        return self.domain

    @property
    def success_msg(self):
        return "You have been added to the %s domain" % self.domain

    @property
    def redirect_to_on_success(self):
        return reverse("domain_homepage", args=[self.domain,])

    def invite(self, invitation, user):
        user.add_domain_membership(domain=self.domain)
        user.set_role(self.domain, invitation.role)
        user.save()


def accept_invitation(request, domain, invitation_id):
    return UserInvitationView()(request, invitation_id, domain=domain)


@require_POST
@require_can_edit_web_users
def reinvite_web_user(request, domain):
    invitation_id = request.POST['invite']
    try:
        invitation = DomainInvitation.get(invitation_id)
        invitation.send_activation_email()
        return json_response({'response': _("Invitation resent"), 'status': 'ok'})
    except ResourceNotFound:
        return json_response({'response': _("Error while attempting resend"), 'status': 'error'})


@require_can_edit_web_users
def invite_web_user(request, domain, template="users/invite_web_user.html"):
    role_choices = UserRole.role_choices(domain)
    if request.method == "POST":
        current_users = [user.username for user in WebUser.by_domain(domain)]
        pending_invites = [di.email for di in DomainInvitation.by_domain(domain)]
        form = AdminInvitesUserForm(request.POST,
            excluded_emails= current_users + pending_invites,
            role_choices=role_choices
        )
        if form.is_valid():
            data = form.cleaned_data
            # create invitation record
            data["invited_by"] = request.couch_user.user_id
            data["invited_on"] = datetime.utcnow()
            data["domain"] = domain
            invite = DomainInvitation(**data)
            invite.save()
            invite.send_activation_email()
            messages.success(request, "Invitation sent to %s" % invite.email)
            return HttpResponseRedirect(reverse("web_users", args=[domain]))
    else:
        form = AdminInvitesUserForm(role_choices=role_choices)
    context = _users_context(request, domain)
    context.update(
        registration_form=form
    )
    return render(request, template, context)


@require_POST
@require_permission_to_edit_user
def make_phone_number_default(request, domain, couch_user_id):
    user = CouchUser.get_by_user_id(couch_user_id, domain)
    if not user.is_current_web_user(request) and not user.is_commcare_user():
        raise Http404

    phone_number = request.POST['phone_number']
    if not phone_number:
        return Http404('Must include phone number in request.')

    user.set_default_phone_number(phone_number)
    if user.is_commcare_user():
        from corehq.apps.users.views.mobile import EditCommCareUserView
        redirect = reverse(EditCommCareUserView.name, args=[domain, couch_user_id])
    else:
        redirect = reverse(EditMyAccountView.name, args=[domain])
    return HttpResponseRedirect(redirect)

@require_POST
@require_permission_to_edit_user
def delete_phone_number(request, domain, couch_user_id):
    user = CouchUser.get_by_user_id(couch_user_id, domain)
    if not user.is_current_web_user(request) and not user.is_commcare_user():
        raise Http404

    phone_number = request.POST['phone_number']
    if not phone_number:
        return Http404('Must include phone number in request.')

    user.delete_phone_number(phone_number)
    if user.is_commcare_user():
        from corehq.apps.users.views.mobile import EditCommCareUserView
        redirect = reverse(EditCommCareUserView.name, args=[domain, couch_user_id])
    else:
        redirect = reverse(EditMyAccountView.name, args=[domain])
    return HttpResponseRedirect(redirect)

@require_permission_to_edit_user
def verify_phone_number(request, domain, couch_user_id):
    """
    phone_number cannot be passed in the url due to special characters
    but it can be passed as %-encoded GET parameters
    """
    if 'phone_number' not in request.GET:
        return Http404('Must include phone number in request.')
    phone_number = urllib.unquote(request.GET['phone_number'])
    user = CouchUser.get_by_user_id(couch_user_id, domain)

    # send verification message
    smsverify.send_verification(domain, user, phone_number)

    # create pending verified entry if doesn't exist already
    user.save_verified_number(domain, phone_number, False, None)

    if user.is_commcare_user():
        from corehq.apps.users.views.mobile import EditCommCareUserView
        redirect = reverse(EditCommCareUserView.name, args=[domain, couch_user_id])
    else:
        redirect = reverse(EditMyAccountView.name, args=[domain])
    return HttpResponseRedirect(redirect)


#@require_POST
#@require_permission_to_edit_user
#def link_commcare_account_to_user(request, domain, couch_user_id, commcare_login_id):
#    user = WebUser.get_by_user_id(couch_user_id, domain)
#    if 'commcare_couch_user_id' not in request.POST:
#        return Http404("Poorly formed link request")
#    user.link_commcare_account(domain,
#                               request.POST['commcare_couch_user_id'],
#                               commcare_login_id)
#    return HttpResponseRedirect(reverse("user_account", args=(domain, couch_user_id)))
#
#@require_POST
#@require_permission_to_edit_user
#def unlink_commcare_account(request, domain, couch_user_id, commcare_user_index):
#    user = WebUser.get_by_user_id(couch_user_id, domain)
#    if commcare_user_index:
#        user.unlink_commcare_account(domain, commcare_user_index)
#        user.save()
#    return HttpResponseRedirect(reverse("user_account", args=(domain, couch_user_id )))

#@login_and_domain_required
#def my_domains(request, domain):
#    return HttpResponseRedirect(reverse("domain_accounts", args=(domain, request.couch_user._id)))

@require_superuser
@login_and_domain_required
def domain_accounts(request, domain, couch_user_id, template="users/domain_accounts.html"):
    context = _users_context(request, domain)
    couch_user = WebUser.get_by_user_id(couch_user_id, domain)
    if request.method == "POST" and 'domain' in request.POST:
        domain = request.POST['domain']
        couch_user.add_domain_membership(domain)
        couch_user.save()
        messages.success(request,'Domain added')
    context.update({"user": request.user})
    return render(request, template, context)

@require_POST
@require_superuser
def add_domain_membership(request, domain, couch_user_id, domain_name):
    user = WebUser.get_by_user_id(couch_user_id, domain)
    if domain_name:
        user.add_domain_membership(domain_name)
        user.save()
    return HttpResponseRedirect(reverse("user_account", args=(domain, couch_user_id)))

@require_POST
def delete_domain_membership(request, domain, couch_user_id, domain_name):
    removing_self = request.couch_user.get_id == couch_user_id
    user = WebUser.get_by_user_id(couch_user_id, domain_name)

    # don't let a user remove another user's domain membership if they're not the admin of the domain or a superuser
    if not removing_self and not (request.couch_user.is_domain_admin(domain_name) or request.couch_user.is_superuser):
        messages.error(request, _("You don't have the permission to remove this user's membership"))

    elif user.is_domain_admin(domain_name): # don't let a domain admin be removed from the domain
        if removing_self:
            error_msg = ugettext_noop("Unable remove membership because you are the admin of %s" % domain_name)
        else:
            error_msg = ugettext_noop("Unable remove membership because %(user)s is the admin of %(domain)s" % {
                'user': user.username,
                'domain': domain_name
            })
        messages.error(request, error_msg)
        
    else:
        user.delete_domain_membership(domain_name)
        user.save()

        if removing_self:
            success_msg = ugettext_noop("You are no longer a part of the %s project space" % domain_name)
        else:
            success_msg = ugettext_noop("%(user)s is no longer a part of the %(domain)s project space" % {
                'user': user.username,
                'domain': domain_name
            })
        messages.success(request, success_msg)

        if removing_self and not user.is_member_of(domain):
            return HttpResponseRedirect(reverse("homepage"))

    return HttpResponseRedirect(reverse("user_account", args=(domain, couch_user_id)))

@login_and_domain_required
def change_password(request, domain, login_id, template="users/partial/reset_password.html"):
    # copied from auth's password_change

    commcare_user = CommCareUser.get_by_user_id(login_id, domain)
    json_dump = {}
    if not commcare_user:
        raise Http404
    django_user = commcare_user.get_django_user()
    if request.method == "POST":
        form = SetPasswordForm(user=django_user, data=request.POST)
        if form.is_valid() and (request.project.password_format() != 'n' or request.POST.get('new_password1').isnumeric()):
            form.save()
            json_dump['status'] = 'OK'
            form = SetPasswordForm(user=django_user)
    else:
        form = SetPasswordForm(user=django_user)
    context = _users_context(request, domain)
    context.update({
        'reset_password_form': form,
    })
    json_dump['formHTML'] = render_to_string(template, context)
    return HttpResponse(json.dumps(json_dump))


# this view can only change the current user's password
@login_and_domain_required
def change_my_password(request, domain, template="users/change_my_password.html"):
    # copied from auth's password_change
    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Your password was successfully changed!")
            return HttpResponseRedirect(reverse('user_account', args=[domain, request.couch_user._id]))
    else:
        form = PasswordChangeForm(user=request.user)
    context = _users_context(request, domain)
    context.update({
        'form': form,
    })
    return render(request, template, context)

@httpdigest
@login_and_domain_required
def test_httpdigest(request, domain):
    return HttpResponse("ok")


@Prescription.require('user-domain-transfer')
@login_and_domain_required
def user_domain_transfer(request, domain, prescription, template="users/domain_transfer.html"):
    target_domain = prescription.params['target_domain']
    if not request.couch_user.is_domain_admin(target_domain):
        return HttpResponseForbidden()
    if request.method == "POST":
        user_ids = request.POST.getlist('user_id')
        app_id = request.POST['app_id']
        errors = []
        for user_id in user_ids:
            user = CommCareUser.get_by_user_id(user_id, domain)
            try:
                user.transfer_to_domain(target_domain, app_id)
            except Exception as e:
                errors.append((user_id, user, e))
            else:
                messages.success(request, "Successfully transferred {user.username}".format(user=user))
        if errors:
            messages.error(request, "Failed to transfer the following users")
            for user_id, user, e in errors:
                if user:
                    messages.error(request, "{user.username} ({user.user_id}): {e}".format(user=user, e=e))
                else:
                    messages.error(request, "CommCareUser {user_id} not found".format(user_id=user_id))
        return HttpResponseRedirect(reverse('commcare_users', args=[target_domain]))
    else:
        from corehq.apps.app_manager.models import VersionedDoc
        # apps from the *target* domain
        apps = VersionedDoc.view('app_manager/applications_brief', startkey=[target_domain], endkey=[target_domain, {}])
        # users from the *originating* domain
        users = list(CommCareUser.by_domain(domain))
        users.extend(CommCareUser.by_domain(domain, is_active=False))
        context = _users_context(request, domain)
        context.update({
            'apps': apps,
            'commcare_users': users,
            'target_domain': target_domain
        })
        return render(request, template, context)

@require_superuser
def audit_logs(request, domain):
    from auditcare.models import NavigationEventAudit
    usernames = [user.username for user in WebUser.by_domain(domain)]
    data = {}
    for username in usernames:
        data[username] = []
        for doc in get_db().view('auditcare/urlpath_by_user_date',
            startkey=[username],
            endkey=[username, {}],
            include_docs=True,
            wrapper=lambda r: r['doc']
        ).all():
            try:
                (d,) = re.search(r'^/a/([\w\-_\.]+)/', doc['request_path']).groups()
                if d == domain:
                    data[username].append(doc)
            except Exception:
                pass
    return json_response(data)

def eula_agreement(request, domain):
    domain = Domain.get_by_name(domain)
    if request.method == 'POST':
        current_user = CouchUser.from_django_user(request.user)
        current_user.eula.signed = True
        current_user.eula.date = datetime.utcnow()
        current_user.eula.type = 'End User License Agreement'
        current_user.eula.user_ip = get_ip(request)
        current_user.save()

    return HttpResponseRedirect(reverse("corehq.apps.reports.views.default", args=[domain]))
