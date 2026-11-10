"""Vercel entry point: the public demo of Lumia Manager.

Same thing as `python bot.py --preview`: fictional data in memory, read-only,
no Discord connection, never touches data/lumia.sqlite or any credential.

    /        demo dashboard (?view=client for the customer side)
    /start   project intake form
    /sito/   public landing page

Production keeps running through bot.py / Docker; this file is only used by Vercel.
"""
import os

from fastapi.responses import RedirectResponse

# LUMIA_DEMO_URL wins (e.g. a custom domain); otherwise Vercel's production domain,
# and locally the preview port.
_host = os.getenv('VERCEL_PROJECT_PRODUCTION_URL') or os.getenv('VERCEL_URL')
ORIGIN = (os.getenv('LUMIA_DEMO_URL') or (f'https://{_host}' if _host else 'http://127.0.0.1:8080')).rstrip('/')
os.environ['LUMIA_DEMO_URL'] = ORIGIN

from lumia.site import create_site_app  # noqa: E402  (needs the env above)
from lumia.web import create_demo_app  # noqa: E402

app = create_demo_app()
app.mount('/sito', create_site_app(f'{ORIGIN}/sito', ORIGIN, preview=True))


@app.get('/ordina')
async def order_start(platform: str = ''):
    # The landing's "order" buttons point at /ordina, as on the real site.
    suffix = '?platform=' + platform if platform in ('fivem', 'minecraft', 'discord', 'web', 'other') else ''
    return RedirectResponse('/start' + suffix, status_code=303)


class _AnyVercelHost:
    """The dashboard only answers on its own host; on Vercel the same deployment is
    also reachable from preview and per-deployment URLs, so present them all as ORIGIN."""

    def __init__(self, inner):
        self.inner = inner
        self.host = ORIGIN.split('://', 1)[1].encode()

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            headers = [(k, v) for k, v in scope['headers'] if k != b'host']
            scope = dict(scope, headers=headers + [(b'host', self.host)])
        await self.inner(scope, receive, send)


app.add_middleware(_AnyVercelHost)
