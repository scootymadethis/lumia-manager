"""The public site's marketing foundations: social preview card and the Italian guides."""
import re
import struct
import unittest
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from lumia.site import GUIDES, create_site_app

ROOT = Path(__file__).resolve().parents[1]
SITE = 'https://site.example'
CARD = f'{SITE}/static/og-card.png'


class Head(HTMLParser):
    """Collects the meta, link and heading facts a crawler reads."""

    def __init__(self):
        super().__init__()
        self.meta, self.links, self.hrefs, self.h1, self.title = {}, {}, [], 0, ''
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            key = attrs.get('property') or attrs.get('name')
            if key:
                self.meta.setdefault(key, attrs.get('content'))
        elif tag == 'link' and attrs.get('rel'):
            self.links.setdefault(attrs['rel'], attrs.get('href'))
        elif tag == 'a' and 'href' in attrs:
            self.hrefs.append(attrs['href'])
        elif tag == 'h1':
            self.h1 += 1
        elif tag == 'title':
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse(text):
    head = Head()
    head.feed(text)
    return head


class SiteGuideTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_site_app(SITE, 'https://manager.example'), base_url=SITE, follow_redirects=False)

    def assert_social_card(self, head):
        self.assertEqual(head.meta['og:image'], CARD)
        self.assertEqual(head.meta['og:image:width'], '1200')
        self.assertEqual(head.meta['og:image:height'], '630')
        self.assertTrue(head.meta.get('og:image:alt'))
        self.assertEqual(head.meta['twitter:card'], 'summary_large_image')
        self.assertEqual(head.meta['twitter:image'], CARD)
        self.assertTrue(head.meta.get('twitter:image:alt'))

    def test_social_card_is_a_light_1200_by_630_png(self):
        data = (ROOT / 'lumia' / 'static' / 'og-card.png').read_bytes()
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        width, height = struct.unpack('>II', data[16:24])
        self.assertEqual((width, height), (1200, 630))
        self.assertLess(len(data), 200 * 1024)

    def test_landing_shares_the_social_card(self):
        head = parse(self.client.get('/').text)
        self.assert_social_card(head)
        self.assertEqual(head.meta['og:url'], f'{SITE}/')
        self.assertEqual(head.links['canonical'], f'{SITE}/')

    def test_landing_footer_links_every_guide(self):
        hrefs = parse(self.client.get('/').text).hrefs
        for slug in GUIDES:
            with self.subTest(slug=slug):
                self.assertIn(f'/guide/{slug}', hrefs)

    def test_guides_are_complete_indexable_pages(self):
        titles, descriptions = set(), set()
        for slug, guide in GUIDES.items():
            with self.subTest(slug=slug):
                response = self.client.get(f'/guide/{slug}')
                self.assertEqual(response.status_code, 200)
                self.assertIn('text/html', response.headers['content-type'])
                self.assertIn("default-src 'self'", response.headers['content-security-policy'])
                text = response.text
                head = parse(text)
                url = f'{SITE}/guide/{slug}'
                self.assertEqual(head.h1, 1)
                self.assertIn(guide['title'], head.title)
                self.assertEqual(head.meta['description'], guide['description'])
                self.assertGreaterEqual(len(guide['description']), 70)
                self.assertLessEqual(len(guide['description']), 160)
                self.assertEqual(head.links['canonical'], url)
                self.assertEqual(head.meta['og:url'], url)
                self.assertEqual(head.meta['og:type'], 'article')
                self.assertTrue(head.meta.get('og:title'))
                self.assertEqual(head.meta['og:description'], guide['description'])
                self.assert_social_card(head)
                self.assertNotIn('noindex', text)
                self.assertRegex(text, r'href="/static/base\.css\?v=[\w.-]+"')
                self.assertRegex(text, r'href="/static/site\.css\?v=[\w.-]+"')
                self.assertTrue(any(h == '/ordina' or h.startswith('/ordina?platform=') for h in head.hrefs))
                for other in GUIDES:
                    if other != slug:
                        self.assertIn(f'/guide/{other}', head.hrefs)
                # same chrome as the landing: glass nav, client area, footer
                self.assertIn('class="site-nav glass-strong"', text)
                self.assertIn('href="https://manager.example/login"', text)
                self.assertIn('class="site-footer"', text)
                titles.add(head.title)
                descriptions.add(guide['description'])
        self.assertEqual(len(titles), len(GUIDES))
        self.assertEqual(len(descriptions), len(GUIDES))

    def test_guide_index_lists_every_guide(self):
        response = self.client.get('/guide')
        self.assertEqual(response.status_code, 200)
        head = parse(response.text)
        self.assertEqual(head.h1, 1)
        self.assertEqual(head.links['canonical'], f'{SITE}/guide')
        self.assert_social_card(head)
        for slug in GUIDES:
            self.assertIn(f'/guide/{slug}', head.hrefs)

    def test_unknown_guide_is_not_found(self):
        self.assertEqual(self.client.get('/guide/non-esiste').status_code, 404)
        self.assertEqual(self.client.get('/guide/..%2Flanding').status_code, 404)

    def test_sitemap_lists_home_index_and_guides(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.headers['content-type'], 'application/xml')
        locs = re.findall(r'<loc>([^<]+)</loc>', response.text)
        self.assertEqual(locs, [f'{SITE}/', f'{SITE}/guide', *[f'{SITE}/guide/{slug}' for slug in GUIDES]])

    def test_guides_never_render_manager_data(self):
        for slug in GUIDES:
            text = self.client.get(f'/guide/{slug}').text
            self.assertNotIn('csrf', text)
            self.assertNotIn('data-snapshot', text)


if __name__ == '__main__':
    unittest.main()
