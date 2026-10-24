"""First-party site analytics: no cookies, no browser storage, no raw IP addresses.

A visitor is a SHA-256 of a daily secret, the client address and the user agent.
The secret rotates every day and the old one is discarded, so a visitor cannot be
recognised across days unless they sign in. Signed-in people are linked by their
Discord ID, which the manager already stores. Typed text is never collected.
"""
import hashlib
import json
import random
import re
import secrets
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

RETENTION_DAYS = 90
SESSION_GAP = 30 * 60
KINDS = ('view', 'click', 'leave', 'step')
GOALS = {'login': 'Accesso', 'request': 'Richiesta inviata', 'quote': 'Preventivo accettato',
         'checkout': 'Pagamento avviato', 'paid': 'Pagamento completato'}
RANGES = {'today': ('Oggi', 0), '7d': ('7 giorni', 7), '30d': ('30 giorni', 30), '90d': ('90 giorni', 90)}
FUNNEL = (('visit', 'Visita il sito'), ('start', 'Apre «Inizia un progetto»'), ('idea', 'Racconta l’idea'),
          ('summary', 'Arriva al riepilogo'), ('request', 'Invia la richiesta'), ('quote', 'Accetta il preventivo'),
          ('paid', 'Paga'))
BOTS = re.compile(r'bot|crawl|spider|slurp|headless|lighthouse|preview|facebookexternalhit|curl|wget|python|httpx', re.I)
VIEW_ID = re.compile(r'^[A-Za-z0-9]{8,32}$')
PAGE_NAMES = {'landing:/': 'Landing', 'manager:/start': 'Inizia un progetto', 'manager:/login': 'Accesso',
              'manager:/': 'Workspace · Home', 'manager:/orders': 'Progetti', 'manager:/orders/:id': 'Progetto',
              'manager:/orders/new': 'Nuovo ordine', 'manager:/payments': 'Pagamenti', 'manager:/agenda': 'Agenda',
              'manager:/activity': 'Attività', 'manager:/tutorial': 'Tutorial clienti', 'manager:/customers': 'Clienti',
              'manager:/settings': 'Impostazioni', 'manager:/analytics': 'Analisi',
              'manager:/orders/:id/paypal/return': 'Ritorno da PayPal'}


def _text(value, limit):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit] if isinstance(value, (str, int, float)) else ''


def _number(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return min(max(number, low), high) if number == number else None


def page_key(site, path):
    path = re.sub(r'/\d+(?=/|$)', '/:id', (path or '/').split('?')[0].split('#')[0]) or '/'
    return f'{site}:{path.rstrip("/") or "/"}'


def page_name(key):
    return PAGE_NAMES.get(key, key.split(':', 1)[1])


def client(user_agent, width):
    ua = user_agent or ''
    device = 'Tablet' if re.search(r'iPad|Tablet', ua) or (re.search(r'Android', ua) and not re.search(r'Mobile', ua)) \
        else 'Mobile' if re.search(r'Mobi|iPhone|Android', ua) else 'Desktop'
    if device == 'Desktop' and width and width < 760:
        device = 'Mobile'
    browser = next((name for pattern, name in ((r'Edg/', 'Edge'), (r'OPR/|Opera', 'Opera'), (r'SamsungBrowser', 'Samsung Internet'),
                    (r'Firefox|FxiOS', 'Firefox'), (r'Chrome|CriOS', 'Chrome'), (r'Safari', 'Safari')) if re.search(pattern, ua)), 'Altro')
    system = next((name for pattern, name in ((r'iPhone|iPad|iOS', 'iOS'), (r'Android', 'Android'), (r'Windows', 'Windows'),
                   (r'Mac OS X|Macintosh', 'macOS'), (r'Linux', 'Linux')) if re.search(pattern, ua)), 'Altro')
    return device, browser, system


class Analytics:
    def __init__(self, store, timezone='Europe/Rome'):
        self.store = store
        self.zone = ZoneInfo(timezone)
        self.staff = set(int(key) for key in store.records('analytics_staff'))
        self.inserts = 0
        with store.lock, store.db:
            store.db.executescript('''
                CREATE TABLE IF NOT EXISTS analytics_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL,
                  visitor TEXT NOT NULL, session TEXT NOT NULL, view TEXT NOT NULL DEFAULT '',
                  user_id INTEGER, staff INTEGER NOT NULL DEFAULT 0, site TEXT NOT NULL,
                  kind TEXT NOT NULL, path TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',
                  target TEXT NOT NULL DEFAULT '', x REAL, y REAL, value REAL,
                  extra TEXT NOT NULL DEFAULT '{}');
                CREATE INDEX IF NOT EXISTS analytics_created ON analytics_events(created);
                CREATE INDEX IF NOT EXISTS analytics_visitor ON analytics_events(visitor, id);
                CREATE INDEX IF NOT EXISTS analytics_session ON analytics_events(session, id);
            ''')

    # ---------- collection ----------
    def mark_staff(self, user_id):
        if user_id and user_id not in self.staff:
            self.staff.add(user_id)
            self.store.put('analytics_staff', user_id, {'at': time.time()})

    def visitor(self, address, user_agent, now=None):
        day = datetime.fromtimestamp(time.time() if now is None else now, self.zone).date().isoformat()
        with self.store.lock:
            salt = self.store.get('analytics', 'salt')
            if not salt or salt.get('day') != day:
                salt = {'day': day, 'value': secrets.token_hex(32)}
                self.store.put('analytics', 'salt', salt)
        return hashlib.sha256(f'{salt["value"]}|{address}|{user_agent}'.encode()).hexdigest()[:20]

    def _session(self, visitor, now):
        row = self.store.db.execute('SELECT session, created FROM analytics_events WHERE visitor=? ORDER BY id DESC LIMIT 1',
                                    (visitor,)).fetchone()
        return row['session'] if row and now - row['created'] < SESSION_GAP else secrets.token_hex(8)

    def _insert(self, rows):
        with self.store.lock, self.store.db:
            self.store.db.executemany('INSERT INTO analytics_events(created,visitor,session,view,user_id,staff,site,kind,path,'
                                      'label,target,x,y,value,extra) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
            self.inserts += len(rows)
            if self.inserts >= 500:
                self.inserts = 0
                self.store.db.execute('DELETE FROM analytics_events WHERE created<?', (time.time() - RETENTION_DAYS * 86400,))

    def record(self, site, address, user_agent, events, user_id=None, now=None):
        """Store a batch from track.js. Invalid items are skipped; nothing is raised to the browser."""
        if BOTS.search(user_agent or '') or not isinstance(events, list):
            return 0
        now = time.time() if now is None else now
        visitor = self.visitor(address, user_agent, now)
        staff = int(bool(user_id and user_id in self.staff))
        rows = []
        with self.store.lock:
            session = self._session(visitor, now)
            for item in events[:40]:
                if not isinstance(item, dict) or item.get('kind') not in KINDS:
                    continue
                path = _text(item.get('path'), 300)
                view = str(item.get('view', ''))
                if not path.startswith('/') or not VIEW_ID.match(view):
                    continue
                extra = {}
                if item['kind'] == 'view':
                    width = _number(item.get('w'), 0, 10000)
                    extra['device'], extra['browser'], extra['os'] = client(user_agent, width)
                    referrer = urlsplit(_text(item.get('ref'), 300))
                    if referrer.hostname and referrer.scheme in ('http', 'https'):
                        extra['ref'] = referrer.hostname.lower().removeprefix('www.')
                    for name in ('utm_source', 'utm_medium', 'utm_campaign'):
                        if _text(item.get(name), 80):
                            extra[name] = _text(item.get(name), 80)
                elif item['kind'] == 'leave' and isinstance(item.get('sections'), list):
                    extra['sections'] = [[_text(part.get('id'), 60), _text(part.get('label'), 80), bool(part.get('seen'))]
                                         for part in item['sections'][:30] if isinstance(part, dict) and _text(part.get('id'), 60)]
                rows.append((now, visitor, session, view, user_id, staff, site, item['kind'], path,
                             _text(item.get('label'), 120), _text(item.get('target'), 300),
                             _number(item.get('x'), 0, 1), _number(item.get('y'), 0, 1),
                             _number(item.get('value'), 0, 86400), json.dumps(extra, separators=(',', ':'))))
        if rows:
            self._insert(rows)
        return len(rows)

    def goal(self, address, user_agent, name, user_id=None, order_id=None, now=None):
        """Server-side milestones (login, request, quote, payment): they cannot be faked by the page."""
        if name not in GOALS:
            raise ValueError('Obiettivo non valido.')
        now = time.time() if now is None else now
        # A provider webhook has no browser behind it: give it the person's own lane.
        visitor = self.visitor(address, user_agent, now) if address else self.visitor(f'user:{user_id}', '', now)
        with self.store.lock:
            session = self._session(visitor, now)
        self._insert([(now, visitor, session, '', user_id, int(bool(user_id and user_id in self.staff)), 'manager', 'goal',
                       f'/orders/{order_id}' if order_id else '/', GOALS[name], name, None, None, None,
                       json.dumps({'order': order_id} if order_id else {}))])

    # ---------- reporting ----------
    def bounds(self, key, now=None):
        now = datetime.fromtimestamp(time.time() if now is None else now, self.zone)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = midnight - timedelta(days=max(RANGES[key][1] - 1, 0))
        length = now.timestamp() - start.timestamp()
        return start.timestamp(), now.timestamp(), start.timestamp() - length

    def _events(self, start, end):
        return [dict(row) for row in self.store.db.execute(
            'SELECT * FROM analytics_events WHERE created>=? AND created<? ORDER BY id LIMIT 300000', (start, end))]

    def _sessions(self, events, include_staff):
        sessions = {}
        staff_visitors = {e['visitor'] for e in events if e['staff']}
        for event in events:
            event['extra'] = json.loads(event['extra'])
            item = sessions.setdefault(event['session'], {'id': event['session'], 'visitor': event['visitor'], 'events': [],
                                                          'user': None, 'staff': event['visitor'] in staff_visitors})
            item['events'].append(event)
            item['user'] = item['user'] or event['user_id']
            item['staff'] = item['staff'] or bool(event['staff']) or (event['user_id'] in self.staff)
        result = []
        for item in sessions.values():
            if item['staff'] and not include_staff:
                continue
            events = item['events']
            views = [e for e in events if e['kind'] == 'view']
            first = views[0] if views else events[0]
            leaves = defaultdict(float)
            for e in events:
                if e['kind'] == 'leave' and e['value'] is not None:
                    leaves[e['view']] = max(leaves[e['view']], e['value'])
            item.update(start=events[0]['created'], end=events[-1]['created'], views=views,
                        clicks=sum(e['kind'] == 'click' for e in events),
                        goals=[e for e in events if e['kind'] == 'goal'],
                        steps=[int(e['value']) for e in events if e['kind'] == 'step' and e['value'] is not None],
                        pages=[page_key(e['site'], e['path']) for e in views],
                        device=first['extra'].get('device', ''), browser=first['extra'].get('browser', ''),
                        source=self.source(first['extra']), active=sum(leaves.values()))
            item['duration'] = max(item['end'] - item['start'], item['active'])
            item['bounce'] = len(views) <= 1 and not item['clicks'] and not item['goals']
            item['stages'] = self._stages(item)
            result.append(item)
        result.sort(key=lambda s: s['start'], reverse=True)
        return result

    @staticmethod
    def source(extra):
        if extra.get('utm_source'):
            return extra['utm_source']
        ref = extra.get('ref', '')
        for pattern, name in (('google.', 'Google'), ('bing.', 'Bing'), ('duckduckgo', 'DuckDuckGo'), ('discord', 'Discord'),
                              ('instagram', 'Instagram'), ('tiktok', 'TikTok'), ('youtube', 'YouTube'), ('facebook', 'Facebook'),
                              ('t.co', 'X'), ('twitter', 'X'), ('reddit', 'Reddit'), ('paypal', 'PayPal')):
            if pattern in ref:
                return name
        return ref or 'Diretto'

    @staticmethod
    def _stages(session):
        reached = {'visit'}
        if 'manager:/start' in session['pages']:
            reached.add('start')
        if any(step >= 1 for step in session['steps']):
            reached.add('idea')
        if any(step >= 5 for step in session['steps']):
            reached.add('summary')
        for goal in session['goals']:
            if goal['target'] == 'request':
                reached.update(('start', 'idea', 'summary', 'request'))
            elif goal['target'] == 'quote':
                reached.add('quote')
            elif goal['target'] == 'paid':
                reached.add('paid')
        return reached

    def report(self, key='7d', include_staff=False, names=None, now=None, limit=20):
        names = names or (lambda user: None)
        start, end, previous = self.bounds(key, now)
        sessions = self._sessions(self._events(start, end), include_staff)
        before = self._sessions(self._events(previous, start), include_staff)

        def person(session):
            return f'u{session["user"]}' if session['user'] else f'v{session["visitor"]}'

        def kpis(items):
            views = sum(len(s['views']) for s in items)
            people = len({person(s) for s in items})
            converted = len({person(s) for s in items if 'request' in s['stages']})
            return {'people': people, 'sessions': len(items), 'views': views,
                    'duration': sum(s['duration'] for s in items) / len(items) if items else 0,
                    'bounce': sum(s['bounce'] for s in items) * 100 / len(items) if items else 0,
                    'requests': converted, 'conversion': converted * 100 / people if people else 0}

        current, past = kpis(sessions), kpis(before)
        delta = {name: (None if not past[name] else (current[name] - past[name]) * 100 / past[name]) for name in current}

        # Daily (or hourly, for today) series of people and sessions.
        buckets = []
        if RANGES[key][1] == 0:
            day = datetime.fromtimestamp(start, self.zone)
            for hour in range(24):
                buckets.append({'label': f'{hour:02d}', 'title': f'{hour:02d}:00', 'start': (day + timedelta(hours=hour)).timestamp()})
        else:
            day = datetime.fromtimestamp(start, self.zone)
            for offset in range(RANGES[key][1]):
                moment = day + timedelta(days=offset)
                buckets.append({'label': moment.strftime('%d'), 'title': moment.strftime('%d/%m'), 'start': moment.timestamp()})
        for bucket in buckets:
            bucket.update(people=set(), sessions=0, requests=0)
        for session in sessions:
            index = max(i for i, b in enumerate(buckets) if b['start'] <= session['start']) if buckets and session['start'] >= buckets[0]['start'] else None
            if index is not None:
                buckets[index]['people'].add(person(session))
                buckets[index]['sessions'] += 1
                buckets[index]['requests'] += 'request' in session['stages']
        peak = max([len(b['people']) for b in buckets] + [1])
        for bucket in buckets:
            bucket['people'] = len(bucket['people'])
            bucket['height'] = round(bucket['people'] * 100 / peak, 1)

        # Funnel, counted on people: a quote accepted days later still closes the loop.
        reached = defaultdict(set)
        for session in sessions:
            for stage in session['stages']:
                reached[stage].add(person(session))
        funnel, top = [], max(len(reached['visit']), 1)
        for index, (stage, label) in enumerate(FUNNEL):
            count = len(reached[stage])
            prior = len(reached[FUNNEL[index - 1][0]]) if index else count
            funnel.append({'key': stage, 'label': label, 'count': count, 'share': count * 100 / top,
                           'drop': (prior - count) * 100 / prior if index and prior else None})

        # Pages: views, people, active time, scroll depth and exits. A page can be left
        # more than once (tab hidden, then closed): keep the furthest reading of each view.
        pages = {}
        exits = Counter(s['pages'][-1] for s in sessions if s['pages'])
        depth, active = {}, {}
        boards = defaultdict(lambda: {'views': set(), 'order': [], 'labels': {}, 'seen': defaultdict(set)})
        for session in sessions:
            view_page = {e['view']: page_key(e['site'], e['path']) for e in session['views']}
            for event in session['events']:
                page = view_page.get(event['view'])
                if not page:
                    continue
                if event['kind'] == 'view':
                    entry = pages.setdefault(page, {'key': page, 'views': 0, 'people': set(), 'depths': [], 'times': []})
                    entry['views'] += 1
                    entry['people'].add(person(session))
                elif event['kind'] == 'leave':
                    if event['y'] is not None:
                        depth[(page, event['view'])] = max(depth.get((page, event['view']), 0), event['y'])
                    if event['value'] is not None:
                        active[(page, event['view'])] = max(active.get((page, event['view']), 0), event['value'])
                    board = boards[page]
                    for ident, label, seen in event['extra'].get('sections', []):
                        board['views'].add(event['view'])
                        if ident not in board['labels']:
                            board['order'].append(ident)
                            board['labels'][ident] = label or ident
                        if seen:
                            board['seen'][ident].add(event['view'])
        for (page, _), value in depth.items():
            pages[page]['depths'].append(value)
        for (page, _), value in active.items():
            pages[page]['times'].append(value)
        page_rows = []
        for entry in pages.values():
            entry['people'] = len(entry['people'])
            entry['name'] = page_name(entry['key'])
            entry['site'] = entry['key'].split(':', 1)[0]
            entry['depth'] = sum(entry['depths']) * 100 / len(entry['depths']) if entry['depths'] else None
            entry['time'] = sum(entry['times']) / len(entry['times']) if entry['times'] else None
            entry['exits'] = exits.get(entry['key'], 0)
            entry['exit_rate'] = entry['exits'] * 100 / entry['views'] if entry['views'] else 0
            del entry['depths'], entry['times']
            page_rows.append(entry)
        page_rows.sort(key=lambda p: p['views'], reverse=True)
        reach = [{'key': page, 'name': page_name(page), 'views': len(board['views']),
                  'sections': [{'label': board['labels'][ident], 'share': len(board['seen'][ident]) * 100 / len(board['views'])}
                               for ident in board['order']]}
                 for page, board in sorted(boards.items(), key=lambda item: len(item[1]['views']), reverse=True)[:2] if board['views']]

        # Clicks, grouped by page and target.
        clicks = Counter()
        click_people = defaultdict(set)
        for session in sessions:
            for event in session['events']:
                if event['kind'] == 'click':
                    group = (page_key(event['site'], event['path']), event['label'] or '—', event['target'])
                    clicks[group] += 1
                    click_people[group].add(person(session))
        click_rows = [{'page': page_name(group[0]), 'label': group[1], 'target': group[2], 'count': count,
                       'people': len(click_people[group])} for group, count in clicks.most_common(12)]

        def share(counter, limit=6):
            total = sum(counter.values()) or 1
            return [{'label': label, 'count': count, 'share': count * 100 / total} for label, count in counter.most_common(limit)]

        sources = Counter(s['source'] for s in sessions)
        source_requests = Counter(s['source'] for s in sessions if 'request' in s['stages'])
        source_rows = [{**row, 'requests': source_requests.get(row['label'], 0)} for row in share(sources, 8)]
        recent = [self.describe(s, names) for s in sessions[:limit]]
        live = self.store.db.execute('SELECT COUNT(DISTINCT visitor) FROM analytics_events WHERE created>=?',
                                     (time.time() - 300 if now is None else now - 300,)).fetchone()[0]
        return {'range': key, 'ranges': RANGES, 'include_staff': include_staff, 'kpis': current, 'delta': delta,
                'series': buckets, 'peak': peak, 'funnel': funnel, 'pages': page_rows[:15], 'reach': reach,
                'clicks': click_rows, 'sources': source_rows, 'devices': share(Counter(s['device'] for s in sessions if s['device'])),
                'browsers': share(Counter(s['browser'] for s in sessions if s['browser']), 5), 'recent': recent,
                'live': live, 'empty': not sessions, 'more_visits': max(len(sessions) - limit, 0), 'limit': limit}

    def describe(self, session, names):
        stage = next((label for key, label in reversed(FUNNEL) if key in session['stages']), FUNNEL[0][1])
        order = next((g['extra'].get('order') for g in session['goals'] if g['extra'].get('order')), None)
        trail = []
        for page in session['pages']:
            if not trail or trail[-1] != page:
                trail.append(page)
        if not trail:
            # Server-only lanes (a provider webhook) have milestones but no pages.
            trail = [g['label'] for g in session['goals']]
        name = names(session['user']) if session['user'] else None
        return {'id': session['id'], 'start': session['start'], 'duration': session['duration'],
                'person': name or (f'Cliente {session["user"]}' if session['user'] else f'Visitatore {session["visitor"][:4].upper()}'),
                'known': bool(session['user']), 'staff': session['staff'], 'views': len(session['views']), 'clicks': session['clicks'],
                'trail': [page_name(p) if ':' in p else p for p in trail[:5]], 'more': max(len(trail) - 5, 0), 'stage': stage,
                'stage_key': next((key for key, _ in reversed(FUNNEL) if key in session['stages']), 'visit'),
                'order': order, 'goals': [g['label'] for g in session['goals']],
                'device': session['device'], 'browser': session['browser'], 'source': session['source']}

    def session(self, ident, names=None):
        if not re.fullmatch(r'[0-9a-f]{16}', ident or ''):
            return None
        events = [dict(row) for row in self.store.db.execute('SELECT * FROM analytics_events WHERE session=? ORDER BY id', (ident,))]
        if not events:
            return None
        item = self._sessions(events, True)[0]
        summary = self.describe(item, names or (lambda user: None))
        timeline = []
        for event in item['events']:
            if event['kind'] == 'leave':
                timeline.append({**event, 'text': 'Lascia la pagina', 'detail': ' · '.join(filter(None, (
                    f'{round(event["value"])} s attivi' if event['value'] is not None else '',
                    f'letto fino al {round(event["y"] * 100)}%' if event['y'] is not None else '')))})
            elif event['kind'] == 'view':
                extra = event['extra']
                timeline.append({**event, 'text': page_name(page_key(event['site'], event['path'])), 'detail': ' · '.join(filter(None, (
                    event['path'], f'da {self.source(extra)}' if extra.get('ref') or extra.get('utm_source') else '')))})
            elif event['kind'] == 'click':
                timeline.append({**event, 'text': event['label'] or 'Clic', 'detail': event['target']})
            elif event['kind'] == 'step':
                timeline.append({**event, 'text': f'Passaggio «{event["label"]}»', 'detail': 'Inizia un progetto'})
            else:
                order = event['extra'].get('order')
                timeline.append({**event, 'text': event['label'], 'detail': f'Ordine LM-{order:04d}' if order else '', 'order': order})
        return {'summary': summary, 'timeline': timeline}


def seed_demo(analytics, now=None):
    """Fictional traffic for the read-only demo. Never used with a real database."""
    rng = random.Random(7)
    now = time.time() if now is None else now
    ua = {'Mobile': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1',
          'Desktop': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36',
          'Tablet': 'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Safari/604.1'}
    sections = [('hero', 'Si parte da te.'), ('servizi', 'Cosa costruiamo'), ('metodo', 'Il percorso'),
                ('principi', 'I nostri principi'), ('domande', 'Domande frequenti'), ('chiusura', 'Iniziamo')]
    steps = ['Dove', 'Idea', 'Dettagli', 'Materiali', 'Tempi', 'Riepilogo']
    refs = ['', '', '', 'https://www.google.com/', 'https://discord.com/', 'https://www.instagram.com/', 'https://www.tiktok.com/']
    customers = list(range(201, 209)) + [101, 102, 103, 104]
    for index in range(420):
        moment = now - rng.random() ** 1.3 * 29 * 86400
        device = rng.choices(['Mobile', 'Desktop', 'Tablet'], [55, 40, 5])[0]
        agent = ua[device] + f' demo/{index}'
        address = f'198.51.100.{index % 250}'
        clock = moment

        def send(kind, path, site='landing', user=None, **fields):
            nonlocal clock
            clock += rng.uniform(2, 40)
            analytics.record(site, address, agent, [{'kind': kind, 'path': path, 'view': fields.pop('view'), **fields}], user, now=clock)

        view = secrets.token_hex(6)
        send('view', '/', view=view, ref=rng.choice(refs), w=390 if device == 'Mobile' else 1440,
             utm_source='newsletter' if rng.random() < .05 else '')
        reach = rng.choices(range(1, 7), [30, 22, 18, 12, 8, 10])[0]
        if rng.random() < .55:
            label, target = rng.choices([('Inizia un progetto', '/ordina'), ('Servizi', '#servizi'), ('Il percorso', '#metodo'),
                                         ('Domande frequenti', '#domande'), ('Entra su Discord', 'https://discord.gg/lumiadevelopment')], [40, 20, 15, 10, 15])[0]
            send('click', '/', view=view, label=label, target=target, x=rng.random(), y=rng.random() * .4)
        send('leave', '/', view=view, value=rng.uniform(6, 160), y=reach / 6,
             sections=[{'id': ident, 'label': label, 'seen': i < reach} for i, (ident, label) in enumerate(sections)])
        if rng.random() > .32:
            continue
        view = secrets.token_hex(6)
        send('view', '/start', site='manager', view=view, ref='https://lumiadevelopment.it/', w=390 if device == 'Mobile' else 1440)
        last = rng.choices(range(6), [30, 20, 14, 8, 6, 22])[0]
        for step in range(1, last + 1):
            send('step', '/start', site='manager', view=view, label=steps[step], value=step)
            send('click', '/start', site='manager', view=view, label='Avanti', target='#brief-next', x=.7, y=.8)
        send('leave', '/start', site='manager', view=view, value=rng.uniform(20, 420), y=rng.uniform(.4, 1))
        if last == 5 and rng.random() < .7:
            user = rng.choice(customers)
            analytics.goal(address, agent, 'login', user, now=clock + 30)
            analytics.goal(address, agent, 'request', user, order_id=rng.randint(1, 4), now=clock + 60)
            clock += 90
            view = secrets.token_hex(6)
            send('view', '/orders/3', site='manager', user=user, view=view)
            send('click', '/orders/3', site='manager', user=user, view=view, label='Accetta il preventivo', target='form', x=.6, y=.3)
            if rng.random() < .5:
                analytics.goal(address, agent, 'quote', user, order_id=3, now=clock + 20)
                if rng.random() < .6:
                    analytics.goal(address, agent, 'checkout', user, order_id=3, now=clock + 40)
                    analytics.goal(address, agent, 'paid', user, order_id=3, now=clock + 120)
