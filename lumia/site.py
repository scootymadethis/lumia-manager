"""Public landing on its own hostname; no manager data or session access."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import HTMLResponse,PlainTextResponse,RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE=Path(__file__).parent

# Public Italian guides under /guide/<slug>; each slug has templates/guides/<slug>.html.
GUIDES={
    'server-fivem-su-misura':{
        'label':'Server FiveM su misura',
        'title':'Server FiveM su misura: script e sistemi',
        'eyebrow':'FiveM',
        'description':'Script, sistemi e integrazioni FiveM su misura per il tuo server roleplay: cosa puoi chiederci, cosa raccontarci e come si arriva al preventivo.',
        'summary':'Cosa puoi chiederci, cosa ci serve sapere del tuo server e come si arriva al preventivo.',
        'order':'/ordina?platform=fivem',
        'cta':'Inizia il tuo progetto FiveM',
    },
    'plugin-minecraft-su-misura':{
        'label':'Plugin Minecraft su misura',
        'title':'Plugin e modalità Minecraft su misura',
        'eyebrow':'Minecraft',
        'description':'Plugin e modalità Minecraft su misura: come descrivere l’idea, quali informazioni tecniche servono e cosa succede dopo la richiesta.',
        'summary':'Come descrivere la tua modalità e quali informazioni tecniche rendono il preventivo più preciso.',
        'order':'/ordina?platform=minecraft',
        'cta':'Inizia il tuo progetto Minecraft',
    },
    'come-funziona-un-progetto-con-lumia':{
        'label':'Come funziona un progetto',
        'title':'Come funziona un progetto su misura',
        'eyebrow':'Il percorso',
        'description':'Richiesta guidata, preventivo, milestone, consegne e pagamenti a rate con PayPal: ecco, passo per passo, come si svolge un progetto con Lumia.',
        'summary':'Richiesta, preventivo, milestone, consegne, pagamenti con PayPal e assistenza su Discord, in ordine.',
        'order':'/ordina',
        'cta':'Inizia il tuo progetto',
    },
}
GUIDE_INDEX={
    'label':'Guide',
    'title':'Guide per il tuo progetto',
    'description':'Le guide di Lumia Development su server FiveM, plugin Minecraft e sul percorso di un progetto su misura, dalla richiesta alla consegna.',
}


def create_site_app(public=None,manager=None,*,preview=False):
    public=(public or os.getenv('LUMIA_SITE_URL','https://lumiadevelopment.it')).rstrip('/')
    manager=(manager or os.getenv('LUMIA_PUBLIC_URL','https://manager.lumiadevelopment.it')).rstrip('/')
    invite=os.getenv('LUMIA_DISCORD_INVITE','https://discord.gg/lumiadevelopment').strip()
    parsed=urlsplit(invite)
    if parsed.scheme!='https' or parsed.hostname not in ('discord.gg','discord.com') or parsed.username or parsed.password:
        raise RuntimeError('LUMIA_DISCORD_INVITE deve essere un invito HTTPS Discord.')
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    app.mount('/static',StaticFiles(directory=HERE/'static'),name='static')
    templates=Jinja2Templates(directory=HERE/'templates')
    templates.env.filters['money']=lambda cents:f'{cents/100:.2f} €'

    @app.middleware('http')
    async def headers(request,call_next):
        if not preview and request.headers.get('host','').lower()!=urlsplit(public).netloc:
            return PlainTextResponse('Host non consentito.',status_code=400)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Cache-Control']='public, max-age=300'
        if not preview:
            response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
        return response

    base={'public_url':public,'manager_url':manager,'discord_url':invite,'guides':GUIDES}

    @app.get('/',response_class=HTMLResponse)
    async def index(request:Request):
        return templates.TemplateResponse(request=request,name='landing.html',context=base)

    @app.get('/guide',response_class=HTMLResponse)
    async def guide_index(request:Request):
        return templates.TemplateResponse(request=request,name='guides/index.html',context={
            **base,'page':GUIDE_INDEX,'path':'/guide','slug':None})

    @app.get('/guide/{slug}',response_class=HTMLResponse)
    async def guide(request:Request,slug:str):
        if slug not in GUIDES:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(request=request,name=f'guides/{slug}.html',context={
            **base,'page':GUIDES[slug],'path':f'/guide/{slug}','slug':slug})

    @app.get('/robots.txt')
    async def robots():
        return PlainTextResponse(f'User-agent: *\nAllow: /\nSitemap: {public}/sitemap.xml\n')

    @app.get('/ordina')
    async def order_start(platform:str=''):
        suffix='?platform='+platform if platform in ('fivem','minecraft','discord','web','other') else ''
        return RedirectResponse(manager+'/start'+suffix,status_code=303)

    @app.get('/sitemap.xml')
    async def sitemap():
        from fastapi.responses import Response
        from html import escape
        paths=['/','/guide',*[f'/guide/{slug}' for slug in GUIDES]]
        urls=''.join(f'<url><loc>{escape(public+path)}</loc></url>' for path in paths)
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+urls+'</urlset>',media_type='application/xml')

    return app


def create_preview_site():
    return create_site_app(preview=True)
