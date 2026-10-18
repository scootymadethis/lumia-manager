"""Opt-in only. Changes three AI settings, keeping every other .env entry."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import shutil


def configure(path,enabled):
    path=Path(path)
    text=path.read_text(encoding='utf-8-sig')
    updates={'LUMIA_AI_ENABLED':'true' if enabled else 'false',
             'LUMIA_OLLAMA_URL':'http://ollama:11434','LUMIA_AI_MODEL':'qwen3:4b'}
    for key,value in updates.items():
        pattern=r'(?m)^\s*(?:export\s+)?'+re.escape(key)+r'=[^\r\n]*'
        if re.search(pattern,text): text=re.sub(pattern,key+'='+value,text)
        else: text=text.rstrip()+'\n'+key+'='+value+'\n'
    backup=path.with_name('.env.before-ai-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path,backup)
    if os.name!='nt': backup.chmod(0o600)
    temporary=path.with_name('.env.ai-tmp')
    try:
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as handle:handle.write(text)
        if os.name!='nt': temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()
    return backup


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Configura l’assistente locale senza sostituire il tuo .env.')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--enable',action='store_true');mode.add_argument('--disable',action='store_true')
    args=parser.parse_args()
    backup=configure(Path(__file__).resolve().parent/'.env',args.enable)
    print('AI locale '+('abilitata' if args.enable else 'disabilitata')+'. Backup: '+backup.name)
    print('Ricrea app con Docker Compose per applicare la modifica. Le altre impostazioni sono conservate.')
