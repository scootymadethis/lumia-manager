import importlib.util
import tempfile
import unittest
from pathlib import Path

source=Path(__file__).resolve().parents[1]/'configure-local-ai.py'
spec=importlib.util.spec_from_file_location('configure_ai',source)
configuration=importlib.util.module_from_spec(spec);spec.loader.exec_module(configuration)


class AIConfigurationTests(unittest.TestCase):
    def test_enable_disable_preserves_secrets_and_creates_private_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            env=Path(folder)/'.env'
            original='DISCORD_TOKEN=keep-this\nSTRIPE_SECRET_KEY=keep-also\n# comment\nCUSTOM=value\n'
            env.write_text(original,encoding='utf-8')
            backup=configuration.configure(env,True)
            self.assertEqual(backup.read_text(),original)
            enabled=env.read_text()
            self.assertTrue(enabled.startswith(original))
            self.assertIn('LUMIA_AI_ENABLED=true',enabled)
            configuration.configure(env,False)
            disabled=env.read_text()
            self.assertIn('LUMIA_AI_ENABLED=false',disabled)
            self.assertEqual(disabled.count('LUMIA_AI_ENABLED='),1)
            self.assertTrue(disabled.startswith(original))

    def test_existing_ai_settings_are_updated_without_duplicate_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            env=Path(folder)/'.env'
            env.write_text('LUMIA_AI_ENABLED=false\nLUMIA_AI_MODEL=old\nexport LUMIA_OLLAMA_URL=http://localhost:11434\nWEB_ENABLED=true\n')
            configuration.configure(env,True)
            text=env.read_text()
            self.assertEqual(text.count('LUMIA_AI_MODEL='),1)
            self.assertEqual(text.count('LUMIA_OLLAMA_URL='),1)
            self.assertIn('LUMIA_AI_MODEL=qwen3:4b',text)
            self.assertIn('WEB_ENABLED=true',text)
