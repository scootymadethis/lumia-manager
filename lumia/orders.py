"""Orders and immutable EUR payment ledger shared by Discord and the dashboard."""
import json
import re
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

STAGES = {
    'bozza': 'Bozza', 'preventivo': 'Preventivo', 'confermato': 'Confermato',
    'in_corso': 'In lavorazione', 'in_revisione': 'In revisione',
    'completato': 'Completato', 'annullato': 'Annullato',
}
MAX_CENTS = 100_000_000


def to_cents(amount: str) -> int:
    if not isinstance(amount, str) or not re.fullmatch(r'\d{1,7}(?:[.,]\d{1,2})?', amount):
        raise ValueError('Importo non valido: usa ad esempio 129,90 (massimo due decimali).')
    whole, _, decimals = amount.replace(',', '.').partition('.')
    value = int(whole) * 100 + int(decimals.ljust(2, '0') or '0')
    if value > MAX_CENTS:
        raise ValueError('Importo massimo: 1.000.000,00 EUR.')
    return value


def _money(value, positive=False):
    if type(value) is not int or value < (1 if positive else 0) or value > MAX_CENTS:
        raise ValueError('Importo in centesimi non valido.')


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f'{name}: inserisci da 1 a {maximum} caratteri.')
    return value.strip()


def _eur(cents):
    return f'{cents / 100:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.') + ' EUR'


class Orders:
    def __init__(self, store):
        self.store = store
        with store.lock, store.db:
            store.db.executescript('''
                CREATE TABLE IF NOT EXISTS orders (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, customer INTEGER NOT NULL,
                  title TEXT NOT NULL, total_cents INTEGER NOT NULL CHECK(total_cents>=0),
                  ticket_id INTEGER, details TEXT NOT NULL DEFAULT '',
                  stage TEXT NOT NULL DEFAULT 'bozza', created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS order_payments (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
                  amount_cents INTEGER NOT NULL CHECK(amount_cents>0), reference TEXT NOT NULL,
                  actor INTEGER NOT NULL, provider TEXT NOT NULL, event_id TEXT UNIQUE,
                  created REAL NOT NULL, UNIQUE(provider,reference));
                CREATE TABLE IF NOT EXISTS order_audit (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
                  actor INTEGER NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS order_payment_reversals (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id INTEGER NOT NULL UNIQUE,
                  order_id INTEGER NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
                  reason TEXT NOT NULL, actor INTEGER NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS order_milestones (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
                  title TEXT NOT NULL, due TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS order_checkouts (
                  session_id TEXT PRIMARY KEY, order_id INTEGER NOT NULL,
                  amount_cents INTEGER NOT NULL, url TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS stripe_events (
                  id TEXT PRIMARY KEY, status TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS order_installments (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
                  position INTEGER NOT NULL, title TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
                  due TEXT, milestone_id INTEGER, released INTEGER NOT NULL DEFAULT 0,
                  created REAL NOT NULL, UNIQUE(order_id,position));
                CREATE TABLE IF NOT EXISTS order_payment_allocations (
                  payment_id INTEGER NOT NULL, installment_id INTEGER NOT NULL,
                  amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
                  PRIMARY KEY(payment_id,installment_id));
                CREATE TRIGGER IF NOT EXISTS allocation_no_update BEFORE UPDATE ON order_payment_allocations
                  BEGIN SELECT RAISE(ABORT, 'Le allocazioni sono immutabili'); END;
                CREATE TRIGGER IF NOT EXISTS allocation_no_delete BEFORE DELETE ON order_payment_allocations
                  BEGIN SELECT RAISE(ABORT, 'Le allocazioni sono immutabili'); END;
                CREATE TRIGGER IF NOT EXISTS payment_no_update BEFORE UPDATE ON order_payments
                  BEGIN SELECT RAISE(ABORT, 'Il registro pagamenti è immutabile'); END;
                CREATE TRIGGER IF NOT EXISTS payment_no_delete BEFORE DELETE ON order_payments
                  BEGIN SELECT RAISE(ABORT, 'Il registro pagamenti è immutabile'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON order_audit
                  BEGIN SELECT RAISE(ABORT, 'Il registro audit è immutabile'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON order_audit
                  BEGIN SELECT RAISE(ABORT, 'Il registro audit è immutabile'); END;
                CREATE TRIGGER IF NOT EXISTS reversal_no_update BEFORE UPDATE ON order_payment_reversals
                  BEGIN SELECT RAISE(ABORT, 'Il registro storni è immutabile'); END;
                CREATE TRIGGER IF NOT EXISTS reversal_no_delete BEFORE DELETE ON order_payment_reversals
                  BEGIN SELECT RAISE(ABORT, 'Il registro storni è immutabile'); END;
            ''')
            columns={row['name'] for row in store.db.execute('PRAGMA table_info(order_checkouts)')}
            for name,kind in (('installment_id','INTEGER'),('expires_at','REAL'),
                              ('status',"TEXT NOT NULL DEFAULT 'open'"),('attempt_key','TEXT'),
                              ('provider',"TEXT NOT NULL DEFAULT 'stripe'")):
                if name not in columns:
                    store.db.execute(f'ALTER TABLE order_checkouts ADD COLUMN {name} {kind}')

    def _audit(self, number, actor, action, detail):
        self.store.db.execute('UPDATE orders SET updated=? WHERE id=?', (time.time(),number))
        self.store.db.execute('INSERT INTO order_audit(order_id,actor,action,detail,created) VALUES(?,?,?,?,?)',
                              (number, int(actor), action, detail, time.time()))

    def create(self, customer: int, title: str, total_cents: int, ticket_id=None, details='', actor=0):
        if type(customer) is not int or customer <= 0:
            raise ValueError('ID Discord cliente non valido.')
        _money(total_cents)
        title = _text(title, 'Titolo', 200)
        if not isinstance(details, str) or len(details) > 8000:
            raise ValueError('Descrizione: massimo 8000 caratteri.')
        if ticket_id is not None and (type(ticket_id) is not int or ticket_id <= 0):
            raise ValueError('Ticket non valido.')
        if ticket_id is not None:
            ticket = self.store.ticket(ticket_id)
            if not ticket or ticket['owner'] != customer:
                raise ValueError('Il ticket deve esistere e appartenere al cliente dell’ordine.')
        now = time.time()
        with self.store.lock, self.store.db:
            cur = self.store.db.execute('INSERT INTO orders(customer,title,total_cents,ticket_id,details,created,updated) VALUES(?,?,?,?,?,?,?)',
                                        (customer, title, total_cents, ticket_id, details.strip(), now, now))
            number = cur.lastrowid
            self._audit(number, actor, 'creato', f'Cliente {customer}; totale {_eur(total_cents)}')
            return self.get(number)

    def get(self, number):
        with self.store.lock:
            row = self.store.db.execute('SELECT * FROM orders WHERE id=?', (number,)).fetchone()
            return dict(row) if row else None

    def list_for(self, actor_id, staff=False):
        with self.store.lock:
            if staff:
                rows = self.store.db.execute('SELECT * FROM orders ORDER BY updated DESC,id DESC').fetchall()
            else:
                rows = self.store.db.execute('SELECT * FROM orders WHERE customer=? ORDER BY updated DESC,id DESC', (actor_id,)).fetchall()
            return [dict(r) for r in rows]

    def update(self, number, stage, actor):
        if stage not in STAGES:
            raise ValueError('Stato ordine non valido.')
        with self.store.lock, self.store.db:
            if not self.get(number):
                raise ValueError('Ordine non trovato.')
            if self.store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='web_requests'").fetchone():
                request=self.store.db.execute('SELECT quote FROM web_requests WHERE order_id=?',(number,)).fetchone()
                if request and not request['quote'] and stage not in ('bozza','annullato'):
                    raise ValueError('Invia prima il preventivo dal manager, con prezzo e ambito del lavoro.')
                if request and request['quote'] and stage=='bozza':
                    raise ValueError('Il preventivo è già stato inviato. Non puoi riportarlo in bozza e modificarne il prezzo.')
            self.store.db.execute('UPDATE orders SET stage=?,updated=? WHERE id=?', (stage, time.time(), number))
            self._audit(number, actor, 'stato', STAGES[stage])
            return self.get(number)

    def accept(self, number, customer):
        with self.store.lock, self.store.db:
            order = self.get(number)
            if not order or order['customer'] != customer or order['stage'] != 'preventivo':
                raise ValueError('Questo preventivo non può essere accettato da questo account.')
            return self.update(number, 'confermato', customer)

    def summary(self, order):
        if not order:
            raise ValueError('Ordine non trovato.')
        with self.store.lock:
            paid = self.store.db.execute('''SELECT COALESCE(SUM(p.amount_cents - COALESCE(r.amount_cents,0)),0)
                FROM order_payments p LEFT JOIN order_payment_reversals r ON r.payment_id=p.id
                WHERE p.order_id=?''', (order['id'],)).fetchone()[0]
            return {'paid_cents': paid, 'due_cents': max(0, order['total_cents'] - paid)}

    def payments(self, number):
        with self.store.lock:
            return [dict(r) for r in self.store.db.execute('''SELECT p.*, r.created AS reversed_at,
                r.reason AS reversal_reason,r.actor AS reversed_by,r.id AS reversal_id
                FROM order_payments p LEFT JOIN order_payment_reversals r ON r.payment_id=p.id
                WHERE p.order_id=? ORDER BY p.id DESC''', (number,))]

    def reverse_payment(self, payment_id, reason, actor):
        """Append one bookkeeping correction. Never reverses a Stripe payment or moves money."""
        reason = _text(reason, 'Motivazione dello storno', 1000)
        with self.store.lock, self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            payment = self.store.db.execute('SELECT * FROM order_payments WHERE id=?', (payment_id,)).fetchone()
            if not payment:
                raise ValueError('Pagamento non trovato.')
            if payment['provider'] != 'manual':
                raise ValueError('I pagamenti Stripe devono essere riconciliati con il provider: lo storno manuale non è consentito.')
            existing = self.store.db.execute('SELECT id FROM order_payment_reversals WHERE payment_id=?', (payment_id,)).fetchone()
            if existing:
                return False
            self.store.db.execute('INSERT INTO order_payment_reversals(payment_id,order_id,amount_cents,reason,actor,created) VALUES(?,?,?,?,?,?)',
                                  (payment_id, payment['order_id'], payment['amount_cents'], reason, int(actor), time.time()))
            self._audit(payment['order_id'], actor, 'storno manuale', f'Rettifica incasso #{payment_id} ({_eur(payment["amount_cents"])}): {reason}. Nessun rimborso eseguito.')
            return True

    def audit(self, number):
        with self.store.lock:
            return [dict(r) for r in self.store.db.execute('SELECT * FROM order_audit WHERE order_id=? ORDER BY id', (number,))]

    def record_payment(self, order_id, amount_cents, reference, actor, provider='manual', event_id=None):
        _money(amount_cents, positive=True)
        reference = _text(reference, 'Riferimento', 200)
        if provider not in ('manual', 'stripe', 'paypal'):
            raise ValueError('Provider non valido.')
        with self.store.lock, self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            return self._record_payment(order_id, amount_cents, reference, actor, provider, event_id)

    def _record_payment(self, order_id, amount_cents, reference, actor, provider, event_id, installment_id=None):
        order = self.get(order_id)
        if not order:
            raise ValueError('Ordine non trovato.')
        existing = self.store.db.execute('SELECT * FROM order_payments WHERE (provider=? AND reference=?) OR (? IS NOT NULL AND event_id=?)',
                                         (provider, reference, event_id, event_id)).fetchone()
        if existing:
            if existing['order_id'] != order_id or existing['amount_cents'] != amount_cents or existing['provider'] != provider or existing['reference'] != reference:
                raise ValueError('Riferimento pagamento già usato con dati diversi.')
            return False
        if amount_cents > self.summary(order)['due_cents']:
            raise ValueError('Il pagamento supera il residuo. Nessun credito registrato: riconcilia manualmente con il provider.')
        if installment_id is not None:
            target=next((x for x in self.installments(order_id) if x['id']==installment_id),None)
            if not target or amount_cents>target['remaining_cents']:
                raise ValueError('La tranche risulta già coperta o non è coerente: riconcilia il pagamento Stripe.')
        cur=self.store.db.execute('INSERT INTO order_payments(order_id,amount_cents,reference,actor,provider,event_id,created) VALUES(?,?,?,?,?,?,?)',
                              (order_id, amount_cents, reference, int(actor), provider, event_id, time.time()))
        self._allocate_payment(cur.lastrowid,order_id,amount_cents,installment_id)
        label = {'stripe': 'Stripe', 'paypal': 'PayPal', 'manual': 'Incasso manuale'}[provider]
        self._audit(order_id, actor, 'pagamento', f'{label}: {_eur(amount_cents)}; {reference}')
        return True

    def _allocate_payment(self,payment_id,order_id,amount,installment_id=None):
        for item in self.installments(order_id):
            if installment_id is not None and item['id']!=installment_id:
                continue
            part=min(amount,item['remaining_cents'])
            if part:
                self.store.db.execute('INSERT INTO order_payment_allocations VALUES(?,?,?)',
                                      (payment_id,item['id'],part))
                amount-=part
            if not amount:
                break

    def create_installments(self,order_id,rows,actor):
        if not isinstance(rows,list) or not 1<=len(rows)<=24:
            raise ValueError('Definisci da 1 a 24 tranche.')
        clean=[]
        for position,row in enumerate(rows):
            title=_text(row.get('title'),'Nome tranche',120)
            amount=row.get('amount_cents')
            _money(amount,positive=True)
            due=row.get('due') or None
            if due:
                try:
                    if date.fromisoformat(due).isoformat()!=due:
                        raise ValueError()
                except (ValueError,TypeError):
                    raise ValueError('Data della tranche non valida (AAAA-MM-GG).') from None
            milestone=row.get('milestone_id') or None
            if milestone is not None and (type(milestone) is not int or milestone<=0):
                raise ValueError('Milestone della tranche non valida.')
            if due and milestone:
                raise ValueError('Per una tranche scegli una data oppure una milestone.')
            clean.append((position,title,amount,due,milestone,int(position==0 and not due and not milestone)))
        with self.store.lock,self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            order=self.get(order_id)
            if not order or order['stage']=='annullato':
                raise ValueError('Ordine non disponibile.')
            if self.installments(order_id):
                raise ValueError('Questo ordine ha già un piano di pagamento.')
            if self.summary(order)['due_cents']<=0:
                raise ValueError('L’ordine è già saldato.')
            if sum(x[2] for x in clean)!=order['total_cents']:
                raise ValueError('La somma delle tranche deve coincidere con il totale dell’ordine.')
            pending=self.store.get('web_checkout_attempts',order_id,{})
            if self.recent_checkout(order_id) or pending.get('expires_at',0)>time.time():
                raise ValueError('È presente un Checkout aperto o in verifica. Attendi la scadenza prima di creare il piano.')
            milestones={m['id'] for m in self.milestones(order_id)}
            if any(row[4] and row[4] not in milestones for row in clean):
                raise ValueError('Ogni milestone deve appartenere a questo ordine.')
            for row in clean:
                self.store.db.execute('''INSERT INTO order_installments
                    (order_id,position,title,amount_cents,due,milestone_id,released,created) VALUES(?,?,?,?,?,?,?,?)''',
                    (order_id,*row,time.time()))
            for payment in reversed(self.payments(order_id)):
                if not payment.get('reversed_at'):
                    self._allocate_payment(payment['id'],order_id,payment['amount_cents'])
            self._audit(order_id,actor,'piano pagamenti',f'{len(clean)} tranche; totale {_eur(order["total_cents"])}')
        return self.installments(order_id)

    def installments(self,order_id):
        today=datetime.now(ZoneInfo('Europe/Rome')).date().isoformat()
        with self.store.lock:
            rows=self.store.db.execute('''SELECT i.*,m.title AS milestone_title,m.done AS milestone_done,
                COALESCE((SELECT SUM(a.amount_cents) FROM order_payment_allocations a
                  JOIN order_payments p ON p.id=a.payment_id
                  LEFT JOIN order_payment_reversals r ON r.payment_id=p.id
                  WHERE a.installment_id=i.id AND r.id IS NULL),0) AS paid_cents
                FROM order_installments i LEFT JOIN order_milestones m ON m.id=i.milestone_id
                WHERE i.order_id=? ORDER BY i.position,i.id''',(order_id,)).fetchall()
            result=[]
            for row in rows:
                item=dict(row)
                item['remaining_cents']=max(0,item['amount_cents']-item['paid_cents'])
                item['ready']=bool(item['released'] or (item['due'] and item['due']<=today)
                                   or (item['milestone_id'] and item['milestone_done']))
                result.append(item)
            return result

    def payable(self,order_id):
        order=self.get(order_id)
        if not order:
            raise ValueError('Ordine non trovato.')
        plan=self.installments(order_id)
        if not plan:
            return {'amount_cents':self.summary(order)['due_cents'],'installment_id':None,'title':'Saldo ordine'}
        current=next((x for x in plan if x['remaining_cents']),None)
        if current and current['ready']:
            return {'amount_cents':current['remaining_cents'],'installment_id':current['id'],'title':current['title']}
        return {'amount_cents':0,'installment_id':None,'title':'Nessuna tranche da pagare'}

    def release_installment(self,order_id,installment_id,actor):
        with self.store.lock,self.store.db:
            item=next((x for x in self.installments(order_id) if x['id']==installment_id),None)
            order=self.get(order_id)
            if not item or not item['remaining_cents'] or not order or order['stage']=='annullato':
                raise ValueError('Tranche non disponibile.')
            if not item['released']:
                self.store.db.execute('UPDATE order_installments SET released=1 WHERE id=?',(installment_id,))
                self._audit(order_id,actor,'richiesta pagamento',f'{item["title"]}: {_eur(item["remaining_cents"])}')
            return item

    def add_milestone(self, order_id, title, due, actor):
        title = _text(title, 'Milestone', 200)
        try:
            if date.fromisoformat(due).isoformat() != due:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('Data milestone non valida (AAAA-MM-GG).') from None
        with self.store.lock, self.store.db:
            if not self.get(order_id):
                raise ValueError('Ordine non trovato.')
            cur = self.store.db.execute('INSERT INTO order_milestones(order_id,title,due) VALUES(?,?,?)', (order_id, title, due))
            self._audit(order_id, actor, 'milestone', f'Aggiunta: {title}; scadenza {due}')
            return dict(self.store.db.execute('SELECT * FROM order_milestones WHERE id=?', (cur.lastrowid,)).fetchone())

    def milestones(self, order_id):
        with self.store.lock:
            return [dict(r) for r in self.store.db.execute('SELECT * FROM order_milestones WHERE order_id=? ORDER BY due,id', (order_id,))]

    def set_milestone(self, order_id, milestone_id, done, actor):
        with self.store.lock, self.store.db:
            cur = self.store.db.execute('UPDATE order_milestones SET done=? WHERE id=? AND order_id=?', (int(bool(done)), milestone_id, order_id))
            if cur.rowcount != 1:
                raise ValueError('Milestone non trovata.')
            self._audit(order_id, actor, 'milestone', f'#{milestone_id}: {"completata" if done else "da completare"}')

    def save_checkout(self, order_id, session_id, amount_cents, url, installment_id=None, expires_at=None, attempt_key=None, provider='stripe'):
        _money(amount_cents, positive=True)
        with self.store.lock, self.store.db:
            if not self.get(order_id):
                raise ValueError('Ordine non trovato.')
            self.store.db.execute('''INSERT INTO order_checkouts
                (session_id,order_id,amount_cents,url,created,installment_id,expires_at,attempt_key,provider) VALUES(?,?,?,?,?,?,?,?,?)''',
                (session_id,order_id,amount_cents,url,time.time(),installment_id,expires_at or time.time()+3600,attempt_key,provider))

    def recent_checkout(self, order_id):
        with self.store.lock:
            row = self.store.db.execute('''SELECT * FROM order_checkouts WHERE order_id=? AND status='open'
                AND COALESCE(expires_at,created+3600)>? ORDER BY created DESC LIMIT 1''',(order_id,time.time())).fetchone()
            return dict(row) if row else None

    def event(self, event_id, status, detail):
        with self.store.lock, self.store.db:
            self.store.db.execute('INSERT OR IGNORE INTO stripe_events VALUES(?,?,?,?)', (event_id, status, detail[:1000], time.time()))

    def events(self):
        with self.store.lock:
            return [dict(r) for r in self.store.db.execute('SELECT * FROM stripe_events ORDER BY created DESC LIMIT 50')]

    def apply_checkout(self, event_id, session):
        with self.store.lock, self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            seen = self.store.db.execute('SELECT id FROM stripe_events WHERE id=?', (event_id,)).fetchone()
            if seen:
                return False
            checkout = self.store.db.execute('SELECT * FROM order_checkouts WHERE session_id=?', (session.get('id'),)).fetchone()
            if not checkout:
                raise ValueError('Sessione Checkout non riconosciuta.')
            order = self.get(checkout['order_id'])
            metadata = session.get('metadata') or {}
            if (not isinstance(metadata,dict) or session.get('currency') != 'eur' or session.get('payment_status') != 'paid'
                    or type(session.get('amount_total')) is not int
                    or session['amount_total'] != checkout['amount_cents']
                    or metadata.get('order_id') != str(order['id'])
                    or (checkout['installment_id'] is not None and metadata.get('installment_id')!=str(checkout['installment_id']))):
                raise ValueError('Valuta, importo, stato o metadati Checkout non coerenti.')
            applied = self._record_payment(order['id'], checkout['amount_cents'], session['id'], 0, 'stripe', event_id,checkout['installment_id'])
            self.store.db.execute("UPDATE order_checkouts SET status='paid' WHERE session_id=?",(session['id'],))
            self._clear_checkout_attempt(checkout)
            self.store.db.execute('INSERT INTO stripe_events VALUES(?,?,?,?)', (event_id, 'registrato' if applied else 'duplicato', session['id'], time.time()))
            return applied

    def _clear_checkout_attempt(self,checkout):
        attempt=self.store.get('web_checkout_attempts',checkout['order_id'],{})
        if checkout['attempt_key'] and attempt.get('key')==checkout['attempt_key']:
            self.store.db.execute("DELETE FROM records WHERE bucket='web_checkout_attempts' AND key=?",(str(checkout['order_id']),))

    def expire_checkout(self,session_id):
        with self.store.lock,self.store.db:
            row=self.store.db.execute('SELECT * FROM order_checkouts WHERE session_id=?',(session_id,)).fetchone()
            if row and row['status']=='open':
                self.store.db.execute("UPDATE order_checkouts SET status='expired' WHERE session_id=?",(session_id,))
                self._clear_checkout_attempt(row)
