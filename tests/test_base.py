import unittest
from types import SimpleNamespace as NS
from lumia.config import validate_config
from lumia.common import is_management, safe_role


class BaseTests(unittest.TestCase):
    def test_config_rejects_missing_guild_and_wrong_types(self):
        for cfg in ({}, {'guild_id':'hello'}, {'guild_id':1,'roles':{'member':True}}):
            with self.assertRaises(ValueError):
                validate_config(cfg)

    def test_config_defaults_do_not_auto_enable_punishment(self):
        cfg = validate_config({'guild_id':123})
        self.assertEqual(cfg['security']['mode'],'observe')
        self.assertFalse(cfg['automod']['enabled'])

    def test_config_rejects_string_switches_and_broken_lists(self):
        for fields in ({'automod':{'enabled':'false'}},{'automod':{'blocked_domains':'foo'}},{'security':{'whitelist_users':['bad']}}):
            with self.assertRaises(ValueError):
                validate_config({'guild_id':123,**fields})

    def test_management_needs_actual_configured_role(self):
        member = NS(id=4,guild=NS(owner_id=1),roles=[NS(id=20)])
        self.assertFalse(is_management(member,{'owner_ids':[],'roles':{'management':21}}))
        self.assertTrue(is_management(member,{'owner_ids':[],'roles':{'management':20}}))

    def test_staff_roles_cannot_alias_self_service_roles(self):
        with self.assertRaises(ValueError):
            validate_config({'guild_id':123,'roles':{'management':55,'member':55}})

    def test_self_roles_reject_dangerous_or_managed_roles(self):
        import discord
        harmless = NS(id=2,managed=False,permissions=discord.Permissions.none())
        dangerous = NS(id=3,managed=False,permissions=discord.Permissions(administrator=True))
        self.assertTrue(safe_role(harmless))
        self.assertFalse(safe_role(dangerous))
        harmless.managed = True
        self.assertFalse(safe_role(harmless))

    def test_self_roles_reject_all_non_public_permission_bits(self):
        import discord
        for flag in ('mute_members','deafen_members','manage_events','manage_expressions','manage_webhooks','bypass_slowmode','pin_messages'):
            with self.subTest(flag=flag):
                role=NS(id=2,managed=False,permissions=discord.Permissions(**{flag:True}))
                self.assertFalse(safe_role(role))
