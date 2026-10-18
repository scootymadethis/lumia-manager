"""Website briefs, idempotent submission and a human approved quotation."""
import hashlib
import json
import re
import time

PLATFORMS = {'fivem':'FiveM','minecraft':'Minecraft','discord':'Discord','web':'Web','other':'Altro'}
SERVICES = {'complete':'Progetto completo','custom':'Funzione su misura','improve':'Migliorare un progetto','help':'Non so ancora'}
BUDGETS = {'discuss':'Da concordare','under500':'Fino a 500 €','500-1500':'500–1.500 €','1500-5000':'1.500–5.000 €','over5000':'Oltre 5.000 €'}
TIMELINES = {'flexible':'Da concordare','month':'Entro un mese, se possibile','quarter':'Nei prossimi tre mesi','date':'Ho una data da concordare'}
LABELS = {'name':'Nome del progetto','goal':'Obiettivo','features':'Funzioni richieste','technical':'Situazione attuale e integrazioni','texts':'Testi e contenuti','style':'Stile e riferimenti','deadline':'Data desiderata e contesto'}


def validate_brief(raw):
    if not isinstance(raw,dict): raise ValueError('Richiesta non valida.')
    result={}
    for key,options in [('platform',PLATFORMS),('service',SERVICES),('budget',BUDGETS),('timeline',TIMELINES)]:
        if raw.get(key) not in options: raise ValueError('Completa piattaforma, servizio, budget e tempi.')
        result[key]=raw[key]
    for key,maximum,minimum in [('name',120,3),('goal',2000,20),('features',2400,10),('technical',1200,0),('texts',2000,0),('style',1000,0),('deadline',200,0)]:
        value=raw.get(key,'')
        if not isinstance(value,str) or not minimum<=len(value.strip())<=maximum:
            raise ValueError(f'{LABELS[key]}: inserisci da {minimum} a {maximum} caratteri.')
        result[key]=value.strip()
    answers=raw.get('answers',[])
    if not isinstance(answers,list) or len(answers)>3: raise ValueError('Massimo tre approfondimenti.')
    result['answers']=[]
    for item in answers:
        if not isinstance(item,dict): raise ValueError('Approfondimento non valido.')
        question=item.get('question','');answer=item.get('answer','')
        if not isinstance(question,str) or not isinstance(answer,str) or not 1<=len(question.strip())<=240 or len(answer.strip())>1000:
            raise ValueError('Approfondimento troppo lungo o non valido.')
        if answer.strip(): result['answers'].append({'question':question.strip(),'answer':answer.strip()})
    if raw.get('acknowledged') is not True: raise ValueError('Conferma di voler richiedere un preventivo.')
    if result['timeline']=='date' and not result['deadline']: raise ValueError('Indica la data desiderata.')
    return result


class Intake:
    def __init__(self,orders):
        self.orders=orders;self.store=orders.store
        with self.store.lock,self.store.db:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS web_requests (
              order_id INTEGER PRIMARY KEY, submission TEXT UNIQUE NOT NULL,
              customer INTEGER NOT NULL, brief TEXT NOT NULL, fingerprint TEXT NOT NULL,
              quote TEXT NOT NULL DEFAULT '', created REAL NOT NULL)''')

    def get(self,number):
        with self.store.lock:
            row=self.store.db.execute('SELECT * FROM web_requests WHERE order_id=?',(number,)).fetchone()
        return {**dict(row),'brief':json.loads(row['brief'])} if row else None

    def submit(self,customer,key,raw):
        if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{20,80}',key): raise ValueError('Identificativo richiesta non valido. Ricarica il percorso.')
        brief=validate_brief(raw)
        encoded=json.dumps(brief,ensure_ascii=False,sort_keys=True)
        fingerprint=hashlib.sha256(encoded.encode()).hexdigest()
        now=time.time()
        with self.store.lock,self.store.db:
            existing=self.store.db.execute('SELECT * FROM web_requests WHERE submission=?',(key,)).fetchone()
            if existing:
                if existing['customer']!=customer or existing['fingerprint']!=fingerprint: raise ValueError('Questa richiesta è già stata inviata. Apri il progetto nel manager.')
                return self.orders.get(existing['order_id']),False
            count=self.store.db.execute('SELECT COUNT(*) FROM web_requests WHERE customer=? AND created>?',(customer,now-86400)).fetchone()[0]
            if count>=10: raise ValueError('Hai già inviato diverse richieste oggi. Scrivici dal progetto esistente.')
            details=f"{PLATFORMS[brief['platform']]} · {SERVICES[brief['service']]}\n\n{brief['goal']}\n\n{brief['features']}"
            cursor=self.store.db.execute('INSERT INTO orders(customer,title,total_cents,details,stage,created,updated) VALUES(?,?,0,?,\'bozza\',?,?)',(customer,brief['name'],details,now,now))
            number=cursor.lastrowid
            self.store.db.execute('INSERT INTO web_requests(order_id,submission,customer,brief,fingerprint,created) VALUES(?,?,?,?,?,?)',(number,key,customer,encoded,fingerprint,now))
            self.orders._audit(number,customer,'richiesta dal sito','Brief ricevuto. Prezzo e disponibilità da confermare dal team.')
            return self.orders.get(number),True

    def quote(self,number,cents,scope,actor):
        if type(cents) is not int or not 50<=cents<=100_000_000: raise ValueError('Il preventivo deve essere almeno 0,50 €.')
        if not isinstance(scope,str) or not 20<=len(scope.strip())<=8000: raise ValueError('Specifica cosa comprende il preventivo (20–8000 caratteri).')
        with self.store.lock,self.store.db:
            order=self.orders.get(number)
            if not self.get(number) or not order or order['stage']!='bozza': raise ValueError('Puoi inviare il preventivo solo da una richiesta in bozza.')
            if self.orders.payments(number) or self.orders.installments(number): raise ValueError('Il progetto contiene già movimenti o un piano. Non puoi modificarne il prezzo.')
            self.store.db.execute('UPDATE orders SET total_cents=?,stage=\'preventivo\',updated=? WHERE id=?',(cents,time.time(),number))
            self.store.db.execute('UPDATE web_requests SET quote=? WHERE order_id=?',(scope.strip(),number))
            self.orders._audit(number,actor,'preventivo inviato',f'Totale {cents/100:.2f} EUR; ambito: {scope.strip()}')

    def guard_stage(self,number,stage):
        brief=self.get(number)
        if brief and stage not in ('bozza','annullato') and not brief['quote']:
            raise ValueError('Prima invia il preventivo con importo e ambito del lavoro.')
