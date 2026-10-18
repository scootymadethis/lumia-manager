"""Rename existing resources without changing IDs/access or touching ServerStats."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,MagicMock,patch
import discord
from discord import app_commands
from lumia.core import Store
from lumia.config import validate_config
from lumia.presentation import channel_name,small_caps
from lumia.setup_server import ServerSetup,CHANNEL_DEFS,CAT_NAMES,ROLE_DEFS
from lumia.community import Community


def channel(number,name,kind=discord.TextChannel):
    item=MagicMock(spec=kind)
    item.id,item.name=number,name
    item.topic=None;item.members=[]
    async def edit(**values):
        for key,value in values.items():
            if key!='reason':setattr(item,key,value)
        return item
    item.edit=AsyncMock(side_effect=edit);item.delete=AsyncMock()
    return item


class ChannelNamesTests(unittest.TestCase):
    def test_requested_alphabet_emoji_digits_and_idempotence(self):
        self.assertEqual(small_caps('abcdefghi lmnopq rstuvz'),'ᴀʙᴄᴅᴇꜰɢʜɪ ʟᴍɴᴏᴘQ ʀꜱᴛᴜᴠᴢ')
        name=channel_name('📋・Commissioni 2026')
        self.assertEqual(name,'📋・ᴄᴏᴍᴍɪꜱꜱɪᴏɴɪ-2026')
        self.assertEqual(channel_name(name),name)
        self.assertEqual(channel_name('🎫・ticket-0012-minecraft'),'🎫・ᴛɪᴄᴋᴇᴛ-0012-ᴍɪɴᴇᴄʀᴀꜰᴛ')
        self.assertEqual(small_caps('LUMIA DEVELOPMENT'),'ʟᴜᴍɪᴀ ᴅᴇᴠᴇʟᴏᴘᴍᴇɴᴛ')

    def test_commissioni_keeps_stable_configuration_key(self):
        self.assertEqual(next(name for key,name,_ in CHANNEL_DEFS if key=='staff_orders'),'📋・ᴄᴏᴍᴍɪꜱꜱɪᴏɴɪ')
        self.assertNotIn('member_counter',[key for key,*_ in CHANNEL_DEFS])


class ChannelMigrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db.sqlite');self.addCleanup(self.store.close)
        self.cfg=validate_config({'guild_id':123,'roles':{'member':50,'management':51},'channels':{'staff_orders':70}})
        self.bot=NS(cfg=self.cfg,store=self.store,save_config=MagicMock())
        self.resources={}
        self.guild=NS(id=123,owner_id=1,me=NS(id=900,guild_permissions=NS(view_audit_log=True)),
            get_channel=lambda number:self.resources.get(number),create_text_channel=AsyncMock(),create_voice_channel=AsyncMock(),create_category=AsyncMock())
        self.cog=ServerSetup(self.bot)

    async def test_existing_commission_and_ticket_channels_rename_in_place(self):
        self.resources[70]=channel(70,'📋・commesse')
        self.resources[71]=channel(71,'🎫・ticket-0001-fivem')
        self.resources[72]=channel(72,'🔊・lounge',discord.VoiceChannel)
        self.resources[73]=channel(73,'LUMIA DEVELOPMENT',discord.CategoryChannel)
        self.resources[74]=channel(74,'Members: 400',discord.VoiceChannel)
        self.store.put('setup','resources',{'lounge':72,'cat:info':73})
        ticket=self.store.reserve_ticket(201,'fivem',{})
        self.store.update_ticket(ticket['id'],channel=71,state='open')
        self.assertEqual(await self.cog.apply_style(self.guild),4)
        self.assertEqual(self.resources[70].name,'📋・ᴄᴏᴍᴍɪꜱꜱɪᴏɴɪ')
        self.assertEqual(self.resources[71].name,'🎫・ᴛɪᴄᴋᴇᴛ-0001-ꜰɪᴠᴇᴍ')
        self.assertEqual(self.store.ticket(ticket['id'])['channel'],71)
        for number in (70,71,72,73):
            self.assertEqual(self.resources[number].id,number)
            self.assertTrue(set(self.resources[number].edit.call_args.kwargs)<={'name','topic','reason'})
            self.resources[number].delete.assert_not_awaited()
        self.resources[74].edit.assert_not_awaited()
        self.assertEqual(await self.cog.apply_style(self.guild),0)
        self.guild.create_text_channel.assert_not_awaited();self.guild.create_voice_channel.assert_not_awaited();self.guild.create_category.assert_not_awaited()

    async def test_new_command_changes_no_roles_and_reports_counts(self):
        self.resources[70]=channel(70,'commesse')
        self.resources[70].topic='Descrizione personalizzata'
        i=NS(guild=self.guild,user=NS(id=2,guild=self.guild,roles=[NS(id=51)]),
            response=NS(defer=AsyncMock(),is_done=lambda:True),followup=NS(send=AsyncMock()))
        self.cog.apply_role_style=AsyncMock()
        await ServerSetup.channels.callback(self.cog,i)
        self.assertEqual(self.resources[70].name,'📋・ᴄᴏᴍᴍɪꜱꜱɪᴏɴɪ')
        self.cog.apply_role_style.assert_not_awaited()
        self.assertEqual(self.resources[70].topic,'Descrizione personalizzata')
        self.assertEqual(set(self.resources[70].edit.call_args.kwargs),{'name','reason'})
        self.assertIn('ID, messaggi, permessi',i.followup.send.call_args.kwargs['embed'].description)

    async def test_closed_ticket_keeps_state_and_custom_label_when_styled(self):
        self.resources[71]=channel(71,'🎫・ticket-0001-Progetto Speciale')
        ticket=self.store.reserve_ticket(201,'custom',{})
        self.store.update_ticket(ticket['id'],channel=71,state='closed')
        await self.cog.apply_style(self.guild)
        self.assertEqual(self.resources[71].name,'🎫・ᴛɪᴄᴋᴇᴛ-0001-ᴘʀᴏɢᴇᴛᴛᴏ-ꜱᴘᴇᴄɪᴀʟᴇ')
        self.assertEqual(self.store.ticket(ticket['id'])['state'],'closed')
        self.resources[71].delete.assert_not_awaited()

    async def test_lowercased_ascii_q_does_not_trigger_repeated_discord_renames(self):
        self.cfg['channels']['faq']=75
        self.resources[75]=channel(75,'❓・ꜰᴀq')
        await self.cog.apply_style(self.guild,topics=False)
        self.resources[75].edit.assert_not_awaited()

    async def test_channel_command_requires_management_and_configured_guild(self):
        i=NS(guild=self.guild,user=NS(id=2,guild=self.guild,roles=[]),response=NS(defer=AsyncMock()))
        with self.assertRaises(app_commands.CheckFailure):await ServerSetup.channels.callback(self.cog,i)
        i.user.roles=[NS(id=51)];self.guild.id=456
        with self.assertRaises(app_commands.CheckFailure):await ServerSetup.channels.callback(self.cog,i)
        i.response.defer.assert_not_awaited()

    def legacy_counter(self,creator=900,occupied=False,audit_permission=True):
        self.cfg['channels']['member_counter']=80
        counter=channel(80,'👥・membri-400',discord.VoiceChannel)
        counter.members=[NS(id=9)] if occupied else []
        self.resources[80]=counter
        self.guild.me.guild_permissions.view_audit_log=audit_permission
        async def logs(**kwargs):
            self.assertEqual(kwargs,{'limit':200,'action':discord.AuditLogAction.channel_create})
            yield NS(target=NS(id=80),user=NS(id=creator))
        self.guild.audit_logs=MagicMock(side_effect=logs)
        return counter

    async def test_deletes_only_empty_counter_with_lumia_creation_proof(self):
        counter=self.legacy_counter()
        self.assertEqual(await self.cog.retire_counter(self.guild),{'removed':True,'review':0})
        counter.delete.assert_awaited_once();self.assertEqual(self.cfg['channels']['member_counter'],0)
        self.bot.save_config.assert_called_once()
        self.assertEqual(await self.cog.retire_counter(self.guild),{'removed':False,'review':0})
        counter.delete.assert_awaited_once()

    async def test_serverstats_counter_is_never_deleted_or_renamed(self):
        counter=self.legacy_counter(creator=901)
        self.assertEqual(await self.cog.retire_counter(self.guild),{'removed':False,'review':80})
        counter.delete.assert_not_awaited();counter.edit.assert_not_awaited()
        self.assertEqual(self.cfg['channels']['member_counter'],0)
        await self.cog.apply_style(self.guild)
        counter.edit.assert_not_awaited()

    async def test_occupied_channel_is_retired_without_deletion(self):
        counter=self.legacy_counter(occupied=True)
        self.assertEqual((await self.cog.retire_counter(self.guild))['review'],80)
        counter.delete.assert_not_awaited();self.guild.audit_logs.assert_not_called()

    async def test_a_repurposed_lumia_voice_channel_is_not_deleted(self):
        counter=self.legacy_counter()
        counter.name='🔊・Lounge privata'
        self.assertEqual((await self.cog.retire_counter(self.guild))['review'],80)
        counter.delete.assert_not_awaited()

    async def test_missing_audit_permission_leaves_legacy_channel_untouched(self):
        counter=self.legacy_counter(audit_permission=False)
        self.assertEqual((await self.cog.retire_counter(self.guild))['review'],80)
        counter.delete.assert_not_awaited();self.guild.audit_logs.assert_not_called()

    async def test_deleted_counter_is_detached_without_replacement(self):
        self.cfg['channels']['member_counter']=80
        self.assertEqual(await self.cog.retire_counter(self.guild),{'removed':False,'review':0})
        self.assertEqual(self.cfg['channels']['member_counter'],0)
        self.guild.create_voice_channel.assert_not_awaited()

    async def test_setup_never_creates_a_member_counter(self):
        registry={};roles={}
        for index,(key,name,_) in enumerate(ROLE_DEFS,100):
            role=MagicMock(spec=discord.Role)
            role.id,role.name,role.managed=index,name,False
            role.is_default.return_value=False
            roles[index]=role;self.cfg['roles'][key]=index;registry['role:'+key]=index
        for index,(key,name) in enumerate(CAT_NAMES.items(),200):
            self.resources[index]=channel(index,name,discord.CategoryChannel);registry['cat:'+key]=index
            if key in self.cfg['categories']:self.cfg['categories'][key]=index
        for index,(key,name,_) in enumerate(CHANNEL_DEFS,300):
            self.resources[index]=channel(index,name);registry['channel:'+key]=index
            if key in self.cfg['channels']:self.cfg['channels'][key]=index
        registry['lounge']=500;self.resources[500]=channel(500,'Lounge',discord.VoiceChannel)
        self.store.put('setup','resources',registry)
        self.guild.get_role=lambda number:roles.get(number)
        self.guild.edit_role_positions=AsyncMock()
        self.cog.migrate_member_access=AsyncMock();self.cog.apply_style=AsyncMock()
        await self.cog.build(self.guild)
        self.guild.create_voice_channel.assert_not_awaited()

    async def test_maintenance_cleans_security_metadata_without_accessing_serverstats(self):
        self.store.put('security_seen','old',{'at':time.time()-90000})
        self.store.put('security_seen','new',{'at':time.time()})
        bot=NS(store=self.store,get_guild=MagicMock(side_effect=AssertionError('No statistics access')))
        cog=Community(bot)
        await cog.maintenance()
        self.assertIsNone(self.store.get('security_seen','old'))
        self.assertIsNotNone(self.store.get('security_seen','new'))
        bot.get_guild.assert_not_called()
