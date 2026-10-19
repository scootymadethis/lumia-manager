"""Project conversations and delivery reviews. Money stays in the order ledger."""
import time
from urllib.parse import urlsplit
from .orders import _text


class Workspace:
    def __init__(self,orders):
        self.orders,self.store=orders,orders.store
        with self.store.lock,self.store.db:
            self.store.db.executescript('''
                CREATE TABLE IF NOT EXISTS project_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
                    author INTEGER NOT NULL, author_name TEXT NOT NULL, staff INTEGER NOT NULL,
                    body TEXT NOT NULL, internal INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS project_messages_order ON project_messages(order_id,created);
                CREATE TABLE IF NOT EXISTS project_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
                    author INTEGER NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
                    description TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    reviewer INTEGER, feedback TEXT NOT NULL DEFAULT '', reviewed REAL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS project_deliveries_order ON project_deliveries(order_id,created);
            ''')

    def _order(self,number):
        order=self.orders.get(number)
        if not order:
            raise ValueError('Progetto non trovato.')
        return order

    def message(self,number,author,name,body,*,staff=False,internal=False):
        self._order(number)
        if internal and not staff:
            raise ValueError('Le note interne sono riservate a Management.')
        body=_text(body,'Messaggio',4000)
        name=_text(name,'Nome',100)
        with self.store.lock,self.store.db:
            cursor=self.store.db.execute('''INSERT INTO project_messages
                (order_id,author,author_name,staff,body,internal,created) VALUES(?,?,?,?,?,?,?)''',
                (number,author,name,int(staff),body,int(internal),time.time()))
            self.store.db.execute('UPDATE orders SET updated=? WHERE id=?',(time.time(),number))
            return cursor.lastrowid

    def messages(self,number,*,staff=False):
        with self.store.lock:
            return [dict(row) for row in self.store.db.execute('''SELECT * FROM
                (SELECT * FROM project_messages WHERE order_id=? AND (internal=0 OR ?=1)
                 ORDER BY created DESC,id DESC LIMIT 200) ORDER BY created,id''',(number,int(staff)))]

    def delivery(self,number,author,title,url,description=''):
        self._order(number)
        title=_text(title,'Nome della consegna',120)
        url=_text(url,'Collegamento',2000)
        try:
            parsed=urlsplit(url)
            valid=parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password
            valid=valid and not any(c.isspace() or ord(c)<32 for c in url)
        except ValueError:
            valid=False
        if not valid:
            raise ValueError('Inserisci un collegamento HTTPS valido, senza credenziali.')
        if len(description)>2000:
            raise ValueError('La descrizione può contenere al massimo 2000 caratteri.')
        with self.store.lock,self.store.db:
            cursor=self.store.db.execute('''INSERT INTO project_deliveries
                (order_id,author,title,url,description,created) VALUES(?,?,?,?,?,?)''',
                (number,author,title,url,description.strip(),time.time()))
            self.orders._audit(number,author,'consegna',title)
            return cursor.lastrowid

    def deliveries(self,number):
        with self.store.lock:
            return [dict(row) for row in self.store.db.execute(
                'SELECT * FROM project_deliveries WHERE order_id=? ORDER BY created DESC,id DESC',(number,))]

    def review(self,number,delivery,actor,state,feedback=''):
        order=self._order(number)
        if actor!=order['customer']:
            raise ValueError('Solo il cliente del progetto può rispondere alla consegna.')
        if state not in ('approved','changes'):
            raise ValueError('Esito della revisione non valido.')
        if state=='changes':
            feedback=_text(feedback,'Indicazioni sulle modifiche',2000)
        elif len(feedback)>2000:
            raise ValueError('Il commento può contenere al massimo 2000 caratteri.')
        with self.store.lock,self.store.db:
            cursor=self.store.db.execute('''UPDATE project_deliveries SET state=?,reviewer=?,feedback=?,reviewed=?
                WHERE id=? AND order_id=? AND state='pending' ''',
                (state,actor,feedback.strip(),time.time(),delivery,number))
            if cursor.rowcount!=1:
                raise ValueError('Consegna non trovata o già revisionata. Ricarica la pagina.')
            self.orders._audit(number,actor,'revisione_consegna',f'#{delivery}: {state}')

    def activity(self,user_id,*,staff=False,limit=80):
        """Apply ownership and internal-note filtering in SQL, before limiting."""
        with self.store.lock:
            messages=[dict(row) for row in self.store.db.execute('''SELECT m.id,m.order_id,m.author,
                m.author_name,m.staff,m.body,m.internal,m.created,o.title FROM project_messages m
                JOIN orders o ON o.id=m.order_id WHERE (o.customer=? OR ?=1) AND (m.internal=0 OR ?=1)
                ORDER BY m.created DESC,m.id DESC LIMIT ?''',(user_id,int(staff),int(staff),limit))]
            deliveries=[dict(row) for row in self.store.db.execute('''SELECT d.*,o.title AS project_title
                FROM project_deliveries d JOIN orders o ON o.id=d.order_id WHERE o.customer=? OR ?=1
                ORDER BY d.created DESC,d.id DESC LIMIT ?''',(user_id,int(staff),limit))]
        result=[{'kind':'note' if m['internal'] else 'message','order_id':m['order_id'],'title':m['title'],
                 'text':m['body'],'author':m['author'],'author_name':m['author_name'],'created':m['created']}
                for m in messages]
        for delivery in deliveries:
            result.append({'kind':'delivery','order_id':delivery['order_id'],'title':delivery['project_title'],
                'text':delivery['title'],'author':delivery['author'],'author_name':'Team Lumia','created':delivery['created']})
            if delivery['reviewed']:
                result.append({'kind':'review','order_id':delivery['order_id'],'title':delivery['project_title'],
                    'text':('Consegna approvata' if delivery['state']=='approved' else 'Modifiche richieste')+
                           (': '+delivery['feedback'] if delivery['feedback'] else ''),
                    'author':delivery['reviewer'],'author_name':'Cliente','created':delivery['reviewed']})
        result.sort(key=lambda row:row['created'],reverse=True)
        return result[:limit]
