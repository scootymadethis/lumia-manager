import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
import discord
from bot import LumiaBot
from lumia.config import validate_config


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_cog_registers_valid_guild_commands_without_login(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=validate_config({'guild_id':123})
            bot=LumiaBot(cfg,config_path=Path(temp)/'config.json',data_dir=temp)
            try:
                async with bot:
                    with patch.object(bot.tree,'sync',new=AsyncMock(return_value=[])):
                        await bot.setup_hook()
                    commands=bot.tree.get_commands(guild=discord.Object(id=123))
                    names={c.name for c in commands}
                    self.assertNotIn('statistiche',names)
                    self.assertTrue({'server','ticket','ordine','faq','pannelli','verifica'}.issubset(names))
                    server=next(c for c in commands if c.name=='server')
                    self.assertTrue({'stile','canali','anteprima','embed'}.issubset({c.name for c in server.commands}))
                    verification=next(c for c in commands if c.name=='verifica')
                    self.assertEqual({'stato','attiva','disattiva'},{c.name for c in verification.commands})
                    for command in commands:
                        payload=command.to_dict(bot.tree)
                        self.assertLessEqual(len(payload.get('options',[])),25)
            finally:
                bot.store.close()
