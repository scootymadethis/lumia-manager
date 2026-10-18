"""Container bootstrap: generated config and state stay in the data volume."""
import os
from pathlib import Path
import shutil
import sys

data=Path(os.environ.get('LUMIA_DATA_DIR','data'))
data.mkdir(parents=True,exist_ok=True)
target=data/'config.json'
if not target.exists():
    bootstrap=Path('bootstrap.json')
    shutil.copyfile(bootstrap if bootstrap.exists() else 'config.example.json',target)
os.execv(sys.executable,[sys.executable,'bot.py','--config',str(target)])
