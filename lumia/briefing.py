"""Optional local Ollama questions. No tools, pricing or order mutations."""
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
import httpx

QUESTIONS={
 'fivem':['Hai già un server o partiamo da zero?','Cosa ti piacerebbe far fare ai giocatori?'],
 'minecraft':['Hai già un server o partiamo da zero?','Che tipo di gioco ti piace?'],
 'discord':['Hai già un server Discord?','Cosa vorresti che facesse il bot?'],
 'web':['Hai già un sito?','Cosa vorresti che le persone potessero fare sul sito?'],
 'other':['A cosa ti servirebbe il progetto?','Hai un esempio di qualcosa che ti piace?']}

SCHEMA={'type':'object','additionalProperties':False,'properties':{'questions':{'type':'array','minItems':1,'maxItems':2,'items':{'type':'string','minLength':10,'maxLength':240}}},'required':['questions']}


class Briefing:
    def __init__(self,*,transport=None):
        self.enabled=os.getenv('LUMIA_AI_ENABLED','false').lower()=='true'
        self.base=os.getenv('LUMIA_OLLAMA_URL','http://ollama:11434').rstrip('/')
        self.model=os.getenv('LUMIA_AI_MODEL','qwen3:4b')
        self.transport=transport
        self.lock=asyncio.Lock()
        parsed=urlsplit(self.base)
        # Local hosts only; this is never a general purpose URL fetch endpoint.
        if self.enabled and (parsed.scheme!='http' or parsed.hostname not in ('ollama','localhost','127.0.0.1','host.docker.internal') or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise RuntimeError('LUMIA_OLLAMA_URL deve indicare Ollama locale (http://ollama:11434).')

    async def questions(self,raw,use_ai=False):
        platform=raw.get('platform','other') if isinstance(raw,dict) else 'other'
        fallback={'questions':QUESTIONS.get(platform,QUESTIONS['other']),'source':'guided'}
        if not self.enabled or not use_ai: return fallback
        if self.lock.locked(): return {**fallback,'unavailable':True}
        # Exclude names, supplied texts, files, credentials, account information and payments.
        context={key:str(raw.get(key,''))[:2400] for key in ('platform','service','goal','features','technical')}
        system=(Path(__file__).parent/'briefing-guide.txt').read_text(encoding='utf-8')
        try:
            async with self.lock, httpx.AsyncClient(transport=self.transport,timeout=httpx.Timeout(35,connect=3),trust_env=False) as http:
                async with http.stream('POST',self.base+'/api/chat',json={'model':self.model,'stream':False,'think':False,'keep_alive':'5m','format':SCHEMA,
                    'messages':[{'role':'system','content':system+'\nSchema JSON: '+json.dumps(SCHEMA)},{'role':'user','content':json.dumps(context,ensure_ascii=False)}],
                    'options':{'temperature':0,'num_predict':400,'num_ctx':4096}}) as response:
                    response.raise_for_status()
                    content=bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content)>32768: raise ValueError('Response too large')
            result=json.loads(json.loads(content)['message']['content'])
            questions=result['questions']
            if not isinstance(questions,list) or not 1<=len(questions)<=2 or any(not isinstance(q,str) or not 10<=len(q.strip())<=240 for q in questions): raise ValueError('Invalid questions')
            if len({q.strip().casefold() for q in questions})!=len(questions) or any(re.search(r'https?://|password|token|carta di credito|numero di carta',q,re.I) for q in questions): raise ValueError('Unsafe or duplicate questions')
            return {'questions':[q.strip() for q in questions],'source':'local-ai'}
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            return {**fallback,'unavailable':True}
