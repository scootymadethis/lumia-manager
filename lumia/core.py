"""Persistent state and policy. No Discord connection required."""
import json
import sqlite3
import threading
import time
from contextlib import closing
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ACTIVE = ('creating', 'open', 'closing')


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS tickets (
              id INTEGER PRIMARY KEY AUTOINCREMENT, owner INTEGER NOT NULL,
              kind TEXT NOT NULL, fields TEXT NOT NULL, created REAL NOT NULL,
              state TEXT NOT NULL, channel INTEGER, staff INTEGER,
              stage TEXT NOT NULL DEFAULT 'nuovo', transcript TEXT,
              closed REAL, extra TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS records (
              bucket TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
              PRIMARY KEY(bucket,key));
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def _ticket(self, row):
        if row is None:
            return None
        item = dict(row)
        item['fields'] = json.loads(item['fields'])
        item['extra'] = json.loads(item['extra'])
        return item

    def ticket(self, number):
        return self._ticket(self.db.execute('SELECT * FROM tickets WHERE id=?', (number,)).fetchone())

    def tickets(self):
        return [self._ticket(r) for r in self.db.execute('SELECT * FROM tickets ORDER BY id')]

    def reserve_ticket(self, owner, kind, fields, now=None):
        now = time.time() if now is None else now
        with self.lock, self.db:
            self.db.execute('BEGIN IMMEDIATE')
            active = self.db.execute("SELECT COUNT(*) FROM tickets WHERE owner=? AND state IN ('creating','open','closing')", (owner,)).fetchone()[0]
            last = self.db.execute('SELECT MAX(created) FROM tickets WHERE owner=?', (owner,)).fetchone()[0]
            if active >= 2:
                raise ValueError('Hai già due ticket aperti. Usa quelli esistenti.')
            if last is not None and now - last < 60:
                raise ValueError('Attendi almeno 60 secondi prima di aprire un altro ticket.')
            cur = self.db.execute('INSERT INTO tickets(owner,kind,fields,created,state) VALUES(?,?,?,?,?)', (owner, kind, json.dumps(fields), now, 'creating'))
            number = cur.lastrowid
        return self.ticket(number)

    def update_ticket(self, number, **changes):
        allowed = {'state','channel','staff','stage','transcript','closed','extra'}
        if not changes or not set(changes) <= allowed:
            raise ValueError('Campi ticket non validi')
        values = [json.dumps(v) if k == 'extra' else v for k,v in changes.items()]
        with self.lock, self.db:
            self.db.execute(f"UPDATE tickets SET {','.join(k+'=?' for k in changes)} WHERE id=?", (*values, number))

    def claim(self, number, staff):
        with self.lock, self.db:
            cur = self.db.execute("UPDATE tickets SET staff=? WHERE id=? AND staff IS NULL AND state='open'", (staff, number))
            return cur.rowcount == 1

    def get(self, bucket, key, default=None):
        row = self.db.execute('SELECT value FROM records WHERE bucket=? AND key=?', (bucket, str(key))).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, bucket, key, value):
        with self.lock, self.db:
            self.db.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(bucket,key) DO UPDATE SET value=excluded.value', (bucket, str(key), json.dumps(value)))

    def records(self, bucket):
        return {r['key']: json.loads(r['value']) for r in self.db.execute('SELECT key,value FROM records WHERE bucket=?', (bucket,))}

    def delete(self, bucket, key):
        with self.lock, self.db:
            self.db.execute('DELETE FROM records WHERE bucket=? AND key=?', (bucket, str(key)))

    def backup(self, target):
        with self.lock, closing(sqlite3.connect(target)) as dest:
            self.db.backup(dest)


class Window:
    def __init__(self):
        self.items = defaultdict(deque)

    def hit(self, key, seconds, now=None):
        now = time.monotonic() if now is None else now
        q = self.items[key]
        while q and q[0] <= now - seconds:
            q.popleft()
        q.append(now)
        # Bound inactive keys during long-running operation.
        if len(self.items) > 5000:
            for old, values in list(self.items.items()):
                if values and values[-1] < now - max(seconds, 600):
                    del self.items[old]
        return len(q)


def attribute_invite(before, after):
    changed = [(code, uses - before.get(code, uses)) for code, uses in after.items() if uses > before.get(code, uses)]
    return changed[0][0] if len(changed) == 1 and changed[0][1] == 1 else None


def parse_when(stamp, tz):
    local = datetime.strptime(stamp, '%Y-%m-%d %H:%M')
    zone = ZoneInfo(tz)
    a, b = local.replace(tzinfo=zone, fold=0), local.replace(tzinfo=zone, fold=1)
    if a.utcoffset() != b.utcoffset() or datetime.fromtimestamp(a.timestamp(), zone).replace(tzinfo=None) != local:
        raise ValueError('Orario inesistente o ambiguo per il cambio ora. Scegli un altro orario.')
    return a.timestamp()


def next_occurrence(stamp, repeat, tz):
    if repeat not in ('daily','weekly'):
        return None
    zone = ZoneInfo(tz)
    wall = datetime.fromtimestamp(stamp, zone).replace(tzinfo=None) + timedelta(days=1 if repeat == 'daily' else 7)
    # Keep the wall-clock time; move a DST gap to the first valid minute.
    for _ in range(181):
        aware = wall.replace(tzinfo=zone, fold=0)
        if datetime.fromtimestamp(aware.timestamp(), zone).replace(tzinfo=None) == wall:
            return aware.timestamp()
        wall += timedelta(minutes=1)
    raise ValueError('Impossibile risolvere il fuso della ricorrenza')
