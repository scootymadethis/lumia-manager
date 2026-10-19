"""Deployment checks: Git trees, offline SQLite backup and local HTTP."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path,PurePosixPath
import sqlite3
import subprocess
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
import zipfile

PROTECTED=('compose.yaml','compose.yml','compose.override.yaml','compose.override.yml',
           'docker-compose.yaml','docker-compose.yml','docker-compose.override.yml',
           'Caddyfile','server_texts.json')
DEPLOY_INFRA=('.gitattributes','GITHUB-ACTIONS.md','.github/workflows/deploy.yml',
              'scripts/deploy.sh','scripts/deploy_checks.py','tests/test_deploy_checks.py')


def git(*args):
    return subprocess.check_output(['git',*args],stderr=subprocess.DEVNULL)


def guard(before,after):
    """A main push cannot silently replace local data or deployment settings."""
    for revision in (before,after):
        paths=git('ls-tree','-r','--name-only','-z',revision).decode('utf-8').split('\0')
        for path in filter(None,paths):
            p=PurePosixPath(path)
            secret=(p.name=='.env' or (p.name.startswith('.env.') and p.name!='.env.example')
                    or p.name in ('config.json','bootstrap.json')
                    or p.parts[0] in ('data','backups','.venv','venv')
                    or p.suffix in ('.sqlite','.sqlite3','.db'))
            if secret:raise ValueError(f'File privato tracciato in Git: {path}. Deploy interrotto.')
    changed=git('diff','--name-only',before,after,'--',*PROTECTED).decode().strip()
    if changed:
        raise ValueError('Il commit modifica configurazioni operative da applicare manualmente: '+', '.join(changed.splitlines()))
    mandatory={'.env','config.json','data','backups','.git'}
    rules=set(git('show',after+':.dockerignore').decode().splitlines())
    if not mandatory<=rules or any(line.strip().startswith('!') and line.strip()!='!.env.example' for line in rules):
        raise ValueError('Mantieni le esclusioni private del .dockerignore prima del deploy.')


def worktree():
    if git('diff','--cached','--name-only').strip():
        raise ValueError('Ci sono file in staging: completa il commit prima del deploy.')
    changed=set(filter(None,git('diff','--name-only','-z').decode('utf-8').split('\0')))
    if changed-set(PROTECTED)-set(DEPLOY_INFRA):
        raise ValueError('Modifiche locali al codice non committate. Salvale prima del deploy.')


def verify_backup(folder):
    archives=list(Path(folder).glob('lumia-*.zip'))
    if len(archives)!=1:raise ValueError('Atteso un backup SQLite completo.')
    with zipfile.ZipFile(archives[0]) as archive:
        if archive.testzip() is not None or not {'lumia.sqlite','config.json'}<=set(archive.namelist()):
            raise ValueError('Archivio backup incompleto o corrotto.')
        # Extract a single fixed filename, never arbitrary archive paths.
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'lumia.sqlite'
            path.write_bytes(archive.read('lumia.sqlite'))
            with closing(sqlite3.connect(path)) as connection:
                if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise ValueError('Verifica integrità SQLite fallita.')


def health():
    port=int(os.getenv('WEB_PORT','8080'))
    public=os.environ['LUMIA_PUBLIC_URL']
    checks=[(public,'/login')]
    if os.getenv('LUMIA_SITE_URL'):checks.append((os.environ['LUMIA_SITE_URL'],'/'))
    for origin,path in checks:
        host=urlsplit(origin).netloc
        if not host:raise ValueError('Hostname pubblico non configurato.')
        request=Request(f'http://127.0.0.1:{port}'+path,headers={'Host':host})
        with urlopen(request,timeout=5) as response:
            if response.status!=200:raise ValueError('Controllo HTTP fallito.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    commands=parser.add_subparsers(dest='action',required=True)
    g=commands.add_parser('guard');g.add_argument('before');g.add_argument('after')
    b=commands.add_parser('backup');b.add_argument('folder')
    commands.add_parser('health')
    commands.add_parser('worktree')
    args=parser.parse_args()
    try:
        if args.action=='guard':guard(args.before,args.after)
        elif args.action=='backup':verify_backup(args.folder)
        elif args.action=='worktree':worktree()
        else:health()
    except Exception as error:
        parser.exit(1,str(error)+'\n')
