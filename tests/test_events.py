import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from lumia.core import Store
from lumia.events import EventService, Events, RSVPView


class EventPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state.db'
        self.store = Store(self.path)
        self.events = EventService(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def create(self, **changes):
        fields = dict(title='Demo FiveM', description='Presentazione del progetto',
                      starts=2000, timezone='Europe/Rome', repeat='none', capacity=1,
                      creator=5, channel=20, now=1000)
        fields.update(changes)
        return self.events.create(**fields)

    def test_full_event_rejects_new_guest_without_removing_their_tentative_rsvp(self):
        event = self.create()
        self.events.rsvp(event['id'], 10, 'yes', now=1001)
        self.events.rsvp(event['id'], 11, 'maybe', now=1001)
        with self.assertRaises(ValueError):
            self.events.rsvp(event['id'], 11, 'yes', now=1001)
        saved = self.store.get('events', event['id'])
        self.assertEqual(saved['rsvp'], {'yes': [10], 'maybe': [11], 'no': []})

    def test_departure_releases_capacity_and_duplicate_rsvp_is_idempotent(self):
        event = self.create()
        self.events.rsvp(event['id'], 10, 'yes', now=1001)
        self.events.rsvp(event['id'], 10, 'yes', now=1001)
        self.events.rsvp(event['id'], 10, 'no', now=1001)
        result = self.events.rsvp(event['id'], 11, 'yes', now=1001)
        self.assertEqual(result['rsvp'], {'yes': [11], 'maybe': [], 'no': [10]})

    def test_event_and_capacity_survive_reopening_database(self):
        event = self.create()
        self.events.rsvp(event['id'], 10, 'yes', now=1001)
        self.store.close()
        self.store = Store(self.path)
        self.events = EventService(self.store)
        self.assertEqual(self.events.get(event['id'])['rsvp']['yes'], [10])
        with self.assertRaises(ValueError):
            self.events.rsvp(event['id'], 12, 'yes', now=1001)

    def test_cancelled_or_started_events_cannot_accept_rsvp(self):
        event = self.create()
        with self.assertRaises(ValueError):
            self.events.rsvp(event['id'], 10, 'yes', now=2000)
        self.events.cancel(event['id'])
        with self.assertRaises(ValueError):
            self.events.rsvp(event['id'], 10, 'yes', now=1001)

    def test_reminder_is_only_due_for_current_occurrence_and_is_persistent(self):
        event = self.create(starts=5000)
        self.assertEqual(self.events.due(1000), [])
        self.assertEqual([(a['kind'], a['event']['id']) for a in self.events.due(3300)], [('reminder', event['id'])])
        self.events.mark_sent(event['id'], 'reminder', 5000)
        self.assertEqual(self.events.due(3301), [])

    def test_weekly_recurrence_advances_after_downtime_without_old_mentions(self):
        event = self.create(repeat='weekly')
        self.events.rsvp(event['id'], 10, 'yes', now=1001)
        self.events.due(2000 + 2 * 604800 + 1000)
        saved = self.events.get(event['id'])
        self.assertGreater(saved['starts'], 2000 + 2 * 604800 + 1000)
        self.assertEqual(saved['rsvp']['yes'], [])
        self.assertFalse(saved['reminded'])

    def test_invalid_event_values_are_rejected(self):
        for changes in ({'capacity': -1}, {'repeat': 'monthly'}, {'starts': 999}, {'title': ''}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.create(**changes)

    def test_simultaneous_guests_cannot_exceed_capacity(self):
        event = self.create()
        def attempt(number):
            try:
                self.events.rsvp(event['id'], number, 'yes', now=1001)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(attempt, (10, 11))), 1)
        self.assertEqual(len(self.events.get(event['id'])['rsvp']['yes']), 1)


class RSVPComponentTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_guild_or_non_member_cannot_use_persistent_panel(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            try:
                cog = Events(SimpleNamespace(store=store, cfg={'guild_id': 10}))
                event = cog.service.create(title='Demo', description='', starts=time.time() + 3600,
                                           timezone='Europe/Rome', repeat='none', capacity=1, creator=1, channel=5)
                view = RSVPView(cog, event)
                self.assertTrue(view.is_persistent())
                for guild_id in (11, 10):
                    messages = []
                    async def send(text, **kwargs):
                        messages.append(text)
                    interaction = SimpleNamespace(guild_id=guild_id, user=SimpleNamespace(id=7),
                                                  response=SimpleNamespace(is_done=lambda: False, send_message=send))
                    await view.children[0].callback(interaction)
                    self.assertEqual(cog.service.get(event['id'])['rsvp']['yes'], [])
                    self.assertEqual(len(messages), 1)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
