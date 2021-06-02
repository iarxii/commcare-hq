import json

from corehq.apps.api.tests.utils import APIResourceTest
from corehq.apps.api.resources.v0_5 import (
    MessagingEventResource, MessagingEventResourceNew
)
from corehq.apps.sms.models import MessagingEvent
from corehq.apps.sms.tests.data_generator import create_fake_sms


class TestMessagingEventResource(APIResourceTest):
    resource = MessagingEventResourceNew
    api_name = 'v0.5'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def _create_sms_messages(self, count, randomize, domain=None):
        domain = domain or self.domain.name
        for i in range(count):
            create_fake_sms(domain, randomize=randomize)

    def _serialized_messaging_event(self):
        return {
            "content_type": "sms",
            "date": "2016-01-01T12:00:00",
            "case_id": None,
            "domain": "qwerty",
            "error": None,
            "form": None,
            'messages': [
                {
                    'backend': 'fake-backend-id',
                    'contact': '99912345678',
                    'content': 'test sms text',
                    'date': '2016-01-01T12:00:00',
                    'direction': 'outgoing',
                    'status': 'sent',
                    'type': 'sms'
                }
            ],
            # "id": 1,  # ids are explicitly removed from comparison
            "recipient": {'display': 'unknown', 'id': None, 'type': 'case'},
            "source": {'id': None, 'display': 'sms', 'type': "other"},
            "status": "completed",
        }

    def test_get_list_simple(self):
        self._create_sms_messages(2, randomize=False)
        response = self._assert_auth_get_resource(self.list_endpoint)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)['objects']
        self.assertEqual(2, len(data))
        for result in data:
            del result['id']  # don't bother comparing ids
            self.assertEqual(self._serialized_messaging_event(), result)

    def test_date_ordering(self):
        self._create_sms_messages(5, randomize=True)
        response = self._assert_auth_get_resource(f'{self.list_endpoint}?order_by=date')
        self.assertEqual(response.status_code, 200)
        ordered_data = json.loads(response.content)['objects']
        self.assertEqual(5, len(ordered_data))
        dates = [r['date'] for r in ordered_data]
        self.assertEqual(dates, sorted(dates))

        response = self._assert_auth_get_resource(f'{self.list_endpoint}?order_by=-date')
        self.assertEqual(response.status_code, 200)
        reverse_ordered_data = json.loads(response.content)['objects']
        self.assertEqual(ordered_data, list(reversed(reverse_ordered_data)))

    def test_domain_filter(self):
        self._create_sms_messages(5, randomize=True, domain='different-one')
        response = self._assert_auth_get_resource(f'{self.list_endpoint}?order_by=date')
        self.assertEqual(response.status_code, 200)
        ordered_data = json.loads(response.content)['objects']
        self.assertEqual(0, len(ordered_data))
