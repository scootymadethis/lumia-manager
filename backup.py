"""Create an offline backup after stopping the bot, without secret files."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
import tempfile
import zipfile
from contextlib import closing

parser=argparse.ArgumentParser(description='Esegui a bot fermo per un backup coerente di database e trascrizioni.')
parser.add_argument('--data',default='data')
parser.add_argument('--output',default='backups')
args=parser.parse_args()
data=Path(args.data).resolve()
output=Path(args.output).resolve()
if not (data/'lumia.sqlite').is_file():
    parser.error('Database non trovato nella cartella indicata.')
output.mkdir(parents=True,exist_ok=True)
name=output/('lumia-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.zip')
with tempfile.TemporaryDirectory() as temp:
    snapshot=Path(temp)/'lumia.sqlite'
    with closing(sqlite3.connect(data/'lumia.sqlite')) as source,closing(sqlite3.connect(snapshot)) as dest:
        source.backup(dest)
    with zipfile.ZipFile(name,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot,'lumia.sqlite')
        for path in data.rglob('*'):
            if path.is_file() and path.suffix=='.txt' and path.name!='.env':
                archive.write(path,path.relative_to(data))
        cfg=data/'config.json'
        if cfg.is_file():
            archive.write(cfg,'config.json')
        elif Path('config.json').is_file():
            archive.write('config.json','config.json')
print(f'Backup creato: {name}')
