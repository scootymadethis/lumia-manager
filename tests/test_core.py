import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from lumia.core import Store, Window, attribute_invite, next_occurrence, parse_when


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db.sqlite'
        self.db = Store(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_quota_and_cooldown_survive_restart(self):
        a = self.db.reserve_ticket(7, 'fivem', {}, now=100)
        with self.assertRaises(ValueError):
            self.db.reserve_ticket(7, 'fivem', {}, now=120)
        b = self.db.reserve_ticket(7, 'support', {}, now=161)
        self.assertNotEqual(a['id'], b['id'])
        self.db.close()
        self.db = Store(self.path)
        with self.assertRaises(ValueError):
            self.db.reserve_ticket(7, 'support', {}, now=222)
        self.db.update_ticket(a['id'], state='closed')
        self.assertEqual(self.db.reserve_ticket(7, 'support', {}, now=222)['id'], 3)

    def test_first_claim_wins(self):
        t = self.db.reserve_ticket(7, 'fivem', {}, now=100)
        self.db.update_ticket(t['id'], state='open')
        self.assertTrue(self.db.claim(t['id'], 10))
        self.assertFalse(self.db.claim(t['id'], 11))
        self.assertEqual(self.db.ticket(t['id'])['staff'], 10)

    def test_failed_creation_releases_quota(self):
        t = self.db.reserve_ticket(7, 'fivem', {}, now=100)
        self.db.update_ticket(t['id'], state='failed')
        self.assertEqual(self.db.reserve_ticket(7, 'fivem', {}, now=161)['state'], 'creating')

    def test_record_mutation_and_backup_reopen(self):
        self.db.put('events', '1', {'rsvp': {'7': 'yes'}})
        target = Path(self.tmp.name) / 'backup.sqlite'
        self.db.backup(target)
        copied = Store(target)
        self.assertEqual(copied.get('events', '1')['rsvp'], {'7': 'yes'})
        copied.close()


class PolicyTests(unittest.TestCase):
    def test_invites_only_attribute_a_unique_single_increment(self):
        self.assertEqual(attribute_invite({'a': 1}, {'a': 2}), 'a')
        self.assertIsNone(attribute_invite({'a': 1}, {'a': 3}))
        self.assertIsNone(attribute_invite({'a': 1, 'b': 0}, {'a': 2, 'b': 1}))
        self.assertIsNone(attribute_invite({'a': 1}, {}))

    def test_windows_do_not_mix_users_or_keep_expired_entries(self):
        w = Window()
        self.assertEqual(w.hit('a', 10, now=0), 1)
        self.assertEqual(w.hit('a', 10, now=2), 2)
        self.assertEqual(w.hit('b', 10, now=2), 1)
        self.assertEqual(w.hit('a', 10, now=11), 2)

    def test_parse_rejects_nonexistent_and_ambiguous_rome_time(self):
        for stamp in ('2026-03-29 02:30', '2026-10-25 02:30'):
            with self.assertRaises(ValueError):
                parse_when(stamp, 'Europe/Rome')

    def test_weekly_event_keeps_local_hour_across_dst(self):
        start = parse_when('2026-10-18 18:00', 'Europe/Rome')
        nxt = next_occurrence(start, 'weekly', 'Europe/Rome')
        self.assertEqual(datetime.fromtimestamp(nxt, timezone.utc).isoformat(), '2026-10-25T17:00:00+00:00')


if __name__ == '__main__':
    unittest.main()
