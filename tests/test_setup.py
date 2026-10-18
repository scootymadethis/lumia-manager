import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
import asyncio
import discord
from discord import app_commands
from lumia.core import Store
from lumia.config import validate_config
from lumia.setup_server import category_policy, ROLE_DEFS, CHANNEL_DEFS,role_permissions,role_position_map


class SetupAccessTests(unittest.IsolatedAsyncioTestCase):
    def context(self, user_id, *, guild_id=123, owner_ids=None):
        from lumia.setup_server import ServerSetup
        cfg=validate_config({'guild_id':123,'owner_ids':[7] if owner_ids is None else owner_ids,'roles':{'member':20}})
        guild=NS(id=guild_id,owner_id=1,me=NS(guild_permissions=NS(manage_channels=True,manage_roles=True)))
        role=NS(id=20,name='Member ®',managed=False,is_default=lambda:False)
        guild.get_role=lambda number:role if number==20 else None
        user=NS(id=user_id,guild=guild,roles=[])
        interaction=NS(guild_id=guild_id,guild=guild,user=user,response=NS(is_done=lambda:False,send_message=AsyncMock(),defer=AsyncMock()))
        bot=NS(cfg=cfg)
        cog=ServerSetup(bot)
        cog.build=AsyncMock()
        return cog,interaction

    async def test_explicit_owner_id_can_open_and_confirm_setup(self):
        from lumia.setup_server import ServerSetup
        cog,i=self.context(7)
        await ServerSetup.prepare.callback(cog,i)
        view=i.response.send_message.call_args.kwargs['view']
        await view.apply.callback(i)
        self.assertEqual(cog.build.await_count,1)

    async def test_guild_owner_retains_setup_access(self):
        from lumia.setup_server import ServerSetup
        cog,i=self.context(1)
        await ServerSetup.prepare.callback(cog,i)
        view=i.response.send_message.call_args.kwargs['view']
        await view.apply.callback(i)
        self.assertEqual(cog.build.await_count,1)

    async def test_unlisted_member_is_denied(self):
        from lumia.setup_server import ServerSetup
        cog,i=self.context(8)
        with self.assertRaises(app_commands.CheckFailure):
            await ServerSetup.prepare.callback(cog,i)
        self.assertEqual(cog.build.await_count,0)

    async def test_another_authorized_user_cannot_confirm_someone_elses_setup(self):
        from lumia.setup_server import SetupConfirm
        cog,i=self.context(1)
        view=SetupConfirm(cog,7)
        await view.apply.callback(i)
        self.assertEqual(cog.build.await_count,0)

    async def test_owner_id_revocation_is_checked_again_on_confirmation(self):
        from lumia.setup_server import SetupConfirm
        cog,i=self.context(7)
        view=SetupConfirm(cog,7)
        cog.bot.cfg['owner_ids']=[]
        await view.apply.callback(i)
        self.assertEqual(cog.build.await_count,0)

    async def test_configured_owner_id_from_other_guild_is_denied(self):
        from lumia.setup_server import ServerSetup
        cog,i=self.context(7,guild_id=456)
        with self.assertRaises(app_commands.CheckFailure):
            await ServerSetup.prepare.callback(cog,i)

    async def test_only_one_confirmation_can_run_setup(self):
        from lumia.setup_server import SetupConfirm
        cog,i=self.context(1)
        view=SetupConfirm(cog,1)
        await asyncio.gather(view.apply.callback(i),view.apply.callback(i))
        self.assertEqual(cog.build.await_count,1)

    async def test_embed_refresh_edits_only_owned_messages_and_keeps_existing_controls(self):
        from lumia.setup_server import ServerSetup
        cog,i=self.context(7)
        cog.bot.cfg['channels']['welcome']=55
        cog.bot.user=NS(id=999)
        cog.bot.store=NS(tickets=lambda:[])
        cog.bot.orders=NS(get=lambda number:{'id':number} if number==1 else None)
        member=NS(display_avatar=NS(url='https://cdn.discordapp.com/avatars/10/example.png'))
        i.guild.get_member=lambda number:member if number==10 else None
        cog.bot.get_guild=lambda number:i.guild
        i.followup=NS(send=AsyncMock())
        i.response.is_done=lambda:True
        original=discord.Embed(title='Ordine',colour=0x93C5FD)
        original.add_field(name='Cliente',value='<@10>\n`10`')
        original.add_field(name='Ordine',value='#1')
        owned=NS(author=NS(id=999),embeds=[original.copy()],components=[],edit=AsyncMock())
        with_controls=NS(author=NS(id=999),embeds=[original.copy()],components=[object()],edit=AsyncMock())
        foreign=NS(author=NS(id=100),embeds=[original.copy()],components=[],edit=AsyncMock())
        channel=Mock(spec=discord.TextChannel)
        async def history(**kwargs):
            self.assertEqual(kwargs,{'limit':20})
            for message in (owned,with_controls,foreign): yield message
        channel.history=history
        i.guild.get_channel=lambda number:channel if number==55 else None
        with patch.dict('os.environ',{'LUMIA_PUBLIC_URL':'https://manager.example'}):
            await ServerSetup.refresh_embeds.callback(cog,i)
        foreign.edit.assert_not_awaited()
        changed=owned.edit.call_args.kwargs
        self.assertEqual(changed['embeds'][0].fields[0].value,'<@10>')
        self.assertEqual(changed['embeds'][0].thumbnail.url,member.display_avatar.url)
        self.assertEqual(changed['view'].children[0].url,'https://manager.example/orders/1')
        self.assertNotIn('view',with_controls.edit.call_args.kwargs)


class SetupTests(unittest.TestCase):
    def test_ticket_categories_have_no_member_or_customer_grant(self):
        self.assertEqual(category_policy('tickets'), ('management','support'))
        self.assertEqual(category_policy('private_tickets'), ('management',))

    def test_roles_are_not_given_administrator(self):
        for name,label,color in ROLE_DEFS:
            self.assertNotEqual(name,'administrator')
        self.assertTrue(any(key=='ticket_panel' for key,*_ in CHANNEL_DEFS))

    def test_moderators_can_use_real_moderation_permissions_without_role_management(self):
        permissions=role_permissions('moderator')
        self.assertTrue(permissions.moderate_members)
        self.assertTrue(permissions.manage_messages)
        self.assertFalse(permissions.manage_roles)
        self.assertFalse(permissions.administrator)
        self.assertFalse(role_permissions('member').ban_members)

    def test_staff_roles_are_ordered_above_members_for_discord_hierarchy(self):
        roles={key:key for key,_,_ in ROLE_DEFS}
        positions=role_position_map(roles)
        self.assertGreater(positions['management'],positions['moderator'])
        self.assertGreater(positions['moderator'],positions['member'])
        self.assertGreater(positions['developer'],positions['customer'])


class GatewayDelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_created_roles_are_used_before_gateway_cache_arrives(self):
        from lumia.setup_server import ServerSetup
        class Role:
            def __init__(self,number,name='Member ®'):
                self.id,self.name,self.managed=number,name,False
            def is_default(self): return False
        class StopAtCategory(Exception): pass
        class Guild:
            def __init__(self):
                self.me=Role(900)
                self.default_role=Role(1)
                self.created=[]
                self.positions={}
                self.overwrites=None
                self.member=Role(50)
            def get_role(self,number): return self.member if number==50 else None
            def get_channel(self,number): return None
            async def create_role(self,**kwargs):
                role=Role(100+len(self.created),kwargs['name'])
                self.created.append(role)
                return role
            async def edit_role_positions(self,**kwargs): self.positions=kwargs['positions']
            async def create_category(self,name,**kwargs):
                self.overwrites=kwargs['overwrites']
                raise StopAtCategory()
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db.sqlite')
            try:
                guild=Guild()
                bot=NS(cfg=validate_config({'guild_id':123,'roles':{'member':50}}),store=store,save_config=lambda:None)
                with self.assertRaises(StopAtCategory):
                    await ServerSetup(bot).build(guild)
                self.assertEqual(len(guild.positions),9)
                self.assertNotIn(guild.member,guild.positions)
                self.assertNotIn(None,guild.overwrites)
            finally:
                store.close()
