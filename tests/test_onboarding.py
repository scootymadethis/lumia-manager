import asyncio
import itertools
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
import discord
from lumia.onboarding import (RolePanel, RulesPanel, PrivateStartPanel,
                              verify_can_join, send_onboarding, open_private_onboarding, private_cards)
from lumia.community import Community
from lumia.config import validate_config
from lumia.core import Store


class OnboardingTests(unittest.IsolatedAsyncioTestCase):
    async def test_raid_blocks_acceptance_without_granting_member(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'db.sqlite')
            store.put('security','raid_until',999)
            with self.assertRaises(ValueError):
                verify_can_join(store,now=998)
            verify_can_join(store,now=1000)
            store.close()

    async def test_controls_are_persistent(self):
        bot=NS(cfg={'guild_id':1},store=None)
        self.assertTrue(RolePanel(bot).is_persistent())
        self.assertTrue(RulesPanel(bot).is_persistent())
        self.assertTrue(PrivateStartPanel(bot).is_persistent())


class Role:
    def __init__(self,number,**permissions):
        self.id=number
        self.managed=False
        self.permissions=discord.Permissions(**permissions)

    def is_default(self):
        return False

    def __lt__(self,other):
        return self.id<other.id


class PrivateOnboardingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db.sqlite'
        self.store=Store(self.path)
        self.addCleanup(lambda:self.store.close())
        self.store.put('verification','policy',{'enabled':False,'until':None})
        self.roles={n:Role(n) for n in (20,21,22,23,24)}
        self.guild=NS(id=123,me=NS(top_role=Role(100),guild_permissions=NS(manage_roles=True)),
                      get_role=lambda n:self.roles.get(n),fetch_member=AsyncMock(),
                      get_channel=Mock(),invites=AsyncMock(return_value=[]),vanity_url_code=None)
        numbers=itertools.count(1000)
        self.member=NS(id=10,bot=False,guild=self.guild,roles=[],
                       created_at=discord.utils.utcnow()-timedelta(days=30),
                       send=AsyncMock(side_effect=lambda **kwargs:NS(id=next(numbers))),
                       add_roles=AsyncMock(),remove_roles=AsyncMock())
        self.guild.fetch_member.return_value=self.member
        cfg=validate_config({'guild_id':123,'roles':{'member':20,'fivem':21,'minecraft':22,'news':23,'release':24}})
        self.bot=NS(cfg=cfg,store=self.store,log=AsyncMock(),get_guild=lambda n:self.guild if n==123 else None,
                    add_view=Mock())

    def interaction(self,kind='rules',user=10,guild_id=None):
        message=NS(id=700)
        self.store.put('onboarding_messages',700,{'member':10,'guild':123,'kind':kind})
        return NS(guild_id=guild_id,user=NS(id=user),message=message,
                  response=NS(defer=AsyncMock(),is_done=lambda:True),
                  followup=NS(send=AsyncMock()))

    async def test_join_sends_rules_in_dm_without_public_posts_or_member_grant(self):
        await Community(self.bot).on_member_join(self.member)
        self.assertGreaterEqual(self.member.send.await_count,2)
        self.guild.get_channel.assert_not_called()
        self.member.add_roles.assert_not_awaited()
        self.assertIsNone(self.store.get('rules',10))
        last=self.member.send.call_args.kwargs
        self.assertIsInstance(last['view'],RulesPanel)
        self.assertEqual(self.store.get('onboarding_messages',1001)['member'],10)
        self.assertEqual(last['allowed_mentions'].to_dict()['parse'],[])

    async def test_dm_acceptance_fetches_member_and_grants_only_member_then_sends_role_menu(self):
        i=self.interaction()
        view=RulesPanel(self.bot)
        self.assertTrue(await view.interaction_check(i))
        await view.accept.callback(i)
        self.guild.fetch_member.assert_awaited_once_with(10)
        self.member.add_roles.assert_awaited_once_with(self.roles[20],reason='Accettazione regolamento Lumia')
        self.assertIn('accepted',self.store.get('rules',10))
        self.assertIsInstance(self.member.send.call_args.kwargs['view'],RolePanel)
        self.assertEqual(self.store.get('onboarding_messages',1000)['kind'],'roles')
        self.assertFalse(i.response.defer.call_args.kwargs['ephemeral'])

    async def test_private_binding_survives_store_and_view_restart(self):
        i=self.interaction()
        self.store.close()
        self.store=Store(self.path)
        self.bot.store=self.store
        view=RulesPanel(self.bot)
        self.assertTrue(await view.interaction_check(i))
        await view.accept.callback(i)
        self.member.add_roles.assert_awaited_once()

    async def test_other_user_other_server_and_unregistered_private_messages_are_rejected(self):
        view=RulesPanel(self.bot)
        i=self.interaction(user=11)
        self.assertFalse(await view.interaction_check(i))
        i=self.interaction(guild_id=999)
        self.assertFalse(await view.interaction_check(i))
        i=self.interaction(kind='roles')
        self.assertFalse(await view.interaction_check(i))
        i=self.interaction()
        self.store.delete('onboarding_messages',700)
        self.assertFalse(await view.interaction_check(i))
        self.member.add_roles.assert_not_awaited()

    async def test_departed_member_cannot_use_old_dm_buttons(self):
        self.guild.fetch_member.side_effect=discord.NotFound(NS(status=404,reason='Not Found'),'Unknown Member')
        i=self.interaction()
        await RulesPanel(self.bot).accept.callback(i)
        self.member.add_roles.assert_not_awaited()
        self.assertIsNone(self.store.get('rules',10))

    async def test_raid_pause_still_blocks_private_acceptance(self):
        self.store.put('security','raid_until',9999999999)
        await RulesPanel(self.bot).accept.callback(self.interaction())
        self.member.add_roles.assert_not_awaited()
        self.assertIsNone(self.store.get('rules',10))

    async def test_dangerous_managed_high_or_missing_member_role_is_never_granted(self):
        for mode in ('dangerous','managed','high','missing','permission'):
            with self.subTest(mode=mode):
                self.roles[20]=Role(20)
                self.guild.me.guild_permissions.manage_roles=True
                if mode=='dangerous': self.roles[20].permissions=discord.Permissions(administrator=True)
                if mode=='managed': self.roles[20].managed=True
                if mode=='high': self.roles[20]=Role(101)
                if mode=='missing': self.roles.pop(20)
                if mode=='permission': self.guild.me.guild_permissions.manage_roles=False
                await RulesPanel(self.bot).accept.callback(self.interaction())
                self.member.add_roles.assert_not_awaited()
                self.assertIsNone(self.store.get('rules',10))

    async def test_failed_assignment_does_not_record_acceptance(self):
        self.member.add_roles.side_effect=discord.Forbidden(NS(status=403,reason='Forbidden'),'Missing Permissions')
        with self.assertRaises(discord.Forbidden):
            await RulesPanel(self.bot).accept.callback(self.interaction())
        self.assertIsNone(self.store.get('rules',10))

    async def test_existing_member_is_not_regranted_but_receives_preferences(self):
        self.member.roles=[self.roles[20]]
        await RulesPanel(self.bot).accept.callback(self.interaction())
        self.member.add_roles.assert_not_awaited()
        self.assertIsInstance(self.member.send.call_args.kwargs['view'],RolePanel)

    async def test_private_preferences_use_fresh_roles_and_touch_only_opt_in_roles(self):
        self.member.roles=[self.roles[20],self.roles[22],Role(99)]
        i=self.interaction(kind='roles')
        view=RolePanel(self.bot)
        self.assertTrue(await view.interaction_check(i))
        view.select._values=['fivem','news']
        await view.select.callback(i)
        self.guild.fetch_member.assert_awaited_once_with(10)
        self.member.remove_roles.assert_awaited_once_with(self.roles[22],reason='Preferenze Lumia')
        self.member.add_roles.assert_awaited_once_with(self.roles[21],self.roles[23],reason='Preferenze Lumia')

    async def test_private_preferences_reject_revoked_member_and_privileged_choices(self):
        view=RolePanel(self.bot)
        view.select._values=['fivem']
        await view.select.callback(self.interaction(kind='roles'))
        self.member.add_roles.assert_not_awaited()
        self.member.roles=[self.roles[20]]
        view.select._values=['management']
        await view.select.callback(self.interaction(kind='roles'))
        self.member.add_roles.assert_not_awaited()
        self.roles[21].permissions=discord.Permissions(manage_roles=True)
        view.select._values=['fivem']
        await view.select.callback(self.interaction(kind='roles'))
        self.member.add_roles.assert_not_awaited()

    async def test_blocked_dms_are_logged_without_public_fallback_or_roles(self):
        self.member.send.side_effect=discord.Forbidden(NS(status=403,reason='Forbidden'),'Cannot send messages')
        await Community(self.bot).on_member_join(self.member)
        self.member.add_roles.assert_not_awaited()
        self.guild.get_channel.assert_not_called()
        self.assertIn('/inizia',self.bot.log.call_args.args[1])
        self.assertIsNone(self.store.get('onboarding_delivery',10))

    async def test_manual_retry_is_private_and_delivery_is_throttled(self):
        i=self.interaction(guild_id=123)
        await open_private_onboarding(self.bot,i)
        count=self.member.send.await_count
        await open_private_onboarding(self.bot,i)
        self.assertEqual(self.member.send.await_count,count)
        self.assertIn('minuto',i.followup.send.call_args.kwargs['embed'].description)
        self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])

    async def test_bots_and_other_guilds_do_not_receive_private_onboarding(self):
        self.member.bot=True
        self.assertEqual(await send_onboarding(self.bot,self.member),'ignored')
        self.member.bot=False
        self.guild.id=999
        self.assertEqual(await send_onboarding(self.bot,self.member),'ignored')
        self.member.send.assert_not_awaited()

    async def test_long_rules_are_delivered_in_full(self):
        text='Prima regola.\n'*800+'Ultima regola.'
        cards=list(private_cards('rules',text))
        self.assertGreater(len(cards),1)
        self.assertEqual(''.join(c.description for c in cards).replace('\n',''),text.replace('\n',''))
