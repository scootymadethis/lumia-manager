"""Real Git histories and real SQLite archives, without Docker or credentials."""
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from scripts.deploy_checks import guard,worktree,verify_backup


@unittest.skipUnless(shutil.which('git'),'Git not installed in the application image')
class DeploymentGitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.before=Path.cwd();self.root=Path(self.temp.name);os.chdir(self.root)
        self.addCleanup(os.chdir,self.before)
        self.git('init','-q','-b','main')
        self.git('config','user.name','Lumia test');self.git('config','user.email','test@example.invalid')
        (self.root/'.dockerignore').write_text('.env\n.env.*\n!.env.example\nconfig.json\ndata\nbackups\n.git\n')
        (self.root/'bot.py').write_text('old')
        (self.root/'compose.yaml').write_text('local configuration')
        self.original=self.commit()

    def git(self,*args):
        return subprocess.check_output(['git',*args],stderr=subprocess.DEVNULL).decode().strip()

    def commit(self):
        self.git('add','.');self.git('commit','-qm','test');return self.git('rev-parse','HEAD')

    def test_normal_code_update_is_allowed(self):
        (self.root/'bot.py').write_text('new');updated=self.commit()
        guard(self.original,updated);worktree()

    def test_deployment_config_changes_are_blocked(self):
        (self.root/'compose.yaml').write_text('different');updated=self.commit()
        with self.assertRaisesRegex(ValueError,'configurazioni operative'):guard(self.original,updated)

    def test_server_texts_changes_are_allowed(self):
        (self.root/'server_texts.json').write_text('{"welcome":"Aggiornato"}');updated=self.commit()
        guard(self.original,updated)

    def test_secrets_and_sqlite_in_commit_are_blocked(self):
        for name in ('.env','.env.before-ai-123','config.json','data/db.sqlite'):
            self.git('reset','--hard',self.original)
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('private')
            updated=self.commit()
            with self.assertRaisesRegex(ValueError,'File privato'):guard(self.original,updated)

    def test_missing_docker_exclusion_is_blocked(self):
        (self.root/'.dockerignore').write_text('.git\n');updated=self.commit()
        with self.assertRaisesRegex(ValueError,'dockerignore'):guard(self.original,updated)

    def test_local_operator_configuration_can_remain_modified(self):
        (self.root/'compose.yaml').write_text('operator customization');worktree()

    def test_uncommitted_code_or_staging_blocks_deploy(self):
        (self.root/'bot.py').write_text('work in progress')
        with self.assertRaisesRegex(ValueError,'codice'):worktree()
        self.git('add','bot.py')
        with self.assertRaisesRegex(ValueError,'staging'):worktree()


class DeploymentBackupTests(unittest.TestCase):
    def test_real_backup_passes_integrity_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'db.sqlite'
            with closing(sqlite3.connect(path)) as db:db.execute('CREATE TABLE sample(id INTEGER)');db.commit()
            with zipfile.ZipFile(root/'lumia-test.zip','w') as archive:
                archive.write(path,'lumia.sqlite');archive.writestr('config.json','{}')
            verify_backup(root)

    def test_missing_or_corrupt_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaises(ValueError):verify_backup(root)
            with zipfile.ZipFile(root/'lumia-test.zip','w') as archive:
                archive.writestr('lumia.sqlite',b'corrupted');archive.writestr('config.json','{}')
            with self.assertRaises(sqlite3.DatabaseError):verify_backup(root)
