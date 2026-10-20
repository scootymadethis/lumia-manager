# Redesign Bianco — piano di implementazione

> **Per gli agenti esecutori:** sottoskill richiesta: superpowers:subagent-driven-development. I passi usano le checkbox (`- [ ]`).

**Obiettivo:** riscrivere template e CSS di tutta l'interfaccia web nella direzione Bianco con Liquid Glass, senza toccare il Python e senza rompere test, agganci JS e CSP.

**Architettura:** fondamenta condivise (`base.css`, `theme.js`, macro) costruite per prime; poi aree indipendenti in parallelo, ognuna proprietaria esclusiva dei propri file; infine pulizia, verifica nel browser reale e revisione avversaria.

**Tecnologie:** Jinja2 (FastAPI), CSS moderno senza build (custom properties, `@layer`, `:has()`, `text-wrap`, `backdrop-filter`), JavaScript vanilla, font Inter variabile ospitato.

**Spec:** [`spec.md`](spec.md) · **Vincoli:** [`contract-map.md`](contract-map.md) (vincolante)

## Vincoli globali

- Nessun file Python sotto `lumia/` cambia. I test esistenti non si modificano.
- CSP: niente `<script>` inline, niente `<style>`, niente attributi `style="…"`, niente `on*=`, niente risorse esterne (font, CSS, JS, immagini). Le larghezze dinamiche si fanno con `<progress>`/`<meter>` o classi, non con stili inline. JS può usare `el.style.setProperty`, mai `setAttribute('style', …)`.
- `macros.html` può usare solo filtri nativi di Jinja e `money` (l'app del sito non ha `date` né `decimal`).
- Stringhe testate con apostrofo tipografico U+2019: `Vai all’area clienti`, `Esci dall’account`. Non normalizzarle.
- Ogni form POST: `method="post"` minuscolo, stessa `action`, stessi nomi di campo, `{{ csrf(user) }}`, pulsanti `type=submit` dentro il form, `disabled` in demo.
- `[hidden]{display:none!important}` deve valere ovunque.
- Versione degli asset: `?v=20261019` su ogni file CSS/JS nuovo o modificato.
- Lingua dell'interfaccia: italiano. Nessun testimonial, numero, cliente o logo inventato.
- Gli agenti **non** eseguono `git commit`, `checkout`, `stash`, `reset` o `push`: i commit li fa l'orchestratore alla fine di ogni fase. Ogni agente modifica **solo** i file del proprio compito.

## Ambiente locale (già pronto)

- Python: `design/.venv/Scripts/python` (dipendenze di `requirements.txt` installate).
- Test: `design/.venv/Scripts/python -m unittest discover -s tests` → baseline 263 OK.
- Server demo (già in esecuzione): manager demo `http://127.0.0.1:8765` (staff su `/`, cliente con `?view=client`), landing `http://127.0.0.1:8766`. Avvio, se fermo: `design/.venv/Scripts/python design/tools/serve_demo.py`. I template si ricaricano da soli; gli statici non sono in cache nel controllo.
- Chrome headless sulla porta 9335 (già in esecuzione).
- Controllo nel browser: `node design/tools/check.mjs --only <prefissi> --themes light,dark --sizes desktop,mobile --out design/shots/<compito>`. Segnala errori JS, violazioni CSP, richieste fallite e scroll orizzontale, e salva gli screenshot PNG (aggiungi `--full` per la pagina intera). Prefissi: `landing`, `intake`, `login`, `error`, `staff-home`, `staff-orders`, `staff-new`, `staff-detail-`, `staff-activity`, `staff-agenda`, `staff-customers`, `staff-payments`, `staff-settings`, `client-home`, `client-orders`, `client-detail-`, `client-activity`, `client-agenda`, `client-payments`, `client-tutorial`. Baseline sull'interfaccia attuale: zero errori JS e zero violazioni CSP.
- Riferimento visivo: `design/mockups/bianco/index.html` (aprilo con Read per leggerne il CSS) e gli screenshot `design/mockups/shots/bianco-*.png`.

---

## Task 1: test di guardia per il redesign

**File:**
- Crea: `tests/test_redesign_templates.py`

**Interfacce:** produce i controlli statici che le fasi successive devono soddisfare.

- [ ] **Passo 1: scrivi i test**

```python
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
```

- [ ] **Passo 2: eseguili e verifica che falliscano dove previsto**

Run: `design/.venv/Scripts/python -m unittest tests.test_redesign_templates -v`
Expected: FAIL in `test_pages_use_the_new_foundation`, `test_theme_script_runs_before_first_paint`, `test_legacy_stylesheets_are_gone`, `test_fonts_are_self_hosted` (manca `base.css`). Gli altri passano già.

- [ ] **Passo 3: commit** (orchestratore) `Test di guardia per il redesign`

---

## Task 2: fondamenta condivise

**File:**
- Crea: `lumia/static/base.css`, `lumia/static/theme.js`
- Modifica: `lumia/templates/macros.html` (solo disegno delle icone, nuove icone, nuova macro `glass_defs`; firme e output di `icon`, `badge`, `avatar`, `csrf`, `order_table` invariati)
- Crea: `design/gallery.html` (galleria dei componenti per la revisione, fuori dal repo)

**Interfacce prodotte (API usata da tutti i compiti successivi):**

`base.css` è organizzato in `@layer tokens, base, components, utilities;` e definisce:

- `@font-face { font-family: "Inter"; src: url('/static/fonts/InterVariable.woff2') format('woff2'); font-weight: 100 900; font-display: swap; }`
- Token della spec §4.1 su `:root` e versione scura su `html[data-theme="dark"]`, più i token del vetro: `--glass-bg`, `--glass-border`, `--glass-highlight`, `--glass-shadow`, `--glass-blur`.
- Base: reset, `body` (font Inter, `--t-body`, `--ink-2` su `--canvas`), titoli con tracking ottico e `text-wrap: balance`, `[hidden]{display:none!important}`, focus ring, `.skip-link`, `.sr-only`, `::selection` color accento.
- Componenti, con questi nomi esatti:
  - `.wrap` (contenitore `--maxw` con `--gutter`)
  - `.button` con `.primary` (nero), `.accent` (blu), `.secondary` (grigio), `.ghost`, `.danger`, `.small`, `.large`; stati `:disabled`, `[aria-busy="true"]`, pressione `scale(.97)`; `.icon-button` (44 px tondo)
  - `.text-link`
  - campi: stile globale per `input`, `select`, `textarea` nativi (16 px minimo, raggio 12, bordo `--line-2`, focus accento); `.field` (`<label class="field"><span class="field-label">…</span> controllo <small class="field-hint">…</small></label>`); `.form-grid` (2 colonne, 1 sotto 620 px); `.form-actions`; `.check` per checkbox e radio in riga
  - `.badge` con le 7 classi di fase e `.badge-dot` (output della macro `badge`)
  - `.avatar`, `.avatar.large`
  - `.panel` (superficie card), `.panel-heading` (h2 + azioni a destra), `.panel-body`, `.panel.flush` (senza padding interno)
  - `.page-heading` (`.eyebrow`, `h1`, `.lede`, `.page-actions`)
  - `.table-scroll` e `table.data-table` (intestazioni `--ink-3`, righe con hairline, `.number` allineato a destra con `tnum`); sotto 620 px `.data-table.stack` diventa a schede
  - `.empty-state` (icona, `h3`, `p`, azione)
  - `.notice` con `.ok`, `.warn`, `.bad`; `.demo-banner`
  - `.segmented` (gruppo di `button` o `a` con `aria-pressed="true"`/`aria-current`), in vetro
  - `.pill`, `.chip`, `.kbd`
  - `progress` stilizzato (traccia `--surface-3`, valore accento; `.ok` verde)
  - `details.disclosure` > `summary` con icona `chevron` che ruota; niente glifi via `content`
  - `.glass` (spec §4.4) con `.glass-strong` (più opaco, per testi lunghi) e `.glass-thin`
  - `.eyebrow`, `.lede`, `.muted`, `.fineprint`, `.tnum`, `.divider`
- `@media (prefers-reduced-motion: reduce)`, `(prefers-reduced-transparency: reduce)`, `(prefers-contrast: more)` con le versioni statiche e piene.

`theme.js` (caricato nel `<head>` senza `defer`):

```js
// Applies the saved theme before first paint and wires [data-theme-toggle] buttons.
(() => {
  const root = document.documentElement;
  const read = () => { try { return localStorage.getItem('lumia:theme'); } catch { return null; } };
  const apply = theme => { root.dataset.theme = theme === 'dark' ? 'dark' : 'light'; };
  apply(read());
  document.addEventListener('DOMContentLoaded', () => {
    const sync = () => document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      const dark = root.dataset.theme === 'dark';
      button.setAttribute('aria-pressed', String(dark));
      button.setAttribute('aria-label', dark ? 'Usa il tema chiaro' : 'Usa il tema scuro');
    });
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-theme-toggle]');
      if (!button) return;
      apply(root.dataset.theme === 'dark' ? 'light' : 'dark');
      try { localStorage.setItem('lumia:theme', root.dataset.theme); } catch {}
      sync();
    });
    sync();
  });
})();
```

Macro nuove in `macros.html`:

- `glass_defs()`: un solo `<svg class="glass-defs" aria-hidden="true" focusable="false" width="0" height="0">` con `<filter id="lg-refract" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">` (`feTurbulence type="fractalNoise" baseFrequency="0.008 0.012" numOctaves="1" seed="7"` + `feGaussianBlur stdDeviation="2"` + `feDisplacementMap in="SourceGraphic" scale="18" xChannelSelector="R" yChannelSelector="G"`). `.glass-defs` in `base.css` è `position:absolute; width:0; height:0; overflow:hidden`.
- Icone: ridisegna tutte quelle esistenti in stile SF Symbols (tratto 1,6, terminali arrotondati, griglia 24) e aggiungi `sun`, `moon`, `chevron`, `external`, `home`, `flag`, `euro`, `menu`, `more`, `paypal-lock` (lucchetto con scudo, per il pagamento). Fallback invariato.

- [ ] **Passo 1:** leggi spec §4, contract map §2 e il CSS del mockup Bianco (`:root`, componenti, `.glass`/`backdrop-filter`, tema scuro).
- [ ] **Passo 2:** scrivi `theme.js` esattamente come sopra.
- [ ] **Passo 3:** scrivi `base.css` con l'API sopra, valori dai token del mockup.
- [ ] **Passo 4:** aggiorna `macros.html` (icone e `glass_defs`). `csrf` resta byte per byte `<input type="hidden" name="csrf" value="{{ user.csrf }}">`.
- [ ] **Passo 5:** crea `design/gallery.html`: pagina statica che collega `/static/base.css` e `/static/theme.js` (percorsi assoluti `/static/…`) e mostra ogni componente in chiaro e scuro, con contenuti realistici in italiano. È servita da `design/serve.mjs` su `http://127.0.0.1:4174/gallery.html` (già in esecuzione; `/static/*` viene da `lumia/static`). Screenshot: `node design/tools/shoot-url.mjs http://127.0.0.1:4174/gallery.html design/shots/task2/gallery` (produce `-light`/`-dark` × desktop/mobile).
- [ ] **Passo 6:** verifica.
  - `design/.venv/Scripts/python -m unittest discover -s tests` → nessuna regressione nei 263 test esistenti (i nuovi test di guardia possono ancora fallire per `LEGACY` e per le pagine non migrate).
  - Screenshot della galleria in chiaro e scuro a 1440 e 390 px; guardali e correggi finché il risultato è all'altezza del mockup.
- [ ] **Passo 7:** commit (orchestratore) `Fondamenta del redesign: base.css, tema, icone e Liquid Glass`

---

## Task 3: shell della dashboard

**File:**
- Modifica: `lumia/templates/dashboard.html`, `lumia/templates/manager/dialogs.html`
- Riscrivi: `lumia/static/workspace.css`
- Crea vuoti con commento d'intestazione: `lumia/static/project.css`, `lumia/static/board.css`, `lumia/static/pages.css`
- Modifica minima consentita: `lumia/static/workspace.js` solo per (a) chiudere la palette con un clic sullo sfondo da qualsiasi lato (oggi solo `clientX < rect.left`, riga ~133) e (b) nient'altro.

**Interfacce:**
- Consuma: API di `base.css`, `theme.js`, `glass_defs()`, icone.
- Produce: struttura della shell e classi comuni della dashboard in `workspace.css`: `.app-shell`, `.sidebar`, `.app-main`, `.topbar` (vetro, sticky), `.tabbar` (vetro, solo telefono), `.nav-item` (`.active`, `.nav-count`, `.notification-dot`), `.manager-main`, `.page-heading` già in base, `.dashboard-grid` (griglia 12 colonne responsive con `.span-4`, `.span-6`, `.span-8`, `.span-12`), `.workspace-section-heading`, `.workspace-toast`, `.workspace-updates`, `.command-dialog`, `.guide-dialog` (geometria della contract map §3.7). I compiti 6, 7 e 8 usano queste classi e scrivono solo nei propri CSS.

Testa del documento (ordine esatto):

```html
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f5f5f7">
<title>{{ … }} · Lumia</title>
<link rel="icon" href="/static/lumia-logo-discord.png">
<script src="/static/theme.js?v=20261019"></script>
<link rel="preload" href="/static/fonts/InterVariable.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/static/base.css?v=20261019">
<link rel="stylesheet" href="/static/workspace.css?v=20261019">
<link rel="stylesheet" href="/static/project.css?v=20261019">
<link rel="stylesheet" href="/static/board.css?v=20261019">
<link rel="stylesheet" href="/static/pages.css?v=20261019">
{% if page == 'tutorial' %}<link rel="stylesheet" href="/static/tutorial.css?v=20261019">{% endif %}
<script src="/static/ui.js?v=20261019" defer></script>
<script src="/static/workspace.js?v=20261019" defer></script>
{% if page == 'tutorial' %}<script src="/static/customer-tutorial.js?v=20261019" defer></script>{% endif %}
```

- [ ] **Passo 1:** leggi contract map §3.6, §3.7, §4 (workspace.js) e la vista `#manager` del mockup.
- [ ] **Passo 2:** riscrivi `dashboard.html` mantenendo: attributi del `<body>`, import e `suffix` in cima, breadcrumb, include `'manager/'+page+'.html'` (i due rami possono unirsi), banner demo con `DEMO`, notice `Riconciliazione richiesta`, `[data-workspace-updates]` unico e `hidden` con `[data-workspace-refresh]`, `.workspace-toast` unico e `hidden`, `[data-command-open]` con `data-tour="search"`, un solo `details.account-menu` con popover (link guida `[data-guide-open]`, tutorial per i clienti, impostazioni per lo staff, interruttore tema `[data-theme-toggle]`, form di logout con `{{ csrf(user) }}` e `Esci dall’account`, non in demo), navigazione con i `data-tour` richiesti e `aria-current`. Aggiungi `{{ glass_defs() }}` subito dopo l'apertura del `<body>`, la sidebar per desktop e la tab bar in vetro per telefono (destinazioni: staff Home, Progetti, Agenda, Attività, Pagamenti; cliente Home, Progetti, Attività, Pagamenti, Tutorial).
- [ ] **Passo 3:** riscrivi `dialogs.html` (palette e tour) in vetro, mantenendo ogni aggancio e la geometria del tour.
- [ ] **Passo 4:** scrivi `workspace.css`.
- [ ] **Passo 5:** modifica la chiusura della palette in `workspace.js` come indicato.
- [ ] **Passo 6:** verifica.
  - Test: `design/.venv/Scripts/python -m unittest discover -s tests` → i 263 test esistenti OK.
  - Browser: `node design/tools/check.mjs --only staff-home,client-home,staff-orders --themes light,dark --out design/shots/task3` → zero errori JS e CSP, nessuno scroll orizzontale. Apri gli screenshot e controlla la shell (il contenuto delle pagine sarà migliorato nei compiti 6-8).
  - Interazioni a mano con Puppeteer o nel pannello browser: Ctrl+K apre la palette, filtro, Esc; tour avanti/indietro/salta; menu account; interruttore tema che persiste al ricaricamento.
- [ ] **Passo 7:** commit (orchestratore) `Shell della dashboard`

---

## Task 4: landing

**File:**
- Riscrivi: `lumia/templates/landing.html`, `lumia/static/landing.js`
- Crea: `lumia/static/site.css`
- Non toccare `ui.js` (è condiviso): se non serve più alla landing, non collegarlo.

**Interfacce:** consuma `base.css` (vetro, pulsanti, tipografia), `icon`, `glass_defs`. La landing non usa `theme.js` ed è sempre chiara: `<html lang="it" data-theme="light">`, `<meta name="color-scheme" content="light">`.

- [ ] **Passo 1:** leggi spec §5.1, contract map §3.1 e §5 "Public", e tutta la vista `#landing` del mockup Bianco (markup, CSS, JS). È il riferimento da superare, non da copiare alla cieca.
- [ ] **Passo 2:** riscrivi `landing.html`. Obbligatori: `class="returning-client"` come unica classe e prima di `href` (`<a class="returning-client" href="{{ manager_url }}/login">`); la sottostringa esatta `href="/ordina">Inizia il tuo progetto` (nessuna icona o spazio tra `>` e il testo); `Hai già un ordine in corso?`; `Vai all’area clienti` (U+2019); `Il tuo prossimo server.`; `PayPal`; gli anchor `#main`, `#servizi`, `#metodo`, `#domande`; i link `/ordina?platform=fivem|minecraft|discord`, `{{ manager_url }}/login`, `{{ discord_url }}` con `target="_blank" rel="noopener noreferrer"`; meta SEO e Open Graph attuali; favicon; preload del font. Solo `/static/…` e `data:` per le immagini.
- [ ] **Passo 3:** scrivi `site.css` e `landing.js` (ogni `querySelector` controllato; si ferma con `prefers-reduced-motion` e a scheda nascosta; nessuno stile inline via attributo).
- [ ] **Passo 4:** verifica.
  - `design/.venv/Scripts/python -m unittest tests.test_customer_tutorial tests.test_intake tests.test_checkout_installments` → OK.
  - `node design/tools/check.mjs --only landing --out design/shots/task4 --full` → zero errori; guarda gli screenshot (desktop e telefono) e itera fino a un risultato da portfolio.
  - Prova anche con movimento ridotto: in Puppeteer `page.emulateMediaFeatures([{name:'prefers-reduced-motion', value:'reduce'}])`.
- [ ] **Passo 5:** commit (orchestratore) `Landing Bianco`

---

## Task 5: richiesta guidata e pagine di accesso

**File:**
- Riscrivi: `lumia/templates/intake.html`, `lumia/static/intake.css`, `lumia/templates/login.html`, `lumia/templates/error.html`, `lumia/templates/paypal-return.html`
- Crea: `lumia/static/auth.css`
- Non toccare `intake.js` e `paypal-return.js`.

**Interfacce:** consuma `base.css`, `theme.js`, icone, `glass_defs`. Testa delle pagine: come nel compito 3 ma con `auth.css` (login, error, paypal-return) o `intake.css` (intake) dopo `base.css`. `error.html` riceve solo `status` e `detail`, non estende layout, include la favicon.

- [ ] **Passo 1:** leggi spec §5.2-5.3, contract map §3.2-3.5.
- [ ] **Passo 2:** riscrivi `intake.html` mantenendo tutti gli agganci di §3.2 (6 `fieldset[data-step]` con `h2`, id dei pulsanti e degli stati, `<dialog id=clear-dialog>`, attributi del `<body>` con `data-csrf` come primo `data-csrf` della pagina, radio `platform`, select `service`/`budget`/`timeline` con i valori dei dizionari, `label[data-other-for]`, `Non devi entrare nel server.` nello stato anonimo, `noindex`).
- [ ] **Passo 3:** scrivi `intake.css` (con le regole `[hidden]` di §6.1 punto 7).
- [ ] **Passo 4:** riscrivi `login.html`, `error.html`, `paypal-return.html` e scrivi `auth.css`.
- [ ] **Passo 5:** verifica.
  - `design/.venv/Scripts/python -m unittest discover -s tests` → OK.
  - `node design/tools/check.mjs --only intake,login,error --themes light,dark --out design/shots/task5` → zero errori.
  - Wizard con Puppeteer: avanza i 6 passi, scegli una piattaforma, compila un campo, verifica riepilogo e bozza ripristinata dopo il ricaricamento, nessun errore in console.
- [ ] **Passo 6:** commit (orchestratore) `Richiesta guidata e accesso`

---

## Task 6: pagina progetto

**File:**
- Riscrivi: `lumia/templates/manager/detail.html`, `order-journey.html`, `brief.html`, `collaboration.html`, `support.html`, `plan-macro.html`
- Scrivi: `lumia/static/project.css`

**Interfacce:** consuma `base.css` e le classi comuni di `workspace.css` (compito 3). Mantiene firma e struttura di `plan_part(index, milestones, title='', amount='')` e tutti gli agganci del plan builder di `ui.js`.

- [ ] **Passo 1:** leggi spec §5.5, contract map §3.11 per intero, e la vista `#cliente` del mockup.
- [ ] **Passo 2:** riscrivi i template: card "Il prossimo passo" = `aside.payment-callout[data-tour=payment]` con la priorità dei rami fissata; stepper; riepilogo; pannelli con gli anchor; strumenti staff raggruppati; tutti i form della tabella §3.11 identici nei campi e nelle condizioni; testo `Ordini e pagamenti si gestiscono qui. Discord è dedicato all’assistenza.` spostato dal CSS nel template.
- [ ] **Passo 3:** scrivi `project.css`.
- [ ] **Passo 4:** verifica.
  - `design/.venv/Scripts/python -m unittest discover -s tests` → OK.
  - `node design/tools/check.mjs --only staff-detail-,client-detail- --themes light,dark --out design/shots/task6 --full` → zero errori.
  - Plan builder con Puppeteer sullo staff, nel progetto con residuo e senza piano: aggiungi e rimuovi una tranche, controlla rinumerazione e totale.
- [ ] **Passo 5:** commit (orchestratore) `Pagina progetto`

---

## Task 7: home, progetti e bacheca

**File:**
- Riscrivi: `lumia/templates/manager/overview.html`, `orders.html`, `project-card.html`, `queues.html`, `new.html`, e la macro `order_table` in `macros.html` **solo nel markup interno** (firma, logica dei rami e attributi invariati).
- Scrivi: `lumia/static/board.css`

**Interfacce:** consuma `base.css` e `workspace.css`. Nota: il compito 2 possiede `macros.html`; questo compito può modificare **solo** il corpo di `order_table`.

- [ ] **Passo 1:** leggi spec §5.6, contract map §3.8-3.10 e la vista `#manager` del mockup.
- [ ] **Passo 2:** riscrivi i template mantenendo: `section.workspace-welcome[data-tour=welcome]`, `section.dashboard-metrics[data-tour=summary]` con `.metric-card` figli diretti, `[data-tour=attention]` con `.panel-heading`, `[data-tour=projects]` con `.workspace-section-heading`, il form `.project-filter` (`q`, `stage`, `sort`), `[data-only-favorites]`, `[data-project-view]`, `[data-project-count]`, `[data-project-board]` > `.board-column` > `.board-column-heading` con il conteggio come ultimo `span`, `[data-project-list]` `hidden`, `.favorites-empty`, card `article.workspace-project` con `data-project-id`, `data-search`, `data-stage`, primo `h3` titolo, `button.favorite-button[data-favorite]`; la logica `scoped`/`filtered`; i testi testati.
- [ ] **Passo 3:** scrivi `board.css`.
- [ ] **Passo 4:** verifica.
  - Test → OK.
  - `node design/tools/check.mjs --only staff-home,client-home,staff-orders,client-orders,staff-new --themes light,dark --out design/shots/task7 --full` → zero errori.
  - Con Puppeteer: preferito su una card (toast), filtro preferiti, vista elenco/bacheca, ricerca, cambio ordinamento.
- [ ] **Passo 5:** commit (orchestratore) `Home e bacheca progetti`

---

## Task 8: attività, agenda, clienti, pagamenti, impostazioni, tutorial

**File:**
- Riscrivi: `lumia/templates/manager/activity.html`, `agenda.html`, `customers.html`, `payments.html`, `paypal-checkouts.html`, `settings.html`, `tutorial.html`
- Scrivi: `lumia/static/pages.css`, riscrivi `lumia/static/tutorial.css`

**Interfacce:** consuma `base.css` e `workspace.css`.

- [ ] **Passo 1:** leggi spec §5.7 e contract map §3.12-3.17.
- [ ] **Passo 2:** riscrivi i template mantenendo `activity-item unread`, `data-tour` e selettori del tour (`.customer-grid`, `.settings-stack`, `.tutorial-index`, `[data-tour=ledger]`, `[data-tour=agenda] .panel-heading`, `[data-tour=activity]`), i form (`/activity/read`, verifica PayPal), lo slicing ISO delle date dell'agenda, gli 8 capitoli del tutorial con i loro id, `h2[tabindex=-1]`, i controlli `data-tutorial-*` e i testi testati.
- [ ] **Passo 3:** scrivi `pages.css` e `tutorial.css`.
- [ ] **Passo 4:** verifica.
  - Test → OK.
  - `node design/tools/check.mjs --only staff-activity,staff-agenda,staff-customers,staff-payments,staff-settings,client-activity,client-agenda,client-payments,client-tutorial --themes light,dark --out design/shots/task8 --full` → zero errori.
  - Tutorial con Puppeteer: avanti fino all'ottavo capitolo, indietro, ricomincia.
- [ ] **Passo 5:** commit (orchestratore) `Pagine secondarie e tutorial`

---

## Task 9: pulizia e integrazione

**File:**
- Elimina: `lumia/static/app.css`, `design.css`, `manager.css`, `orders.css`, `landing.css`, `cinematic.css`
- Modifica: `STILE.txt` (sezione WEB riscritta per il sistema Bianco con Liquid Glass)

- [ ] **Passo 1:** `grep -rn "design.css\|manager.css\|orders.css\|app.css\|landing.css\|cinematic.css" lumia/` → nessun risultato fuori dai file da eliminare; poi elimina i file.
- [ ] **Passo 2:** aggiorna `STILE.txt`.
- [ ] **Passo 3:** `design/.venv/Scripts/python -m unittest discover -s tests` → 263 + nuovi test di guardia, tutti OK.
- [ ] **Passo 4:** `node design/tools/check.mjs --themes light,dark --out design/shots/final --full` → zero problemi su tutte le pagine.
- [ ] **Passo 5:** commit `Rimuove i vecchi fogli di stile e aggiorna la guida di stile`

## Task 10: revisione avversaria e correzioni

Revisori indipendenti, ciascuno con una lente: contratti e agganci JS, accessibilità, telefono, tema scuro, CSP e prestazioni, qualità visiva rispetto al mockup e al livello "Apple". Ogni problema viene verificato da un secondo agente prima della correzione; le correzioni vengono riverificate con test e `check.mjs`. Si ripete finché un giro non trova nulla di nuovo.

## Task 11: pull request

Branch `redesign/bianco` → PR verso `main` con descrizione, screenshot principali, esito dei test e del controllo nel browser. Niente merge senza approvazione: il merge pubblica in produzione.
