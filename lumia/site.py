"""Public landing on its own hostname; no manager data or session access."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse,PlainTextResponse,RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE=Path(__file__).parent


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

    @app.get('/',response_class=HTMLResponse)
    async def index(request:Request):
        return templates.TemplateResponse(request=request,name='landing.html',context={
            'public_url':public,'manager_url':manager,'discord_url':invite})

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
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>'+escape(public)+'/</loc></url></urlset>',media_type='application/xml')

    return app


def create_preview_site():
    return create_site_app(preview=True)
