from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from corehq.apps.custom_data_fields.models import (
    PROFILE_SLUG,
    CustomDataFieldsDefinition,
    CustomDataFieldsProfile,
    Field,
)
from corehq.apps.users.models import CommCareUser, WebUser
from corehq.apps.users.user_data import UserData
from corehq.apps.users.views.mobile.custom_data_fields import UserFieldsView


class TestUserMetadata(TestCase):
    domain = 'test-user-metadata'

    @classmethod
    def setUpTestData(cls):
        definition = CustomDataFieldsDefinition(domain=cls.domain, field_type=UserFieldsView.field_type)
        definition.save()
        definition.set_fields([Field(slug='start')])
        definition.save()
        profile = CustomDataFieldsProfile(
            name='low',
            fields={'start': 'sometimes'},
            definition=definition,
        )
        profile.save()
        cls.profile_id = profile.pk

    def setUp(self):
        self.user = CommCareUser.create(
            domain=self.domain,
            username='birdman',
            password='***',
            created_by=None,
            created_via=None,
        )
        self.addCleanup(self.user.delete, self.domain, deleted_by=None)

    def test_user_data_not_allowed_in_create(self):
        message = "Do not access user_data directly, pass metadata argument to create."
        with self.assertRaisesMessage(ValueError, message):
            CommCareUser.create(self.domain, 'martha', 'bmfa', None, None, user_data={'country': 'Canada'})

    def test_user_data_accessor(self):
        user_data = self.user.get_user_data(self.domain)
        self.assertEqual(user_data['commcare_project'], self.domain)
        user_data.update({
            'cruise': 'control',
            'this': 'road',
        })
        # Normally you shouldn't use `user.user_data` directly - I'm demonstrating that it's updated
        self.assertEqual(self.user.user_data, {
            'commcare_project': self.domain,
            'cruise': 'control',
            'this': 'road',
        })
        del user_data['cruise']
        self.assertEqual(self.user.user_data, {
            'commcare_project': self.domain,
            'this': 'road',
        })
        user_data.update({'this': 'field'})
        self.assertEqual(self.user.user_data, {
            'commcare_project': self.domain,
            'this': 'field',
        })

    def test_web_users(self):
        # This behavior is bad - data isn't fully scoped to domain
        web_user = WebUser.create(None, "imogen", "*****", None, None)
        self.addCleanup(web_user.delete, self.domain, deleted_by=None)
        user_data = web_user.get_user_data(self.domain)
        self.assertEqual(user_data.to_dict(), {'commcare_project':  self.domain})

        user_data['start'] = 'sometimes'
        self.assertEqual(web_user.get_user_data(self.domain).to_dict(), {
            'commcare_project': self.domain,
            'start': 'sometimes',
        })
        self.assertEqual(web_user.get_user_data('ANOTHER_DOMAIN').to_dict(), {
            'commcare_project': 'ANOTHER_DOMAIN',
            'start': 'sometimes',  # whoops, domain 1 affects other domains!
        })


def _get_profile(self, profile_id):
    if profile_id == 'blues':
        return CustomDataFieldsProfile(
            id=profile_id,
            name='blues',
            fields={'favorite_color': 'blue'},
        )
    return CustomDataFieldsProfile(
        id=profile_id,
        name='others',
        fields={},
    )


@patch('corehq.apps.users.user_data.UserData._get_profile', new=_get_profile)
class TestUserDataModel(SimpleTestCase):
    domain = 'test-user-data-model'

    def test_add_and_remove_profile(self):
        # Custom user data profiles get their data added to metadata automatically for mobile users
        user_data = UserData({'yearbook_quote': 'Not all who wander are lost.'}, self.domain)
        self.assertEqual(user_data.to_dict(), {
            'commcare_project': self.domain,
            'yearbook_quote': 'Not all who wander are lost.',
        })

        user_data[PROFILE_SLUG] = 'blues'
        self.assertEqual(user_data.to_dict(), {
            'commcare_project': self.domain,
            'commcare_profile': 'blues',
            'favorite_color': 'blue',  # provided by the profile
            'yearbook_quote': 'Not all who wander are lost.',
        })

        # Remove profile should remove it and related fields
        del user_data[PROFILE_SLUG]
        self.assertEqual(user_data.to_dict(), {
            'commcare_project': self.domain,
            'yearbook_quote': 'Not all who wander are lost.',
        })

    def test_profile_conflicts_with_data(self):
        user_data = UserData({'favorite_color': 'purple'}, self.domain)
        with self.assertRaisesMessage(ValueError, "Profile conflicts with existing data"):
            user_data[PROFILE_SLUG] = 'blues'

    def test_data_conflicts_with_profile(self):
        user_data = UserData({PROFILE_SLUG: 'blues'}, self.domain)
        with self.assertRaisesMessage(ValueError, "'favorite_color' cannot be set directly"):
            user_data['favorite_color'] = 'purple'

    def test_profile_and_data_conflict(self):
        user_data = UserData({}, self.domain)
        with self.assertRaisesMessage(ValueError, "'favorite_color' cannot be set directly"):
            user_data.update({
                PROFILE_SLUG: 'blues',
                'favorite_color': 'purple',
            })
