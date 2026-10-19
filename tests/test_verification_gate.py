"""Newcomer gate: roles, public verification entry and safe channel migration."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch
import discord
import test_onboarding as fixtures
from lumia.config import validate_config
from lumia.onboarding import complete_acceptance, Onboarding
from lumia.community import Community
from lumia.setup_server import ServerSetup, CHANNEL_DEFS, ROLE_DEFS


class VerificationGateTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.PrivateOnboardingTests.setUp
    interaction=fixtures.PrivateOnboardingTests.interaction

    def pending(self):
        role=fixtures.Role(19)
        self.roles[19]=role
        self.bot.cfg['roles']['unverified']=19
        self.bot.cfg['channels']['verification']=555
        return role

    async def test_join_assigns_pending_even_with_closed_dms_and_never_member(self):
        pending=self.pending()
        self.member.send.side_effect=discord.Forbidden(NS(status=403,reason='Forbidden'),'DM closed')
        await Community(self.bot).on_member_join(self.member)
        self.member.add_roles.assert_awaited_once_with(pending,reason='Lumia: accesso in attesa di verifica')
        self.assertIsNone(self.store.get('rules',10))
        self.assertIn('555',str(self.bot.log.call_args))

    async def test_success_grants_member_then_removes_only_pending(self):
        pending=self.pending();extra=fixtures.Role(98)
        self.member.roles=[pending,extra]
        await complete_acceptance(self.bot,self.interaction(),verified=True)
        self.member.add_roles.assert_awaited_once_with(self.roles[20],reason='Accettazione regolamento Lumia')
        self.member.remove_roles.assert_awaited_once_with(pending,reason='Lumia: verifica completata')
        self.assertTrue(self.store.get('rules',10)['verified'])

    async def test_bad_pending_hierarchy_never_grants_member(self):
        self.pending();pending=fixtures.Role(101);self.roles[19]=pending;self.member.roles=[pending]
        await complete_acceptance(self.bot,self.interaction(),verified=True)
        self.member.add_roles.assert_not_awaited()
        self.assertIsNone(self.store.get('rules',10))

    async def test_pending_remove_failure_can_retry_and_does_not_claim_success(self):
        pending=self.pending();self.member.roles=[pending]
        self.member.remove_roles.side_effect=discord.Forbidden(NS(status=403,reason='Forbidden'),'Missing permissions')
        with self.assertRaises(discord.Forbidden):
            await complete_acceptance(self.bot,self.interaction(),verified=True)
        self.assertIsNone(self.store.get('rules',10))
        self.member.roles=[pending,self.roles[20]]
        self.member.add_roles.reset_mock();self.member.remove_roles.side_effect=None
        await complete_acceptance(self.bot,self.interaction(),verified=True)
        self.member.add_roles.assert_not_awaited()
        self.assertTrue(self.store.get('rules',10)['verified'])

    async def test_channel_entry_shows_private_rules_and_does_not_require_dm(self):
        from lumia.onboarding import VerificationPanel, RulesPanel
        self.pending()
        i=self.interaction(guild_id=123)
        await VerificationPanel(self.bot).verify.callback(i)
        self.member.send.assert_not_awaited()
        sent=i.followup.send.call_args.kwargs
        self.assertTrue(sent['ephemeral'])
        self.assertIsInstance(sent['view'],RulesPanel)
        self.member.add_roles.assert_awaited_once_with(self.roles[19],reason='Lumia: accesso in attesa di verifica')

    async def test_persistent_verification_panel_registered_and_wrong_guild_rejected(self):
        from lumia.onboarding import VerificationPanel
        self.pending();Onboarding(self.bot)
        views=[call.args[0] for call in self.bot.add_view.call_args_list]
        self.assertTrue(any(view.is_persistent() and any(child.custom_id=='lumia:verification:start:v1' for child in view.children) for view in views))
        panel=VerificationPanel(self.bot)
        self.assertFalse(await panel.interaction_check(self.interaction(guild_id=999)))

    async def test_rejoin_cannot_bypass_the_verification_attempt_limit(self):
        self.pending()
        self.store.put('verification_attempts',10,{'blocked_until':9999999999})
        self.store.put('verification_attempts',11,{'count':3})
        await Community(self.bot).on_member_join(self.member)
        self.assertEqual(self.store.get('verification_attempts',10)['blocked_until'],9999999999)
        self.assertEqual(self.store.get('verification_attempts',11)['count'],3)

    async def test_sync_gives_pending_to_existing_newcomers_and_preserves_members(self):
        from lumia.onboarding import sync_pending_members
        pending=self.pending()
        existing=NS(id=11,bot=False,roles=[self.roles[20],pending],guild=self.guild,remove_roles=AsyncMock(),add_roles=AsyncMock())
        async def members(**kwargs):
            for member in (self.member,existing):yield member
        self.guild.fetch_members=members
        result=await sync_pending_members(self.bot,self.guild)
        self.assertEqual(result,{'pending':1,'cleaned':1,'failed':0})
        self.member.add_roles.assert_awaited_once_with(pending,reason='Lumia: accesso in attesa di verifica')
        existing.add_roles.assert_not_awaited()
        existing.remove_roles.assert_awaited_once_with(pending,reason='Lumia: Member già presente')
        self.assertIsNone(self.store.get('rules',10))


class GateMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_category_never_propagates_gate_or_member_migration_to_external_children(self):
        from lumia.core import Store
        store=Store(':memory:');self.addCleanup(store.close)
        roles={key:MagicMock(spec=discord.Role) for key in ('member','unverified','management','support','moderator','developer')}
        for index,role in enumerate(roles.values(),20):role.id=index
        roles['member'].managed=False
        roles['member'].is_default.return_value=False
        old=MagicMock(spec=discord.Role);old.id=10
        everyone=MagicMock(spec=discord.Role)
        bot_member=MagicMock(spec=discord.Member)
        cfg=validate_config({'guild_id':1,'roles':{key:role.id for key,role in roles.items()}})
        category=MagicMock(spec=discord.CategoryChannel);category.id=100
        owned=MagicMock(spec=discord.TextChannel);owned.id=101
        external=MagicMock(spec=discord.TextChannel);external.id=102
        category.channels=[owned,external]
        for channel in (category,owned,external):
            channel.overwrites={old:discord.PermissionOverwrite(view_channel=True)}
            channel.permissions_synced=True
            channel.edit=AsyncMock()
        registry={'cat:community':100,'channel:general':101,'role:member':10}
        channels={channel.id:channel for channel in (category,owned,external)}
        guild=NS(default_role=everyone,me=bot_member,get_role=lambda n:next((r for r in roles.values() if r.id==n),None),get_channel=channels.get)
        cog=ServerSetup(NS(cfg=cfg,store=store,save_config=lambda:None))
        await cog.migrate_member_access(guild,registry)
        await cog.reconcile_access(guild,registry,roles)
        category.edit.assert_not_awaited()
        external.edit.assert_not_awaited()
        self.assertTrue(owned.edit.await_count)
        self.assertTrue(owned.edit.call_args.kwargs['overwrites'][roles['member']].view_channel)

    async def test_verification_panel_is_updated_in_place_on_repeated_setup(self):
        from lumia.core import Store
        from lumia.onboarding import publish_verification_panel
        store=Store(':memory:');self.addCleanup(store.close)
        channel=MagicMock(spec=discord.TextChannel)
        message=NS(id=456,edit=AsyncMock())
        channel.send=AsyncMock(return_value=message)
        channel.fetch_message=AsyncMock(return_value=message)
        bot=NS(cfg={'guild_id':1,'channels':{'verification':555}},store=store)
        guild=NS(get_channel=lambda n:channel if n==555 else None)
        await publish_verification_panel(bot,guild)
        await publish_verification_panel(bot,guild)
        channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        self.assertEqual(store.get('panels','verification'),456)
        self.assertTrue(message.edit.call_args.kwargs['view'].is_persistent())

    async def test_config_preserves_pending_role_verification_channel_and_categories(self):
        cfg=validate_config({'guild_id':1,'roles':{'member':20,'unverified':19},'channels':{'verification':555},'categories':{'start':11,'info':12,'community':13}})
        self.assertEqual(cfg['roles']['unverified'],19)
        self.assertEqual(cfg['channels']['verification'],555)
        self.assertEqual(cfg['categories']['start'],11)
        self.assertTrue(any(key=='unverified' for key,*_ in ROLE_DEFS))
        self.assertEqual(next(category for key,name,category in CHANNEL_DEFS if key=='verification'),'start')

    async def test_only_owned_channels_reconcile_without_erasing_other_overwrites(self):
        from lumia.core import Store
        store=Store(':memory:');self.addCleanup(store.close)
        roles={key:MagicMock(spec=discord.Role) for key in ('member','unverified','management','support','moderator','developer')}
        for index,role in enumerate(roles.values(),20):role.id=index
        cfg=validate_config({'guild_id':1,'roles':{key:role.id for key,role in roles.items()}})
        everyone=MagicMock(spec=discord.Role);everyone.id=1
        bot_member=MagicMock(spec=discord.Member);bot_member.id=999
        other=MagicMock(spec=discord.Role);other.id=888
        channels={}
        for number,kind in [(100,discord.CategoryChannel),(101,discord.TextChannel),(102,discord.TextChannel),(103,discord.TextChannel)]:
            channel=MagicMock(spec=kind);channel.id=number
            channel.overwrites={other:discord.PermissionOverwrite(attach_files=False),everyone:discord.PermissionOverwrite(view_channel=True)}
            async def edit(_c=channel,**kwargs):_c.overwrites=kwargs['overwrites']
            channel.edit=AsyncMock(side_effect=edit)
            channel.category=None
            channels[number]=channel
        cfg['channels']['verification']=102
        cfg['channels']['services']=103  # Configured external target, not Lumia-owned.
        registry={'cat:info':100,'channel:general':101,'channel:verification':102,'channel:services':104}
        store.put('setup','resources',registry)
        guild=NS(default_role=everyone,me=bot_member,get_role=lambda n:next((r for r in roles.values() if r.id==n),None),get_channel=lambda n:channels.get(n))
        cog=ServerSetup(NS(cfg=cfg,store=store,save_config=lambda:None))
        await cog.reconcile_access(guild,registry,roles)
        for number in (100,101):
            ow=channels[number].overwrites
            self.assertFalse(ow[everyone].view_channel)
            self.assertFalse(ow[roles['unverified']].view_channel)
            self.assertTrue(ow[roles['member']].view_channel)
            self.assertFalse(ow[other].attach_files)
        self.assertTrue(channels[102].overwrites[everyone].view_channel)
        self.assertFalse(channels[102].overwrites[everyone].send_messages)
        self.assertTrue(channels[102].overwrites[roles['unverified']].view_channel)
        channels[103].edit.assert_not_awaited()
        await cog.reconcile_access(guild,registry,roles)
        self.assertEqual(channels[101].edit.await_count,1)
