"""Existing member identity and permissions survive the role-name migration."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,MagicMock

import discord
from lumia.config import validate_config
from lumia.setup_server import ServerSetup


def role(number,name='Existing member'):
    item=MagicMock(spec=discord.Role)
    item.id,item.name,item.managed=number,name,False
    item.is_default.return_value=False
    async def edit(**kwargs):
        item.name=kwargs['name']
        return item
    item.edit=AsyncMock(side_effect=edit)
    return item


class RoleReuseTests(unittest.IsolatedAsyncioTestCase):
    def context(self,registry=None):
        cfg=validate_config({'guild_id':123,'roles':{'member':20,'support':21}})
        registry={} if registry is None else registry
        self.member,self.support,self.unrelated=role(20),role(21,'Support'),role(99,'Keep me')
        self.roles={r.id:r for r in (self.member,self.support,self.unrelated)}
        store=NS(get=lambda *args:registry,put=lambda *args:None)
        bot=NS(cfg=cfg,store=store,save_config=lambda:None)
        guild=NS(get_role=lambda n:self.roles.get(n),create_role=AsyncMock())
        return ServerSetup(bot),guild,registry

    async def test_existing_roles_are_edited_in_place_without_recreating_or_resetting_permissions(self):
        cog,guild,_=self.context()
        self.assertEqual(await cog.apply_role_style(guild),2)
        self.assertEqual(self.member.id,20)
        self.assertEqual(self.member.name,'Member ®')
        self.assertEqual(self.support.name,'Support ®')
        self.assertEqual(set(self.member.edit.call_args.kwargs),{'name','reason'})
        self.unrelated.edit.assert_not_awaited()
        guild.create_role.assert_not_awaited()
        self.assertEqual(await cog.apply_role_style(guild),0)

    async def test_missing_configured_member_aborts_before_creating_any_role(self):
        cog,guild,_=self.context()
        self.roles.pop(20)
        with self.assertRaisesRegex(ValueError,'non esiste'):
            await cog.build(guild)
        guild.create_role.assert_not_awaited()

    async def test_member_access_moves_on_owned_public_channels_only(self):
        registry={'role:member':10,'cat:community':50,'cat:staff':51,'channel:general':52,'channel:welcome':53}
        cog,guild,_=self.context(registry)
        cog.bot.cfg['categories']['staff']=51
        cog.bot.cfg['channels']['welcome']=54  # Explicitly remapped, no longer the owned destination.
        old=role(10)
        access=discord.PermissionOverwrite(view_channel=True,send_messages=True)
        other=discord.PermissionOverwrite(view_channel=False)
        channels={}
        for number in (50,51,52,53,54):
            channel=MagicMock(spec=discord.TextChannel)
            channel.overwrites={old:access,self.unrelated:other}
            async def edit(_channel=channel,**kwargs):
                _channel.overwrites=kwargs['overwrites']
            channel.edit=AsyncMock(side_effect=edit)
            channels[number]=channel
        guild.get_channel=lambda n:channels.get(n)
        await cog.migrate_member_access(guild,registry)
        for number in (50,52):
            overwrites=channels[number].overwrites
            self.assertNotIn(old,overwrites)
            self.assertIs(overwrites[self.member],access)
            self.assertIs(overwrites[self.unrelated],other)
        for number in (51,53,54): channels[number].edit.assert_not_awaited()
        self.assertEqual(registry['member_access_role'],20)
        await cog.migrate_member_access(guild,registry)
        self.assertEqual(channels[50].edit.await_count,1)
