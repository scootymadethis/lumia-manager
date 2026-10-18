import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import discord

from lumia.core import Store
from lumia.community import InviteTracker
from lumia.moderation import AuditGuard, RaidGuard, audit_change_is_risky, blocked_domain, moderation_error


def member(number, position, **permissions):
    perms = dict(administrator=False, moderate_members=False, kick_members=False,
                 ban_members=False, manage_messages=False)
    perms.update(permissions)
    return SimpleNamespace(id=number, top_role=position, guild_permissions=SimpleNamespace(**perms))


class HierarchyTests(unittest.TestCase):
    def setUp(self):
        self.actor = member(10, 8, kick_members=True, moderate_members=True)
        self.target = member(20, 2)
        self.bot = member(30, 9, kick_members=True, moderate_members=True)

    def test_staff_role_does_not_replace_discord_permission(self):
        self.actor.guild_permissions.kick_members = False
        self.assertIsNotNone(moderation_error(self.actor, self.target, self.bot, 1, 'kick_members'))

    def test_equal_role_owner_and_self_are_protected(self):
        for target in (member(20, 8), member(1, 1), self.actor, self.bot):
            with self.subTest(target=target.id):
                self.assertIsNotNone(moderation_error(self.actor, target, self.bot, 1, 'kick_members'))

    def test_bot_hierarchy_is_checked_even_for_guild_owner(self):
        owner = member(1, 1, administrator=True)
        self.assertIsNotNone(moderation_error(owner, member(20, 9), self.bot, 1, 'kick_members'))

    def test_lower_role_target_with_both_permissions_is_allowed(self):
        self.assertIsNone(moderation_error(self.actor, self.target, self.bot, 1, 'kick_members'))

    def test_timeout_rejects_administrators(self):
        self.target.guild_permissions.administrator = True
        self.assertIsNotNone(moderation_error(self.actor, self.target, self.bot, 1, 'moderate_members'))

    def test_domain_suffix_matching_does_not_block_unrelated_host(self):
        self.assertEqual(blocked_domain('https://sub.bad.example/a', ['bad.example']), 'bad.example')
        self.assertIsNone(blocked_domain('https://notbad.example/a', ['bad.example']))

    def test_permission_diff_only_flags_new_dangerous_permissions(self):
        harmless = SimpleNamespace(permissions=discord.Permissions(send_messages=True))
        dangerous = SimpleNamespace(permissions=discord.Permissions(send_messages=True, manage_roles=True))
        self.assertTrue(audit_change_is_risky('role_update', harmless, dangerous))
        self.assertFalse(audit_change_is_risky('role_update', dangerous, harmless))
        self.assertFalse(audit_change_is_risky('role_update', harmless, harmless))
        self.assertFalse(audit_change_is_risky('role_update', None, dangerous))

    def test_role_diff_only_flags_added_privileged_roles(self):
        safe = SimpleNamespace(id=1, permissions=discord.Permissions(send_messages=True))
        dangerous = SimpleNamespace(id=2, permissions=discord.Permissions(ban_members=True))
        self.assertTrue(audit_change_is_risky('member_role_update', SimpleNamespace(roles=[]), SimpleNamespace(roles=[dangerous])))
        self.assertFalse(audit_change_is_risky('member_role_update', SimpleNamespace(roles=[dangerous]), SimpleNamespace(roles=[safe])))
        self.assertFalse(audit_change_is_risky('member_role_update', None, SimpleNamespace(roles=[SimpleNamespace(id=3)])))

    def test_create_and_webhook_delete_bursts_are_counted(self):
        for action in ('channel_create', 'role_create', 'webhook_delete'):
            self.assertTrue(audit_change_is_risky(action))


class StoredPolicies(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state.db')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_audit_threshold_uses_distinct_entry_ids_and_real_actor(self):
        guard = AuditGuard(self.store, {'audit_limit': 2, 'audit_window': 60}, owner=1)
        entry = dict(id=100, actor=8, action='channel_delete', target=50)
        self.assertIsNone(guard.observe(entry, now=1000))
        self.assertIsNone(guard.observe(entry, now=1001))
        self.assertIsNone(guard.observe(dict(id=101, actor=None, action='channel_delete', target=51), now=1002))
        incident = guard.observe(dict(id=102, actor=8, action='role_delete', target=52), now=1003)
        self.assertEqual(incident['actor'], 8)
        self.assertEqual([e['id'] for e in incident['entries']], [100, 102])
        self.assertEqual(incident['entries'][-1]['target'], 52)
        self.assertEqual(len(self.store.records('security_incidents')), 1)

    def test_audit_whitelist_owner_and_expired_window_do_not_trigger(self):
        guard = AuditGuard(self.store, {'audit_limit': 2, 'audit_window': 10, 'whitelist_users': [9]}, owner=1)
        for i, actor in enumerate((1, 1, 9, 9, 8)):
            self.assertIsNone(guard.observe(dict(id=i, actor=actor, action='channel_delete', target=i), now=1000))
        self.assertIsNone(guard.observe(dict(id=9, actor=8, action='channel_delete', target=9), now=1011))

    def test_audit_guard_keeps_seen_entries_across_restart(self):
        cfg = {'audit_limit': 2, 'audit_window': 60}
        first = dict(id=100, actor=8, action='channel_delete', target=50)
        AuditGuard(self.store, cfg, owner=1).observe(first, now=1000)
        guard = AuditGuard(self.store, cfg, owner=1)
        self.assertIsNone(guard.observe(first, now=1001))
        incident = guard.observe(dict(id=101, actor=8, action='role_delete', target=51), now=1002)
        self.assertIsNotNone(incident)

    def test_escalation_threshold_rejects_unverified_diffs(self):
        guard = AuditGuard(self.store, {'audit_limit': 2, 'audit_window': 60}, owner=1)
        self.assertIsNone(guard.observe(dict(id=1, actor=8, action='role_update', target=50, dangerous_grant=False), now=1000))
        self.assertIsNone(guard.observe(dict(id=2, actor=8, action='role_update', target=50, dangerous_grant=True), now=1001))
        incident = guard.observe(dict(id=3, actor=8, action='member_role_update', target=51, dangerous_grant=True), now=1002)
        self.assertEqual([e['id'] for e in incident['entries']], [2, 3])

    def test_raid_window_persists_and_expires(self):
        cfg = {'join_limit': 3, 'join_window': 20, 'raid_seconds': 300}
        guard = RaidGuard(self.store, cfg)
        self.assertFalse(guard.join(1, young=True, now=1000)['active'])
        self.assertFalse(guard.join(2, young=True, now=1001)['active'])
        self.assertTrue(guard.join(3, young=True, now=1002)['active'])
        self.assertTrue(RaidGuard(self.store, cfg).active(now=1003))
        self.assertFalse(guard.active(now=1303))

    def test_ordinary_launch_surge_does_not_pause_member_verification(self):
        guard = RaidGuard(self.store, {'join_limit': 3, 'join_window': 20})
        for number in range(4):
            self.assertFalse(guard.join(number, young=False, now=1000 + number)['active'])

    def test_unique_invite_increment_is_attributed_and_leave_is_counted(self):
        invites = InviteTracker(self.store)
        invites.seed({'abc': {'uses': 4, 'inviter': 10}})
        join = invites.join(50, {'abc': {'uses': 5, 'inviter': 10}}, now=1000)
        self.assertEqual(join['inviter'], 10)
        self.assertEqual(invites.totals(10), {'total': 1, 'active': 1, 'left': 0})
        invites.leave(50, now=1001)
        self.assertEqual(invites.totals(10), {'total': 1, 'active': 0, 'left': 1})

    def test_batched_unknown_and_first_snapshot_are_never_guessed(self):
        invites = InviteTracker(self.store)
        self.assertIsNone(invites.join(1, {'a': {'uses': 1, 'inviter': 9}}, now=1000)['inviter'])
        self.assertIsNone(invites.join(2, {'a': {'uses': 3, 'inviter': 9}}, now=1001)['inviter'])
        self.assertIsNone(invites.join(3, None, now=1002)['inviter'])
        self.assertIsNone(invites.join(4, {'a': {'uses': 4, 'inviter': 9}}, now=1003)['inviter'])

    def test_new_or_deleted_invites_make_concurrent_attribution_unknown(self):
        invites = InviteTracker(self.store)
        invites.seed({'a': {'uses': 0, 'inviter': 9}, 'single': {'uses': 0, 'inviter': 8}})
        self.assertIsNone(invites.join(1, {'a': {'uses': 1, 'inviter': 9}}, now=1000)['inviter'])
        self.assertIsNone(invites.join(2, {'a': {'uses': 2, 'inviter': 9}, 'new': {'uses': 1, 'inviter': 8}}, now=1001)['inviter'])

    def test_rejoin_history_does_not_count_previous_membership_as_active(self):
        invites = InviteTracker(self.store)
        invites.seed({'a': {'uses': 0, 'inviter': 9}})
        invites.join(1, {'a': {'uses': 1, 'inviter': 9}}, now=1000)
        invites.leave(1, now=1001)
        invites.join(1, {'a': {'uses': 2, 'inviter': 9}}, now=1002)
        self.assertEqual(invites.totals(9), {'total': 2, 'active': 1, 'left': 1})

    def test_members_who_left_during_downtime_are_reconciled_without_guessing_new_invites(self):
        invites = InviteTracker(self.store)
        invites.seed({'a': {'uses': 0, 'inviter': 9}})
        invites.join(1, {'a': {'uses': 1, 'inviter': 9}}, now=1000)
        restarted = InviteTracker(self.store)
        restarted.reconcile(set(), now=1100)
        self.assertEqual(restarted.totals(9), {'total': 1, 'active': 0, 'left': 1})


if __name__ == '__main__':
    unittest.main()
