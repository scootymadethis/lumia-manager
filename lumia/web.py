"""Self-hosted dashboard. Real mode requires Discord OAuth and HTTPS."""
import asyncio
import csv
import io
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

import httpx
from discord import app_commands
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .core import Store, Window
from .common import is_management
from .orders import Orders, STAGES, to_cents
from .notifications import notify_order
from .workspace import Workspace
from .intake import Intake, PLATFORMS, SERVICES, BUDGETS, TIMELINES, LABELS
from .briefing import Briefing
from .paypal import PayPal

HERE = Path(__file__).parent
DISCORD = 'https://discord.com/api/v10'
COOKIE = '__Host-lumia_session'
STATE_COOKIE = '__Host-lumia_oauth'
SESSION_TTL = 8 * 3600


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _public_url(value, demo=False):
    parsed = urlsplit(value)
    if (parsed.scheme not in (('http', 'https') if demo else ('https',)) or not parsed.hostname
            or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise RuntimeError('LUMIA_PUBLIC_URL deve essere l’origine HTTPS pubblica, senza percorso (es. https://manager.example.it).')
    return f'{parsed.scheme}://{parsed.netloc.lower()}'


def _cookie(response, name, value, ttl):
    response.set_cookie(name, value, max_age=ttl, secure=True, httponly=True, samesite='lax', path='/')


def verify_stripe_signature(raw, signature, secret, now=None):
    """Verify Stripe v1 against the untouched body; reject replay outside five minutes."""
    if not secret or not signature:
        return False
    fields = {}
    for part in signature.split(','):
        key, _, value = part.strip().partition('=')
        fields.setdefault(key, []).append(value)
    try:
        if len(fields.get('t', [])) != 1:
            return False
        stamp = int(fields['t'][0])
        if abs((time.time() if now is None else now) - stamp) > 300:
            return False
        expected = hmac.new(secret.encode(), str(stamp).encode() + b'.' + raw, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(expected, candidate) for candidate in fields.get('v1', []))
    except (ValueError, TypeError):
        return False


def create_app(bot, *, http_transport=None):
    client_id = os.getenv('DISCORD_CLIENT_ID', '').strip()
    client_secret = os.getenv('DISCORD_CLIENT_SECRET', '').strip()
    if not client_id or not client_secret or not os.getenv('LUMIA_PUBLIC_URL'):
        raise RuntimeError('Dashboard disabilitata: configura DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET e LUMIA_PUBLIC_URL HTTPS.')
    public = _public_url(os.environ['LUMIA_PUBLIC_URL'])
    app=_build_app(bot, public, client_id, client_secret, http_transport=http_transport)
    site=os.getenv('LUMIA_SITE_URL','').strip()
    if site:
        from .site import create_site_app
        from starlette.routing import Host
        site=_public_url(site)
        if urlsplit(site).netloc==urlsplit(public).netloc:
            raise RuntimeError('Landing e manager richiedono hostname distinti.')
        app.router.routes.insert(0,Host(urlsplit(site).netloc,app=create_site_app(site,public)))
        app.state.site_host=urlsplit(site).netloc
    return app


def create_demo_app():
    """Fictional, in-memory and read-only. Never reads the production bot or database."""
    store = Store(':memory:')
    orders = Orders(store)
    examples = [
        (101, 'FiveM · Esperienza roleplay', 125000, 'in_corso', 'Framework personalizzato, interfaccia inventario e onboarding giocatori.', 75000, '2026-11-04'),
        (102, 'Minecraft · Network survival', 68000, 'in_revisione', 'Lobby, economia e plugin dedicati per una community in crescita.', 34000, '2026-10-28'),
        (103, 'Web · Portale community', 42000, 'preventivo', 'Un punto di incontro per news, candidature e risorse della community.', 0, '2026-11-10'),
        (104, 'Discord · Automazioni server', 24000, 'completato', 'Ticket, moderazione e flussi di benvenuto integrati.', 24000, '2026-10-14'),
    ]
    names = {101: 'Alessandro R.', 102: 'Sofia M.', 103: 'Marco C.', 104: 'Giulia F.'}
    for customer, title, total, stage, details, paid, due in examples:
        order = orders.create(customer, title, total, details=details, actor=900)
        orders.update(order['id'], stage, 900)
        if paid:
            orders.record_payment(order['id'], paid, f'DEMO-{order["id"]}', 900)
        orders.add_milestone(order['id'], 'Consegna del progetto', due, 900)
        if stage=='in_corso':
            milestone=orders.milestones(order['id'])[0]
            orders.create_installments(order['id'],[
                {'title':'Avvio progetto','amount_cents':50000},
                {'title':'Prima versione','amount_cents':25000},
                {'title':'Consegna','amount_cents':50000,'milestone_id':milestone['id']}],900)
            orders.release_installment(order['id'],orders.installments(order['id'])[-1]['id'],900)
        if stage == 'completato':
            milestone = orders.milestones(order['id'])[0]
            orders.set_milestone(order['id'], milestone['id'], True, 900)
    bot = SimpleNamespace(store=store, orders=orders, cfg={'guild_id': 0, 'owner_ids': [], 'roles': {}}, demo_names=names)
    public = _public_url(os.getenv('LUMIA_DEMO_URL', 'http://127.0.0.1:8765'), demo=True)
    return _build_app(bot, public, '', '', demo=True)


def _build_app(bot, public, client_id, client_secret, *, demo=False, http_transport=None):
    orders = bot.orders if hasattr(bot, 'orders') else Orders(bot.store)
    store = orders.store
    workspace=Workspace(orders)
    intake=Intake(orders)
    briefing=Briefing()
    if demo and not workspace.messages(1):
        workspace.message(1,900,'Team Lumia','La prima versione è pronta. Qui trovi aggiornamenti e consegne.',staff=True)
        workspace.message(1,101,'Alessandro','Perfetto, controllo la prima versione e vi lascio un riscontro.')
        workspace.message(1,900,'Team Lumia','Nota di lavoro riservata al team.',staff=True,internal=True)
        workspace.delivery(1,900,'Prima versione','https://discord.gg/lumiadevelopment','Apri il ticket per concordare la prova della versione.')
    stripe_secret = '' if demo else os.getenv('STRIPE_WEBHOOK_SECRET', '').strip()
    paypal = PayPal(orders, public, http_transport)
    limits = Window()
    checkout_locks = {}
    support_locks = {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        if demo:
            store.close()

    app = FastAPI(title='Lumia Manager', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.orders = orders
    app.state.demo = demo
    app.state.workspace=workspace
    app.state.intake=intake
    app.state.briefing=briefing
    app.state.paypal=paypal
    app.mount('/static', StaticFiles(directory=HERE / 'static'), name='static')
    templates = Jinja2Templates(directory=HERE / 'templates')
    templates.env.filters['money'] = lambda cents: f'{cents / 100:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.') + ' €'
    zone = ZoneInfo(bot.cfg.get('timezone', 'Europe/Rome'))
    templates.env.filters['date'] = lambda value: datetime.fromtimestamp(value, zone).strftime('%d/%m/%Y, %H:%M')
    templates.env.filters['decimal'] = lambda cents:f'{cents/100:.2f}'.replace('.',',')

    @app.middleware('http')
    async def guard(request, call_next):
        host=request.headers.get('host','').lower()
        if host==getattr(app.state,'site_host',None):
            return await call_next(request)
        if host != urlsplit(public).netloc:
            return HTMLResponse('Host non consentito.', status_code=400)
        if demo and request.method not in ('GET', 'HEAD'):
            return HTMLResponse('DEMO: tutte le modifiche sono disabilitate.', status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.url.path not in ('/webhooks/stripe', '/webhooks/paypal'):
            if request.headers.get('origin') != public:
                return HTMLResponse('Origine della richiesta non consentita.', status_code=403)
        try:
            size = int(request.headers.get('content-length', '0'))
        except ValueError:
            return HTMLResponse('Richiesta non valida.', status_code=400)
        if size > 1_048_576:
            return HTMLResponse('Richiesta troppo grande.', status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        # no-referrer makes browsers send Origin: null on HTML form POSTs.
        # Preserve same-origin submissions so the strict Origin check above works.
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; img-src 'self' data: https://cdn.discordapp.com https://media.discordapp.net; script-src 'self'; connect-src 'self'; form-action 'self' https://www.paypal.com https://www.sandbox.paypal.com; frame-ancestors 'none'; base-uri 'none'"
        response.headers['Cache-Control'] = 'no-store' if not request.url.path.startswith('/static/') else 'public, max-age=3600'
        if not demo:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    async def principal(request, staff=False):
        if demo:
            client=request.query_params.get('view')=='client'
            if staff and client:
                raise HTTPException(403,'Questa funzione è riservata al ruolo Management.')
            return {'id':101 if client else 900,'name':'Alessandro' if client else 'Lumia',
                    'staff':not client,'csrf':'demo-read-only','avatar':None}
        token = request.cookies.get(COOKIE, '')
        session = store.get('web_sessions', _digest(token)) if token else None
        if not session or session.get('expires', 0) <= time.time():
            raise HTTPException(303, headers={'Location': '/login'})
        guild = bot.get_guild(int(bot.cfg['guild_id']))
        if guild is None and not session.get('web_customer'):
            raise HTTPException(503, 'Il bot Discord non è ancora connesso al server. Riprova tra poco.')
        try:
            # Always retrieve from Discord: cache alone would retain removed members/roles.
            member = await guild.fetch_member(session['id']) if guild else None
        except Exception:
            if not session.get('web_customer'):
                raise HTTPException(403, 'Non è possibile verificare la tua appartenenza attuale al server Discord.') from None
            member=None
        is_staff = bool(member and is_management(member, bot.cfg))
        if staff and not is_staff:
            raise HTTPException(403, 'Questa funzione è riservata al ruolo Management.')
        avatar=getattr(getattr(member,'display_avatar',None),'url',None)
        return {**session, 'staff': is_staff,'avatar':str(avatar) if avatar else None,
                'name':getattr(member,'display_name',session['name'])}

    async def form(request, user):
        if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            raise HTTPException(415, 'Formato richiesta non supportato.')
        raw = await request.body()
        maximum=131072 if request.url.path in ('/requests','/requests/questions') else 32768
        if len(raw) > maximum:
            raise HTTPException(413, 'Modulo troppo grande.')
        try:
            values = parse_qs(raw.decode('utf-8'), keep_blank_values=True, strict_parsing=False)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, 'Modulo non valido.') from None
        if any(len(v) != 1 for v in values.values()):
            raise HTTPException(400, 'Campi duplicati non consentiti.')
        result = {k: v[0] for k, v in values.items()}
        if not hmac.compare_digest(result.get('csrf', '').encode('utf-8'), user['csrf'].encode('utf-8')):
            raise HTTPException(403, 'La sessione del modulo è scaduta. Ricarica la pagina e riprova.')
        return result

    def visible_order(number, user):
        order = orders.get(number)
        if not order or (not user['staff'] and order['customer'] != user['id']):
            raise HTTPException(404, 'Ordine non trovato.')
        return order

    def decorate(order):
        result = {**order, **orders.summary(order)}
        result['intake']=intake.get(order['id'])
        result['milestones'] = orders.milestones(order['id'])
        result['installments'] = orders.installments(order['id'])
        result['payable'] = orders.payable(order['id'])
        result['completed_milestones']=sum(bool(m['done']) for m in result['milestones'])
        result['progress']=round(result['completed_milestones']*100/len(result['milestones'])) if result['milestones'] else (100 if order['stage']=='completato' else 0)
        result['pending_deliveries']=sum(d['state']=='pending' for d in workspace.deliveries(order['id']))
        today=datetime.now(zone).date().isoformat()
        result['overdue']=any(not m['done'] and m['due']<today for m in result['milestones'])
        result['needs_payment']=result['payable']['amount_cents']>0 and order['stage'] in ('confermato','in_corso','in_revisione','completato')
        result['focuses']=[key for key,active in (
            ('requests',order['stage']=='bozza'),('quotes',order['stage']=='preventivo'),
            ('payments',result['needs_payment']),('deliveries',result['pending_deliveries'] and order['stage']!='annullato'),
            ('overdue',result['overdue'] and order['stage'] not in ('annullato','completato'))) if active]
        guild = None if demo else bot.get_guild(int(bot.cfg['guild_id']))
        member = guild.get_member(order['customer']) if guild and hasattr(guild, 'get_member') else None
        result['customer_name'] = getattr(bot, 'demo_names', {}).get(order['customer'], getattr(member, 'display_name', f'Cliente {order["customer"]}'))
        profile=store.get('web_customers',order['customer'],{})
        if not member and profile: result['customer_name']=profile['name']
        result['customer_avatar']=str(member.display_avatar.url) if member and getattr(member,'display_avatar',None) else None
        ticket_id=store.get('order_support_tickets',order['id'],{}).get('id') or order.get('ticket_id')
        if ticket_id and hasattr(store, 'ticket') and not demo:
            ticket = store.ticket(ticket_id)
            if ticket and ticket.get('channel') and ticket['owner']==order['customer']:
                result['ticket_url'] = f'https://discord.com/channels/{bot.cfg["guild_id"]}/{ticket["channel"]}'
                result['support_open']=ticket['state'] in ('creating','open','closing')
        return result

    def page(request, user, current, **extra):
        data = [decorate(order) for order in orders.list_for(user['id'], user['staff'])]
        if extra.get('selected_sort')=='deadline':
            data.sort(key=lambda o:min((m['due'] for m in o['milestones'] if not m['done']),default='9999'))
        elif extra.get('selected_sort')=='amount':
            data.sort(key=lambda o:o['due_cents'],reverse=True)
        totals = {'total': sum(o['total_cents'] for o in data if o['stage'] != 'annullato'),
                  'paid': sum(o['paid_cents'] for o in data),
                  'due': sum(o['due_cents'] for o in data if o['stage'] not in ('annullato', 'bozza', 'preventivo')),
                  'active': sum(o['stage'] not in ('completato', 'annullato', 'bozza', 'preventivo') for o in data),
                  'quotes': sum(o['stage'] == 'preventivo' for o in data)}
        customers = {}
        for order in data:
            entry = customers.setdefault(order['customer'], {'name': order['customer_name'], 'avatar':order['customer_avatar'],'id': order['customer'], 'count': 0, 'total': 0, 'paid': 0})
            entry['count'] += 1
            entry['total'] += order['total_cents']
            entry['paid'] += order['paid_cents']
        payments = [{**payment, 'title': order['title'], 'customer_name': order['customer_name']} for order in data for payment in orders.payments(order['id'])]
        payments.sort(key=lambda p: p['created'], reverse=True)
        milestones = [{**m, 'order_id': o['id'], 'project': o['title']} for o in data for m in o['milestones'] if not m['done']]
        milestones.sort(key=lambda m: m['due'])
        today=datetime.now(zone).date().isoformat()
        attention=[]
        agenda=[]
        for order in data:
            link=f'/orders/{order["id"]}'
            if demo and not user['staff']:
                link+='?view=client'
            if order['stage']=='preventivo':
                attention.append({'title':order['title'],'text':'Preventivo da confermare' if not user['staff'] else 'In attesa del cliente','kind':'quote','url':link})
            if order['pending_deliveries'] and order['stage']!='annullato':
                attention.append({'title':order['title'],'text':'Consegna da verificare' if not user['staff'] else 'Consegna in attesa di risposta','kind':'delivery','url':link+'#deliveries'})
            if order['payable']['amount_cents']>=50 and order['stage'] in ('confermato','in_corso','in_revisione','completato'):
                attention.append({'title':order['title'],'text':f'{order["payable"]["title"]} · '+templates.env.filters['money'](order['payable']['amount_cents']),'kind':'payment','url':link})
            if user['staff'] and order['stage']=='bozza':
                attention.append({'title':order['title'],'text':'Richiesta da valutare' if order['intake'] else 'Bozza da completare','kind':'draft','url':link})
            if order['stage']!='annullato':
                for milestone in order['milestones']:
                    if not milestone['done']:
                        agenda.append({'date':milestone['due'],'title':milestone['title'],'project':order['title'],'kind':'Milestone','url':link+'#milestones','overdue':milestone['due']<today})
                for part in order['installments']:
                    if part['due'] and part['remaining_cents']:
                        agenda.append({'date':part['due'],'title':part['title'],'project':order['title'],'kind':'Tranche','url':link+'#payment-plan','overdue':part['due']<today})
        agenda.sort(key=lambda item:(item['date'],item['title']))
        activity=workspace.activity(user['id'],staff=user['staff'])
        read=store.get('workspace_read',user['id'],{}).get('at',0)
        unread=sum(item['author']!=user['id'] and item['created']>read for item in activity)
        role='admin' if user['staff'] else 'client'
        customer_options={entry['id']:entry['name'] for entry in customers.values()}
        if user['staff'] and current=='new' and not demo:
            guild=bot.get_guild(int(bot.cfg['guild_id']))
            for member in list(getattr(guild,'members',[]))[:1000]:
                if getattr(member,'id',0) and not getattr(member,'bot',False):
                    customer_options[member.id]=getattr(member,'display_name',str(member.id))
        return templates.TemplateResponse(request=request, name='dashboard.html', context={
            'user': user, 'page': current, 'orders': data, 'totals': totals, 'stages': STAGES,
            'customers': list(customers.values()), 'payments': payments, 'milestones': milestones,
            'demo': demo, 'paypal': demo or paypal.ready, 'paypal_environment':paypal.environment, 'public_url': public,
            'site_url':os.getenv('LUMIA_SITE_URL','https://lumiadevelopment.it').rstrip('/'),
            'discord_url':os.getenv('LUMIA_DISCORD_INVITE','https://discord.gg/lumiadevelopment'),
            'brief_labels':LABELS,'platforms':PLATFORMS,'services':SERVICES,'budgets':BUDGETS,'timelines':TIMELINES,
            'attention':attention,'agenda':agenda,'today':today,'activity':activity,'unread':unread,
            'read_at':read,'tour':store.get('workspace_tour',f'{user["id"]}:{role}',{}),
            'customer_options':sorted(customer_options.items(),key=lambda item:item[1].casefold()),
            'queues':{key:sum(key in o['focuses'] for o in data) for key in ('requests','quotes','payments','deliveries','overdue')},
            'snapshot':workspace_version(user),
            'tutorial_order':data[0] if data else None,
            'paypal_checkouts':paypal.pending() if user['staff'] else [],
            'events': payment_events() if user['staff'] else [], **extra})

    def payment_events():
        with store.lock:
            rows = [dict(row, provider='PayPal') for row in store.db.execute('SELECT * FROM paypal_events')]
        rows += [dict(row, provider='Stripe (storico)') for row in orders.events()]
        return sorted(rows, key=lambda row: row['created'], reverse=True)[:100]

    def workspace_version(user):
        visible=orders.list_for(user['id'], user['staff'])
        state=[(o,orders.audit(o['id']),workspace.messages(o['id'],staff=user['staff']),
                workspace.deliveries(o['id'])) for o in visible]
        if user['staff']:
            state.append(payment_events())
        return _digest(json.dumps(state,sort_keys=True,default=str))

    @app.get('/workspace/version')
    async def workspace_updates(request:Request):
        user=await principal(request)
        return {'version':workspace_version(user)}

    async def audit_log(text):
        if not demo and hasattr(bot, 'log'):
            try:
                text=re.sub(r'(?i)\b(cliente|da|per) (\d{5,})\b',lambda m:f'{m[1]} <@{m[2]}>',text)
                match=re.search(r'(?i)(?:ordine|preventivo) #?(\d+)',text)
                await bot.log('staff_orders',text,order_id=int(match[1]) if match else None)
            except Exception:
                # Immutable local audit already committed; Discord outage cannot undo it.
                pass

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        if error.status_code == 303:
            return RedirectResponse(error.headers['Location'], status_code=303)
        return templates.TemplateResponse(request=request, name='error.html', context={'status': error.status_code, 'detail': error.detail}, status_code=error.status_code)

    @app.exception_handler(ValueError)
    async def bad_input(request, error):
        return templates.TemplateResponse(request=request, name='error.html', context={'status': 400, 'detail': str(error)}, status_code=400)

    @app.get('/login', response_class=HTMLResponse)
    async def login(request: Request):
        return templates.TemplateResponse(request=request, name='login.html', context={'demo': demo,
            'site_url':os.getenv('LUMIA_SITE_URL','https://lumiadevelopment.it').rstrip('/')})

    @app.get('/auth/discord')
    async def authorize(request: Request):
        if demo:
            return RedirectResponse('/', status_code=303)
        if limits.hit(('oauth', request.client.host), 600) > 20:
            raise HTTPException(429, 'Troppi tentativi di accesso. Riprova tra qualche minuto.')
        state = secrets.token_urlsafe(32)
        web_customer=request.query_params.get('customer')=='1'
        return_start=request.query_params.get('return')=='start'
        store.put('web_oauth', _digest(state), {'created': time.time(),'web_customer':web_customer,'return_start':return_start})
        response = RedirectResponse('https://discord.com/oauth2/authorize?' + urlencode({
            'client_id': client_id, 'redirect_uri': public + '/auth/callback',
            'response_type': 'code', 'scope': 'identify' if web_customer else 'identify guilds.members.read', 'state': state}), status_code=303)
        _cookie(response, STATE_COOKIE, state, 600)
        return response

    @app.get('/auth/callback')
    async def callback(request: Request, state: str = '', code: str = ''):
        if demo:
            return RedirectResponse('/', status_code=303)
        cookie = request.cookies.get(STATE_COOKIE, '')
        with store.lock:
            pending = store.get('web_oauth', _digest(state)) if state else None
            if not cookie or not state or not hmac.compare_digest(cookie.encode('utf-8'), state.encode('utf-8')) or not pending or time.time() - pending['created'] > 600:
                raise HTTPException(400, 'Accesso Discord scaduto o non valido. Avvia nuovamente l’accesso.')
            store.delete('web_oauth', _digest(state))
        if not code or len(code) > 512:
            raise HTTPException(400, 'Autorizzazione Discord non completata.')
        try:
            async with httpx.AsyncClient(transport=http_transport, timeout=15) as http:
                token = await http.post(DISCORD + '/oauth2/token', data={'client_id': client_id,
                    'client_secret': client_secret, 'grant_type': 'authorization_code', 'code': code,
                    'redirect_uri': public + '/auth/callback'})
                token.raise_for_status()
                access = token.json()['access_token']
                headers = {'Authorization': 'Bearer ' + access}
                profile = await http.get(DISCORD + '/users/@me', headers=headers)
                profile.raise_for_status()
                identity = profile.json()
                if not str(identity['id']).isdigit() or not 0<int(identity['id'])<2**63: raise ValueError('Invalid identity')
                if not pending.get('web_customer'):
                    member = await http.get(DISCORD + f'/users/@me/guilds/{bot.cfg["guild_id"]}/member', headers=headers)
                    member.raise_for_status()
                    if not member.json().get('user') or member.json()['user']['id'] != identity['id']:
                        raise ValueError('Member identity mismatch')
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise HTTPException(403, 'Discord non ha confermato l’accesso al server. Verifica il tuo account e riprova.') from None
        # Discard the OAuth token. Session holds only identity, expiry and CSRF nonce.
        session_token = secrets.token_urlsafe(48)
        old = request.cookies.get(COOKIE)
        if old:
            store.delete('web_sessions', _digest(old))
        store.put('web_sessions', _digest(session_token), {'id': int(identity['id']),
            'name': identity.get('global_name') or identity.get('username', 'Membro'),
            'csrf': secrets.token_urlsafe(32), 'expires': time.time() + SESSION_TTL,'web_customer':bool(pending.get('web_customer'))})
        store.put('web_customers',int(identity['id']),{'name':identity.get('global_name') or identity.get('username','Cliente')})
        response = RedirectResponse('/start?connected=1' if pending.get('return_start') else '/', status_code=303)
        _cookie(response, COOKIE, session_token, SESSION_TTL)
        response.delete_cookie(STATE_COOKIE, secure=True, httponly=True, samesite='lax', path='/')
        return response

    @app.post('/logout')
    async def logout(request: Request):
        user = await principal(request)
        await form(request, user)
        store.delete('web_sessions', _digest(request.cookies.get(COOKIE, '')))
        response = RedirectResponse('/login', status_code=303)
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='lax', path='/')
        return response

    @app.get('/')
    async def overview(request: Request):
        return page(request, await principal(request), 'overview')

    @app.get('/start',response_class=HTMLResponse)
    async def start_project(request:Request):
        user=None
        if demo or request.cookies.get(COOKIE):
            try: user=await principal(request)
            except HTTPException as error:
                if error.status_code!=303: raise
        return templates.TemplateResponse(request=request,name='intake.html',context={
            'user':user,'demo':demo,'ai_enabled':briefing.enabled and not demo,
            'site_url':os.getenv('LUMIA_SITE_URL','https://lumiadevelopment.it').rstrip('/'),
            'platforms':PLATFORMS,'services':SERVICES,'budgets':BUDGETS,'timelines':TIMELINES})

    @app.post('/requests/questions')
    async def intake_questions(request:Request):
        user=await principal(request)
        values=await form(request,user)
        if limits.hit(('briefing',user['id']),3600)>6:
            raise HTTPException(429,'Assistente già utilizzato più volte. Continua con le domande guidate.')
        try: raw=json.loads(values.get('brief','{}'))
        except (ValueError,TypeError): raise ValueError('Brief non valido.') from None
        if not isinstance(raw,dict): raise ValueError('Brief non valido.')
        return JSONResponse(await briefing.questions(raw,use_ai=True))

    @app.post('/requests')
    async def submit_request(request:Request):
        user=await principal(request)
        values=await form(request,user)
        try: raw=json.loads(values.get('brief','{}'))
        except (ValueError,TypeError): raise ValueError('Brief non valido.') from None
        try:
            order,created=intake.submit(user['id'],values.get('submission',''),raw)
        except ValueError as error:
            return JSONResponse({'detail':str(error)},status_code=400)
        if created: await audit_log(f'Ordine #{order["id"]}: richiesta dal sito inviata dal cliente {user["id"]}.')
        return JSONResponse({'url':f'/orders/{order["id"]}?submitted=1','id':order['id']},status_code=201 if created else 200)

    @app.post('/orders/{number:int}/quote')
    async def send_quote(request:Request,number:int):
        user=await principal(request,staff=True)
        values=await form(request,user)
        visible_order(number,user)
        intake.quote(number,to_cents(values.get('total','')),values.get('scope',''),user['id'])
        await audit_log(f'Preventivo #{number}: proposta inviata da {user["id"]}.')
        return RedirectResponse(f'/orders/{number}',status_code=303)

    @app.get('/orders')
    async def listing(request: Request, q: str = '', stage: str = '', focus: str = '', sort: str = 'updated'):
        user = await principal(request)
        return page(request, user, 'orders', query=q[:200], selected_stage=stage if stage in STAGES else '',
                    selected_focus=focus if focus in ('requests','quotes','payments','deliveries','overdue') else '',
                    selected_sort=sort if sort in ('updated','deadline','amount') else 'updated')

    @app.get('/orders/new')
    async def new(request: Request):
        return page(request, await principal(request, staff=True), 'new')

    @app.post('/orders')
    async def create(request: Request):
        user = await principal(request, staff=True)
        values = await form(request, user)
        selected=values.get('customer','').strip()
        manual_customer=values.get('customer_id','').strip()
        if selected and manual_customer and selected!=manual_customer:
            raise ValueError('Scegli un solo cliente: usa l’elenco oppure l’ID manuale.')
        try:
            customer = int(manual_customer or selected)
            ticket = int(values['ticket_id']) if values.get('ticket_id') else None
        except ValueError:
            raise ValueError('Inserisci un ID Discord cliente e un numero ticket validi.') from None
        order = orders.create(customer, values.get('title', ''), to_cents(values.get('total', '')),
                              ticket, values.get('details', ''), actor=user['id'])
        await audit_log(f'Ordine #{order["id"]} creato da {user["id"]} per {customer}.')
        return RedirectResponse(f'/orders/{order["id"]}', status_code=303)

    @app.get('/orders/{number:int}')
    async def detail(request: Request, number: int):
        user = await principal(request)
        order = visible_order(number, user)
        return page(request, user, 'detail', order=decorate(order), order_payments=orders.payments(number),
                    order_audit=orders.audit(number), messages=workspace.messages(number,staff=user['staff']),
                    deliveries=workspace.deliveries(number),checkout_success=request.query_params.get('checkout') == 'success',
                    checkout_cancelled=request.query_params.get('checkout') == 'cancelled')

    @app.get('/activity')
    async def activity_page(request:Request):
        return page(request,await principal(request),'activity')

    @app.post('/orders/{number:int}/support')
    async def order_support(request:Request,number:int):
        user=await principal(request)
        values=await form(request,user)
        order=visible_order(number,user)
        if user['id']!=order['customer']:
            raise HTTPException(403,'Il ticket deve essere aperto dal cliente del progetto.')
        reason=values.get('reason','').strip()
        if not 10 <= len(reason) <= 1800:
            raise ValueError('Descrivi la richiesta di assistenza con 10–1800 caratteri.')
        guild=bot.get_guild(int(bot.cfg['guild_id']))
        cog=bot.get_cog('Tickets') if hasattr(bot,'get_cog') else None
        if not guild or not cog:
            raise HTTPException(503,'Assistenza Discord temporaneamente non disponibile. Scrivi nella conversazione del progetto.')
        try:
            member=await guild.fetch_member(user['id'])
        except Exception:
            raise HTTPException(409,'Per usare l’assistenza Discord entra nel server Lumia e completa la verifica. Puoi continuare a scriverci dal sito.') from None
        async with support_locks.setdefault(number,asyncio.Lock()):
            code=f'LM-{number:04d}'
            existing=next((t for t in store.tickets() if t['owner']==user['id'] and t['kind']=='support'
                and t['state'] in ('creating','open','closing') and t.get('fields',{}).get('Ordine')==code),None)
            if existing:
                ticket=existing
            else:
                try:
                    ticket=await cog.create_ticket(guild,member,'support',{
                        'Ordine':code,'Progetto':order['title'],'Richiesta':reason,'Area clienti':f'{public}/orders/{number}'})
                except app_commands.CheckFailure as error:
                    raise HTTPException(409,str(error)) from None
            store.put('order_support_tickets',number,{'id':ticket['id']})
        return RedirectResponse(f'/orders/{number}#support',status_code=303)

    @app.post('/activity/read')
    async def read_activity(request:Request):
        user=await principal(request)
        await form(request,user)
        store.put('workspace_read',user['id'],{'at':time.time()})
        return RedirectResponse('/activity',status_code=303)

    @app.get('/agenda')
    async def agenda_page(request:Request):
        return page(request,await principal(request),'agenda')

    @app.post('/preferences/tour')
    async def save_tour(request:Request):
        user=await principal(request)
        values=await form(request,user)
        if values.get('status') not in ('started','completed','skipped'):
            raise ValueError('Stato del tutorial non valido.')
        try:
            step=int(values.get('step','0'))
            if not 0<=step<=20:raise ValueError()
        except ValueError:
            raise ValueError('Passaggio del tutorial non valido.') from None
        role='admin' if user['staff'] else 'client'
        tour_page=values.get('page','overview')
        if tour_page not in ('overview','orders','detail','payments','activity','agenda','customers','new','settings','tutorial'):
            raise ValueError('Pagina del tutorial non valida.')
        store.put('workspace_tour',f'{user["id"]}:{role}',{
            'status':values['status'],'step':step,'page':tour_page,'version':2 if user['staff'] else 3,'at':time.time()})
        return JSONResponse({'saved':True})

    @app.post('/orders/{number:int}/messages')
    async def project_message(request:Request,number:int):
        user=await principal(request)
        values=await form(request,user)
        order=visible_order(number,user)
        if limits.hit(('message',user['id']),60)>8:
            raise HTTPException(429,'Hai inviato molti messaggi. Attendi un minuto e riprova.')
        internal=values.get('internal')=='1'
        if internal and not user['staff']:
            raise HTTPException(403,'Le note interne sono riservate a Management.')
        workspace.message(number,user['id'],user['name'],values.get('body',''),staff=user['staff'],internal=internal)
        if not internal:
            if user['staff']:
                await notify_order(bot,order,'Hai un nuovo messaggio nel tuo progetto.')
            else:
                await audit_log(f'Ordine #{number}: nuovo messaggio dal cliente {user["id"]}.')
        return RedirectResponse(f'/orders/{number}#conversation',status_code=303)

    @app.post('/orders/{number:int}/deliveries')
    async def project_delivery(request:Request,number:int):
        user=await principal(request,staff=True)
        values=await form(request,user)
        order=visible_order(number,user)
        workspace.delivery(number,user['id'],values.get('title',''),values.get('url',''),values.get('description',''))
        await audit_log(f'Ordine #{number}: nuova consegna pubblicata da {user["id"]}.')
        if not demo:
            await notify_order(bot,order,'Una nuova consegna è pronta da verificare nella dashboard.')
        return RedirectResponse(f'/orders/{number}#deliveries',status_code=303)

    @app.post('/orders/{number:int}/deliveries/{delivery_id:int}/review')
    async def review_delivery(request:Request,number:int,delivery_id:int):
        user=await principal(request)
        values=await form(request,user)
        order=visible_order(number,user)
        if order['customer']!=user['id']:
            raise HTTPException(403,'La revisione spetta al cliente del progetto.')
        workspace.review(number,delivery_id,user['id'],values.get('state'),values.get('feedback',''))
        await audit_log(f'Ordine #{number}: risposta del cliente {user["id"]} alla consegna #{delivery_id}.')
        return RedirectResponse(f'/orders/{number}#deliveries',status_code=303)

    @app.get('/exports/{kind}.csv')
    async def export_csv(request:Request,kind:str):
        user=await principal(request)
        if kind not in ('projects','payments'):
            raise HTTPException(404,'Esportazione non trovata.')
        buffer=io.StringIO(newline='')
        writer=csv.writer(buffer,delimiter=';')
        def safe(value):
            text=str(value)
            return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else text
        def row(values):writer.writerow([safe(value) for value in values])
        if kind=='projects':
            row(['Ordine','Progetto','Cliente Discord','Stato','Totale EUR','Ricevuto EUR','Residuo EUR'])
        else:
            row(['Ordine','Progetto','Movimento','Data','Metodo','Importo EUR','Stornato'])
        for order in orders.list_for(user['id'],user['staff']):
            if kind=='projects':
                balance=orders.summary(order)
                row([order['id'],order['title'],order['customer'],STAGES[order['stage']],
                     templates.env.filters['decimal'](order['total_cents']),templates.env.filters['decimal'](balance['paid_cents']),templates.env.filters['decimal'](balance['due_cents'])])
            else:
                for payment in orders.payments(order['id']):
                    row([order['id'],order['title'],payment['id'],templates.env.filters['date'](payment['created']),
                         payment['provider'],templates.env.filters['decimal'](payment['amount_cents']),'Sì' if payment.get('reversed_at') else 'No'])
        return Response('\ufeff'+buffer.getvalue(),media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename="lumia-{kind}.csv"'})

    @app.post('/orders/{number:int}/stage')
    async def stage(request: Request, number: int):
        user = await principal(request, staff=True)
        values = await form(request, user)
        visible_order(number, user)
        intake.guard_stage(number,values.get('stage'))
        orders.update(number, values.get('stage'), user['id'])
        await audit_log(f'Ordine #{number}: stato {values.get("stage")} impostato da {user["id"]}.')
        if not demo:
            await notify_order(bot,orders.get(number),'Il progetto è stato aggiornato.')
        return RedirectResponse(f'/orders/{number}', status_code=303)

    @app.post('/orders/{number:int}/accept')
    async def accept(request: Request, number: int):
        user = await principal(request)
        await form(request, user)
        visible_order(number, user)
        orders.accept(number, user['id'])
        await audit_log(f'Preventivo #{number} accettato dal cliente {user["id"]}.')
        return RedirectResponse(f'/orders/{number}', status_code=303)

    @app.post('/orders/{number:int}/payments')
    async def manual(request: Request, number: int):
        user = await principal(request, staff=True)
        values = await form(request, user)
        visible_order(number, user)
        recorded = orders.record_payment(number, to_cents(values.get('amount', '')), values.get('reference', ''), user['id'])
        if recorded:
            await audit_log(f'Pagamento manuale ordine #{number}: {values["amount"]} EUR, riferimento {values["reference"]}; registrato da {user["id"]}.')
        return RedirectResponse(f'/orders/{number}', status_code=303)

    @app.post('/orders/{number:int}/milestones')
    async def milestone(request: Request, number: int):
        user = await principal(request, staff=True)
        values = await form(request, user)
        visible_order(number, user)
        orders.add_milestone(number, values.get('title', ''), values.get('due', ''), user['id'])
        return RedirectResponse(f'/orders/{number}', status_code=303)

    @app.post('/orders/{number:int}/installments')
    async def payment_plan(request: Request,number:int):
        user=await principal(request,staff=True)
        values=await form(request,user)
        visible_order(number,user)
        try:
            count=int(values.get('part_count','0'))
            if not 1<=count<=24:
                raise ValueError()
            rows=[{'title':values.get(f'part_{i}_title',''),
                   'amount_cents':to_cents(values.get(f'part_{i}_amount','')),
                   'due':values.get(f'part_{i}_due',''),
                   'milestone_id':int(values[f'part_{i}_milestone']) if values.get(f'part_{i}_milestone') else None}
                  for i in range(count)]
        except (ValueError,TypeError):
            raise ValueError('Controlla importi e milestone del piano di pagamento.') from None
        orders.create_installments(number,rows,user['id'])
        await audit_log(f'Ordine #{number}: piano di {count} tranche creato.')
        if not demo:
            await notify_order(bot,orders.get(number),'Il tuo piano di pagamento è disponibile nell’area clienti.')
        return RedirectResponse(f'/orders/{number}#payment-plan',status_code=303)

    @app.post('/orders/{number:int}/installments/{installment_id:int}/release')
    async def release_installment(request: Request,number:int,installment_id:int):
        user=await principal(request,staff=True)
        await form(request,user)
        visible_order(number,user)
        item=orders.release_installment(number,installment_id,user['id'])
        if not demo:
            await notify_order(bot,orders.get(number),f'È stato richiesto il pagamento della tranche «{item["title"]}».')
        return RedirectResponse(f'/orders/{number}#payment-plan',status_code=303)

    @app.post('/orders/{number:int}/payments/{payment_id:int}/reverse')
    async def reverse_payment(request: Request, number: int, payment_id: int):
        user = await principal(request, staff=True)
        values = await form(request, user)
        visible_order(number, user)
        if not any(p['id'] == payment_id for p in orders.payments(number)):
            raise HTTPException(404, 'Pagamento non trovato per questo ordine.')
        if orders.reverse_payment(payment_id, values.get('reason', ''), user['id']):
            await audit_log(f'Storno contabile incasso #{payment_id}, ordine #{number}, da {user["id"]}: {values["reason"]}. Nessun rimborso eseguito.')
        return RedirectResponse(f'/orders/{number}', status_code=303)

    @app.post('/orders/{number:int}/milestones/{milestone_id:int}')
    async def milestone_status(request: Request, number: int, milestone_id: int):
        user = await principal(request, staff=True)
        values = await form(request, user)
        visible_order(number, user)
        orders.set_milestone(number, milestone_id, values.get('done') == '1', user['id'])
        return RedirectResponse(f'/orders/{number}', status_code=303)

    @app.get('/customers')
    async def customers(request: Request):
        return page(request, await principal(request, staff=True), 'customers')

    @app.get('/payments')
    async def payments(request: Request):
        return page(request, await principal(request), 'payments')

    @app.get('/settings')
    async def settings(request: Request):
        return page(request, await principal(request, staff=True), 'settings')

    @app.get('/tutorial')
    async def customer_tutorial(request:Request):
        return page(request,await principal(request),'tutorial')

    @app.post('/orders/{number:int}/checkout')
    async def checkout(request: Request, number: int):
        user = await principal(request)
        values = await form(request, user)
        order = visible_order(number, user)
        if order['stage'] not in ('confermato', 'in_corso', 'in_revisione', 'completato'):
            raise HTTPException(400, 'Il preventivo deve essere confermato prima del pagamento.')
        if not paypal.ready:
            raise HTTPException(503, 'PayPal non è ancora configurato. Scrivi al team dal progetto.')
        async with checkout_locks.setdefault(number, asyncio.Lock()):
            try:
                url = await paypal.create(number, values.get('installment_id'))
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
            except (httpx.HTTPError, KeyError, StopIteration):
                raise HTTPException(502, 'PayPal non è al momento disponibile. Riprova dal progetto: il tentativo viene conservato.') from None
        return RedirectResponse(url, status_code=303)

    @app.get('/orders/{number:int}/paypal/return')
    async def paypal_return(request: Request, number: int, token: str = ''):
        user = await principal(request)
        visible_order(number, user)
        saved = paypal.checkout(token)
        if saved['order_id'] != number:
            raise HTTPException(404, 'Pagamento non trovato.')
        if saved['status'] == 'paid':
            return RedirectResponse(f'/orders/{number}?checkout=success', status_code=303)
        return templates.TemplateResponse(request=request, name='paypal-return.html', context={
            'user': user, 'number': number, 'token': token})

    @app.post('/orders/{number:int}/paypal/capture')
    async def paypal_capture(request: Request, number: int):
        user = await principal(request)
        values = await form(request, user)
        order = visible_order(number, user)
        token = values.get('token', '')
        saved = paypal.checkout(token)
        if saved['order_id'] != number:
            raise HTTPException(404, 'Pagamento non trovato.')
        async with checkout_locks.setdefault(number, asyncio.Lock()):
            try:
                applied = await paypal.capture(token)
            except (httpx.HTTPError, KeyError):
                raise HTTPException(502, 'La verifica PayPal è in corso. Torna al progetto e riprendi il pagamento per verificarne l’esito.') from None
            except ValueError as error:
                paypal.event('return-error:' + token, 'da_riconciliare', str(error))
                raise HTTPException(409, 'Il pagamento richiede una verifica del team. Non ripetere il pagamento.') from None
        if applied and not demo:
            await notify_order(bot, order, 'Pagamento PayPal ricevuto. Consulta il saldo nel sito.')
        return RedirectResponse(f'/orders/{number}?checkout=success', status_code=303)

    @app.post('/webhooks/paypal')
    async def paypal_webhook(request: Request):
        if not paypal.ready:
            raise HTTPException(503, 'Webhook PayPal non configurato.')
        raw = await request.body()
        if len(raw) > 1_048_576:
            raise HTTPException(413, 'Evento troppo grande.')
        try:
            event = json.loads(raw)
            event_id, kind = event['id'], event['event_type']
            if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200 or not isinstance(kind, str):
                raise ValueError()
            if not isinstance(event.get('resource'), dict):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise HTTPException(400, 'Evento PayPal non valido.') from None
        try:
            if not await paypal.verify(event, request.headers):
                raise HTTPException(400, 'Firma PayPal non valida.')
            resource = event['resource']
            if kind in ('PAYMENT.CAPTURE.COMPLETED', 'CHECKOUT.ORDER.APPROVED'):
                token = (resource.get('supplementary_data', {}).get('related_ids', {}).get('order_id')
                         if kind.startswith('PAYMENT.') else resource.get('id'))
                try:
                    saved = paypal.checkout(token)
                    async with checkout_locks.setdefault(saved['order_id'], asyncio.Lock()):
                        if kind == 'CHECKOUT.ORDER.APPROVED':
                            applied = await paypal.capture(token)
                        else:
                            result = await paypal.api('GET', '/v2/checkout/orders/' + token)
                            applied = paypal.apply(result, event_id)
                        if not applied and paypal.checkout(token)['status'] != 'paid':
                            # Provider state may lag the webhook; let PayPal retry.
                            raise HTTPException(503, 'Pagamento PayPal in verifica.')
                    if applied and not demo:
                        await notify_order(bot, orders.get(saved['order_id']), 'Pagamento PayPal ricevuto. Saldo aggiornato nel sito.')
                except ValueError as error:
                    paypal.event(event_id, 'da_riconciliare', str(error))
                    await audit_log(f'PayPal: evento {event_id} da riconciliare. {error}')
            elif kind in ('PAYMENT.CAPTURE.REFUNDED', 'PAYMENT.CAPTURE.REVERSED', 'CUSTOMER.DISPUTE.CREATED'):
                paypal.event(event_id, 'da_riconciliare', f'{kind}: {resource.get("id", "")}')
                await audit_log(f'PayPal: {kind}, evento {event_id}. Verifica il registro.')
            else:
                paypal.event(event_id, 'ignorato', kind)
        except (httpx.HTTPError, KeyError):
            raise HTTPException(503, 'Verifica PayPal temporaneamente non disponibile.') from None
        return {'received': True}

    @app.post('/payments/paypal/{token}/verify')
    async def paypal_verify_payment(request:Request,token:str):
        user=await principal(request,staff=True)
        await form(request,user)
        saved=paypal.checkout(token)
        async with checkout_locks.setdefault(saved['order_id'],asyncio.Lock()):
            try:
                result=await paypal.api('GET','/v2/checkout/orders/'+token)
                status=result.get('status','UNKNOWN')
                event_id=f'check:{token}:{secrets.token_hex(8)}'
                if status=='COMPLETED':
                    paypal.apply(result,event_id)
                elif status=='VOIDED':
                    orders.expire_checkout(token)
                    paypal.event(event_id,'chiuso',token+' · annullato da PayPal, nessun incasso registrato')
                else:
                    paypal.event(event_id,'in_attesa',token+' · '+status)
            except httpx.HTTPError:
                raise HTTPException(502,'PayPal non è disponibile. Il tentativo viene conservato per la verifica.') from None
        return RedirectResponse('/payments',status_code=303)

    @app.post('/webhooks/stripe')
    async def webhook(request: Request):
        if not stripe_secret:
            raise HTTPException(503, 'Webhook non configurato.')
        raw = await request.body()
        if len(raw) > 1_048_576 or not verify_stripe_signature(raw, request.headers.get('stripe-signature', ''), stripe_secret):
            raise HTTPException(400, 'Firma webhook non valida o scaduta.')
        try:
            event = json.loads(raw)
            event_id, kind = event['id'], event['type']
            if not isinstance(event_id, str) or not event_id.startswith('evt_') or len(event_id) > 200:
                raise ValueError()
            session = event['data']['object']
            if not isinstance(session, dict):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise HTTPException(400, 'Evento webhook non valido.') from None
        if kind in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
            if session.get('payment_status') != 'paid':
                orders.event(event_id, 'in_attesa', str(session.get('id', '')))
            else:
                try:
                    if orders.apply_checkout(event_id, session):
                        await audit_log(f'Stripe: pagamento verificato per ordine {session.get("metadata", {}).get("order_id")}; evento {event_id}.')
                        order=orders.get(int(session['metadata']['order_id']))
                        if not demo:
                            await notify_order(bot,order,'Pagamento ricevuto. Il saldo e il piano sono aggiornati.')
                except ValueError as error:
                    orders.event(event_id, 'da_riconciliare', str(error))
                    await audit_log(f'Stripe: evento {event_id} da riconciliare. {error}')
        elif kind=='checkout.session.expired':
            orders.expire_checkout(session.get('id',''))
        elif kind in ('charge.refunded', 'refund.created', 'refund.updated', 'charge.dispute.created'):
            # Never erase a received payment or automatically issue a refund.
            orders.event(event_id, 'da_riconciliare', f'{kind}: {session.get("id", "")} — verifica il provider e la contabilità.')
            await audit_log(f'Stripe: {kind} ({event_id}). Richiesta riconciliazione manuale in contabilità.')
        else:
            orders.event(event_id, 'ignorato', kind)
        return {'received': True}

    return app
