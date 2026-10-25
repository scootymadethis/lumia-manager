import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,MagicMock
import discord
from lumia.core import Store
from lumia.config import validate_config


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store=Store(':memory:');self.addCleanup(self.store.close)
        self.role=MagicMock(spec=discord.Role);self.role.managed=False
        self.role.is_default.return_value=False;self.role.permissions=discord.Permissions.none()
        self.role.__lt__.return_value=True
        self.channel=MagicMock(spec=discord.TextChannel)
        self.channel.permissions_for.return_value=discord.Permissions.all()
        self.channel.fetch_message=AsyncMock(side_effect=discord.NotFound(NS(status=404,reason='Not Found'),'Deleted'))
        self.guild=NS(default_role=NS(id=1),me=NS(top_role=NS(id=999),guild_permissions=discord.Permissions.all()),
                      get_channel=lambda n:self.channel if n==55 else None,get_role=lambda n:self.role if n else None)
        self.cfg=validate_config({'guild_id':1,'roles':{'member':20,'unverified':21},'channels':{'verification':55}})
        self.bot=NS(cfg=self.cfg,store=self.store,is_ready=lambda:True,get_cog=lambda n:None)

    async def test_effective_permission_and_missing_panel_are_reported_without_mutations(self):
        from lumia.diagnostics import inspect_discord
        self.store.put('panels','verification',777)
        self.channel.permissions_for.return_value=discord.Permissions(view_channel=True)
        before=list(self.store.db.iterdump())
        issues=await inspect_discord(self.bot,self.guild)
        self.assertTrue(any('send_messages' in item for item in issues))
        self.assertTrue(any('Pannello verification' in item for item in issues))
        self.assertEqual(before,list(self.store.db.iterdump()))

    async def test_privileged_member_role_and_public_staff_channel_are_flagged(self):
        from lumia.diagnostics import inspect_discord
        self.role.permissions=discord.Permissions(administrator=True)
        self.cfg['channels']['staff_orders']=55
        issues=await inspect_discord(self.bot,self.guild)
        self.assertTrue(any('Ruolo pubblico non sicuro: member' in item for item in issues))
        self.assertTrue(any('pubblicamente' in item and 'staff_orders' in item for item in issues))

    async def test_gateway_not_ready_is_reported(self):
        from lumia.diagnostics import inspect_discord
        self.bot.is_ready=lambda:False
        issues=await inspect_discord(self.bot,self.guild)
        self.assertTrue(any('Gateway' in item for item in issues))

    async def test_staff_log_exposed_only_to_optional_interest_role_is_flagged(self):
        from lumia.diagnostics import inspect_discord
        web=MagicMock(spec=discord.Role)
        web.managed=False;web.is_default.return_value=False
        web.permissions=discord.Permissions.none();web.__lt__.return_value=True
        self.cfg['roles']['web']=22
        self.cfg['channels']['staff_orders']=55
        self.guild.get_role=lambda n:web if n==22 else self.role if n else None
        self.channel.permissions_for.side_effect=lambda actor: (
            discord.Permissions.all() if actor is self.guild.me or actor is web else discord.Permissions.none())
        issues=await inspect_discord(self.bot,self.guild)
        self.assertTrue(any('staff_orders' in item and 'ruolo web' in item for item in issues))
