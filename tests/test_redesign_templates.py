"""Static guards for the Bianco redesign: CSP-safe templates and a single asset foundation."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'lumia' / 'templates'
STATIC = ROOT / 'lumia' / 'static'
PAGES = ['landing.html', 'intake.html', 'login.html', 'error.html', 'paypal-return.html', 'dashboard.html']
LEGACY = ['design.css', 'manager.css', 'orders.css', 'app.css', 'landing.css', 'cinematic.css']


def read(path):
    return path.read_text(encoding='utf-8')


class RedesignTemplateTests(unittest.TestCase):
    def templates(self):
        return sorted(TEMPLATES.rglob('*.html'))

    def test_templates_have_no_inline_styles_scripts_or_handlers(self):
        for path in self.templates():
            text = read(path)
            with self.subTest(template=path.relative_to(TEMPLATES).as_posix()):
                self.assertNotRegex(text, r'\sstyle\s*=')
                self.assertNotRegex(text, r'<style[\s>]')
                self.assertNotRegex(text, r'\son[a-z]+\s*=\s*["\']')
                for tag in re.findall(r'<script\b[^>]*>', text):
                    self.assertIn(' src="/static/', tag)

    def test_static_references_exist(self):
        for path in self.templates():
            for ref in re.findall(r'/static/([^"\'\s?)]+)', read(path)):
                if '{{' in ref or '{%' in ref:
                    continue
                with self.subTest(template=path.name, ref=ref):
                    self.assertTrue((STATIC / ref).is_file())

    def test_pages_use_the_new_foundation(self):
        for name in PAGES:
            text = read(TEMPLATES / name)
            with self.subTest(page=name):
                self.assertRegex(text, r'href="/static/base\.css\?v=[\w.-]+"')
                for legacy in LEGACY:
                    self.assertNotIn(f'/static/{legacy}', text)

    def test_theme_script_runs_before_first_paint(self):
        for name in PAGES:
            if name == 'landing.html':
                continue
            head = read(TEMPLATES / name).split('</head>')[0]
            with self.subTest(page=name):
                self.assertRegex(head, r'<script src="/static/theme\.js\?v=[\w.-]+"></script>')

    def test_legacy_stylesheets_are_gone(self):
        for legacy in LEGACY:
            with self.subTest(file=legacy):
                self.assertFalse((STATIC / legacy).exists())

    def test_fonts_are_self_hosted(self):
        self.assertTrue((STATIC / 'fonts' / 'InterVariable.woff2').is_file())
        self.assertRegex(read(STATIC / 'base.css'), r"url\(['\"]?/static/fonts/InterVariable\.woff2")
        for path in [*self.templates(), *STATIC.glob('*.css')]:
            with self.subTest(file=path.name):
                self.assertNotIn('fonts.googleapis', read(path))
                self.assertNotIn('fonts.gstatic', read(path))

    def test_icon_names_used_in_templates_exist(self):
        macros = read(TEMPLATES / 'macros.html')
        defined = set(re.findall(r"name == '([a-z0-9_-]+)'", macros))
        for path in self.templates():
            for name in re.findall(r"icon\('([a-z0-9_-]+)'", read(path)):
                with self.subTest(template=path.name, icon=name):
                    self.assertIn(name, defined)

    def test_macros_use_only_filters_available_on_the_site_app(self):
        used = set(re.findall(r'\|\s*([a-z_]+)', read(TEMPLATES / 'macros.html')))
        allowed = {'money', 'format', 'string', 'upper', 'lower', 'length', 'default', 'e', 'escape',
                   'trim', 'int', 'join', 'replace', 'first', 'last', 'round', 'abs', 'title', 'capitalize'}
        self.assertLessEqual(used, allowed)


if __name__ == '__main__':
    unittest.main()
