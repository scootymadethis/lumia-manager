"""Verify style migration boundaries and real log delivery without Discord login."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,MagicMock,patch

import discord
from bot import LumiaBot
from lumia.config import validate_config
from lumia.presentation import COLORS
from lumia.setup_server import ServerSetup


class PresentationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_bot_extensions_load_with_production_public_url(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=validate_config({'guild_id':123})
            bot=LumiaBot(cfg,config_path=Path(temp)/'config.json',data_dir=temp)
            try:
                with patch.dict('os.environ',{'LUMIA_PUBLIC_URL':'https://manager.lumiadevelopment.it'}):
                    async with bot:
                        for extension in ('setup_server','onboarding','verification','tickets','order_commands','moderation','community','events'):
                            await bot.load_extension('lumia.'+extension)
                        self.assertEqual(len(bot.extensions),8)
                        self.assertIsNotNone(bot.tree.get_command('ordina'))
                        panel=bot.get_cog('Tickets').persistent_views[0]
                        self.assertTrue(panel.is_persistent())
                        self.assertEqual(panel.to_components()[0]['components'][0]['type'],3)
            finally:
                bot.store.close()

    async def test_order_logs_get_customer_avatar_and_project_button_automatically(self):
        with tempfile.TemporaryDirectory() as temp:
            bot=LumiaBot(validate_config({'guild_id':123,'channels':{'staff_orders':55}}),
                         config_path=Path(temp)/'config.json',data_dir=temp)
            channel=MagicMock(spec=discord.TextChannel)
            channel.send=AsyncMock()
            member=NS(display_avatar=NS(url='https://cdn.discordapp.com/avatars/10/avatar.png'))
            guild=NS(get_member=lambda number:member if number==10 else None)
            try:
                async with bot:
                    order=bot.orders.create(10,'Progetto',10000)
                    with patch.object(bot,'get_channel',return_value=channel),patch.object(bot,'get_guild',return_value=guild),patch.dict('os.environ',{'LUMIA_PUBLIC_URL':'https://manager.example'}):
                        await bot.log('staff_orders','Stato aggiornato',fields=[('Ordine',f'#{order["id"]}',True)])
                    payload=channel.send.call_args.kwargs
                    self.assertEqual(payload['view'].children[0].url,f'https://manager.example/orders/{order["id"]}')
                    self.assertEqual(payload['embed'].thumbnail.url,member.display_avatar.url)
                    self.assertIn('<@10>',[field.value for field in payload['embed'].fields])
                    self.assertEqual(payload['allowed_mentions'].to_dict()['parse'],[])
            finally:bot.store.close()

    async def test_style_update_uses_current_configured_ids_and_is_idempotent(self):
        cfg=validate_config({'guild_id':123,'channels':{'welcome':55,'mod_log':77}})
        registry={'channel:welcome':55,'channel:mod_log':66}
        channels={}
        for number in (55,66,77):
            channel=MagicMock(spec=discord.TextChannel)
            channel.id,channel.name,channel.topic=number,'old-name',None
            async def edit(_channel=channel,**kwargs):
                for key,value in kwargs.items():
                    if key!='reason': setattr(_channel,key,value)
                return _channel
            channel.edit=AsyncMock(side_effect=edit)
            channels[number]=channel
        bot=NS(cfg=cfg,store=NS(get=lambda *args:registry))
        cog=ServerSetup(bot)
        guild=NS(get_channel=lambda number:channels.get(number))
        self.assertEqual(await cog.apply_style(guild),2)
        payload=channels[55].edit.call_args.kwargs
        self.assertEqual(set(payload),{'name','topic','reason'})
        channels[66].edit.assert_not_awaited()
        channels[77].edit.assert_awaited_once()
        self.assertEqual(await cog.apply_style(guild),0)
        self.assertEqual(channels[55].edit.await_count,1)

    async def test_log_sends_structured_embed_without_notification_mentions(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=validate_config({'guild_id':123,'channels':{'mod_log':55}})
            bot=LumiaBot(cfg,config_path=Path(temp)/'config.json',data_dir=temp)
            channel=MagicMock(spec=discord.TextChannel)
            channel.send=AsyncMock()
            try:
                async with bot:
                    with patch.object(bot,'get_channel',return_value=channel):
                        sent=await bot.log('mod_log','Dettaglio @everyone',title='Controllo',level='warning',
                                           fields=[('Membro','<@7>\n`7`',True)])
                    self.assertTrue(sent)
                    payload=channel.send.call_args.kwargs
                    self.assertNotIn('content',payload)
                    self.assertIn('Controllo',payload['embed'].title)
                    self.assertEqual(payload['embed'].fields[0].value,'<@7>\n`7`')
                    self.assertEqual(payload['embed'].color.value,COLORS['warning'])
                    self.assertIsNotNone(payload['embed'].timestamp)
                    self.assertEqual(payload['allowed_mentions'].to_dict()['parse'],[])
            finally:
                bot.store.close()
