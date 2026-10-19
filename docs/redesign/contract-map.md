# Lumia UI contract map

This is the reference for rewriting every template under `lumia/templates` and every stylesheet and script under `lumia/static` without breaking the server, the JavaScript or the tests. Python routes, handlers and context builders are out of scope and stay unchanged.

- Repo root: the repository root. All paths below are relative to it.
- Sources: five parallel reader maps covering public pages, the dashboard shell, partials group A, partials group B, and the tests. Where two readers disagreed, the source files were re-read. Those cases are listed in [Section 0](#0-corrections-and-open-questions).
- Legend: **[TEST]** means a test asserts it. **[JS]** means a script reads it without a null check, so removing it throws. **[JS?]** means a script reads it with a guard, so removing it degrades quietly. **[SRV]** means the server parses or validates it. **[?]** means it is unverified.
- **No test runs a browser or executes JavaScript, and TestClient does not enforce CSP.** A green suite tells you nothing about the JS hooks or about CSP violations. Check both by hand in a real browser.

---

## 0. Corrections and open questions

| Topic | Reader claim | Verified in source |
|---|---|---|
| PayPal checkouts on `/payments` | The test reader said the section renders twice (include plus inline) | **Renders once.** `manager/payments.html:5` is the only include, and there is no inline copy. |
| Plan-builder JS | The test reader attributed `data-plan-form` to workspace.js | **ui.js** (`ui.js:32`). workspace.js does not touch it. |
| `.workspace-updates[hidden]` rule | One reader placed it in workspace.css | It is in **orders.css** (line 5). workspace.css line 1 holds `.workspace [hidden]{display:none!important}`. |
| Origin and Referrer coupling | "Adding a no-referrer meta tag makes Origin null" | Confirmed by the comment at `web.py:187-189`. The Origin check is at `web.py:176-177`. It returns a plain `HTMLResponse` 403, **not** error.html. The 413 at `web.py:183` is also plain HTML. |
| ui.js `form[method="post"]` selector case | One reader was unsure | **[?]** In HTML documents, attribute selectors on `method` match case-insensitively in most engines, but do not rely on it. Write lowercase `method="post"` everywhere. |
| Test suite baseline | — | Run on `main` at `b0413ae` with Python 3.11 and `requirements.txt`: **263 tests, OK**. Command: `python -m unittest discover -s tests` from the repository root. |

---

## 1. Page inventory

Two FastAPI apps share these templates:

- The **site app** (`lumia/site.py`, `create_site_app`) runs on `LUMIA_SITE_URL`. In production it is mounted through a Starlette Host route inside the manager app (`web.py` lines 85-93).
- The **manager app** (`lumia/web.py`, `create_app`) runs on `LUMIA_PUBLIC_URL`.

Every authenticated workspace page renders `dashboard.html` through `page(request, user, current, **extra)` (`web.py` 278-346), which includes `manager/<page>.html`.

| Template | Route | Audience | Purpose |
|---|---|---|---|
| `landing.html` | site `GET /` | public, no auth or cookies | Italian marketing page with a cinematic scroll experience: hero, services, ecosystem, journey, principles, FAQ, CTA. |
| _(no template)_ | site `GET /ordina?platform=` | public | Redirects 303 to `{manager}/start`. The `?platform=` param is kept only for `fivem\|minecraft\|discord\|web\|other`. |
| `intake.html` | `GET /start` | public, plus customer and staff | 6-step request wizard. Anonymous users can fill it in; submitting requires a Discord login. |
| `login.html` | `GET /login` | public | Single "Continua con Discord" CTA. It is also the 303 target for an expired session and for `/logout`. |
| _(no template)_ | `/auth/discord`, `/auth/callback` | public | OAuth. `?customer=1` requests scope `identify`; `&return=start` sends the user back to `/start?connected=1`. |
| `error.html` | every HTTPException except 303, and every ValueError (400) | anyone | Shows `status` and `detail` only. |
| `paypal-return.html` | `GET /orders/{n}/paypal/return?token=` | owning customer or staff | Auto-submits the capture POST. Redirects 303 to `?checkout=success` if the order is already paid. |
| `macros.html` | — | shared | `icon`, `badge`, `avatar`, `csrf`, `order_table`. |
| `dashboard.html` | all `page()` routes | customer and staff | Shell: sidebar, topbar, account menu, banners, partial include, dialogs, toast. |
| `manager/overview.html` | `GET /` | both | Welcome, queues, metrics, attention list, agenda preview, recent projects, quicklinks. |
| `manager/orders.html` | `GET /orders?q&stage&sort&focus&view` | both | Filter form, 4-column kanban board and list view. |
| `manager/project-card.html` | (included) | both | A single card on the board or overview. |
| `manager/queues.html` | (included by overview and orders) | both; the `requests` card is staff-only | Focus-queue cards that link to `/orders?focus=`. |
| `manager/new.html` | `GET /orders/new`, `POST /orders` | **staff only** (server enforced) | Create a manual order. |
| `manager/detail.html` | `GET /orders/{n}` | owning customer or staff (`visible_order` returns 404 otherwise) | Project page. Includes order-journey, brief, collaboration and support. |
| `manager/order-journey.html` | (included) | both | 6-step stage stepper. |
| `manager/plan-macro.html` | (macro) | staff | `plan_part()` renders one tranche row. |
| `manager/brief.html` | (included) | both | Intake brief, quote, and the staff quote form. |
| `manager/collaboration.html` | (included) | both | Deliveries, delivery review, and the conversation. |
| `manager/support.html` | (included) | both; the form is customer-only | Discord support ticket. |
| `manager/activity.html` | `GET /activity`, `POST /activity/read` | both | Activity feed and "mark all read". |
| `manager/agenda.html` | `GET /agenda` | both | Dated milestones and tranches. |
| `manager/customers.html` | `GET /customers` | **staff only** | Customer directory. |
| `manager/payments.html` | `GET /payments` | both; events are staff-only | Totals, ledger, CSV export, payment events. |
| `manager/paypal-checkouts.html` | (included by payments) | staff, only when rows exist | Open PayPal checkouts with a verify button. |
| `manager/settings.html` | `GET /settings` | **staff only** | Read-only integration status. |
| `manager/tutorial.html` | `GET /tutorial` | any logged-in user; the nav link is customer-only | 8-chapter customer tutorial. |
| `manager/dialogs.html` | (included on every dashboard page) | both | Command palette and guided-tour dialog. |

Other endpoints the UI talks to:

- `GET /workspace/version`: polled, returns `{version}`.
- `POST /preferences/tour`: fetch.
- `POST /requests` and `POST /requests/questions`: fetch from intake.
- `GET /exports/{projects|payments}.csv`.
- `POST /logout`.
- `POST /orders/{n}/payments`: manual payment. **The route exists and is tested, but no template renders a form for it. Do not add one.**

`static/app.css` is **dead**. No template or Python file references it.

---

## 2. Global constraints

### 2.1 Security headers and CSP

**Manager** (`web.py:185-193`, applied to every response not served on the site host):

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: same-origin          <- required: the POST Origin check depends on it
Content-Security-Policy: default-src 'self'; style-src 'self'; img-src 'self' data: https://cdn.discordapp.com https://media.discordapp.net; script-src 'self'; connect-src 'self'; form-action 'self' https://www.paypal.com https://www.sandbox.paypal.com; frame-ancestors 'none'; base-uri 'none'
Cache-Control: no-store   (except /static/* -> public, max-age=3600)
Strict-Transport-Security: max-age=31536000; includeSubDomains   (not in demo)
```

**Site/landing** (`site.py:30-36`):

```
nosniff, DENY, Referrer-Policy: same-origin
Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'
Cache-Control: public, max-age=300   (HSTS unless preview)
```

What this means for the redesign. Browsers block these silently, and tests will not catch it:

- No inline `<script>`, no `on*=` attributes, no `javascript:` URLs.
- No `<style>` blocks and no `style="..."` attributes. That includes custom-property tricks like `style="--progress:40%"`. JavaScript may still set `el.style.x` or call `style.setProperty`, but must not use `setAttribute('style', …)`.
- No Google Fonts, CDN CSS, CDN JS or icon CDNs. `font-src` falls back to `'self'`, so fonts must be self-hosted under `/static`.
- Images may come only from self or `data:`, plus the Discord CDNs on the manager. **The landing allows only self and `data:`.**
- No `<base>` tag and no framing. fetch and XHR must be same-origin.
- Forms may post only to self. The manager also allows the PayPal hosts.
- **Do not add** `<meta name="referrer" content="no-referrer">` or `referrerpolicy="no-referrer"` on forms or links that submit. Either one makes browsers send `Origin: null`, and every POST then returns 403. `referrerpolicy="no-referrer"` on the avatar `<img>` is fine.

Other server rules:

- Every non-GET request must carry `Origin` equal to the public URL, so it must stay same-origin.
- In demo mode, every non-GET returns 403.
- `/start` must stay `Cache-Control: no-store` **[TEST]**. Middleware sets it.
- The body size limit is 131072 bytes for `/requests` and `/requests/questions`.
- `web.py form()` requires `application/x-www-form-urlencoded`; anything else gets 415, so never use multipart. It also requires a body of at most 32 KB, **no duplicate field names** (400 "Campi duplicati non consentiti"), and a matching `csrf` (403).

### 2.2 Static files and cache busters

- Files are served from `/static/` (`lumia/static`). The manager caches them for 1 h and the site for 5 min. **When a CSS or JS file changes, bump its `?v=` in every template that links it.** Otherwise users get new markup with old assets, or the reverse, for up to an hour.
- No test asserts a `?v=` value, and the current values are inconsistent. You can normalize them.

| Page | Links today |
|---|---|
| landing | `design.css?v=6`, `landing.css?v=7`, `cinematic.css?v=6`, `ui.js?v=6` (defer), `landing.js?v=8` (defer) |
| intake | `design.css?v=6`, `intake.css?v=9`, `intake.js?v=10` (defer) |
| login, error | `design.css?v=4`, `manager.css?v=4`; no JS |
| paypal-return | `design.css?v=8`, `manager.css?v=8`, `orders.css?v=8`, `paypal-return.js?v=8` (defer) |
| dashboard | `design.css?v=6`, `manager.css?v=6`, `workspace.css?v=9`, `orders.css?v=8`, `ui.js?v=6` then `workspace.js?v=9` (both defer, in this order). When `page=='tutorial'` it also links `tutorial.css?v=1` and `customer-tutorial.js?v=1` **[TEST: substring `/static/customer-tutorial.js`]** |

Images referenced from templates:

- `/static/lumia-logo-discord.png` (favicon and brand)
- `/static/lumia-logo-completo.png` (og:image)
- `/static/logos/{fivem,minecraft,discord}.svg`. Intake builds this path from the platform key.
- `static/brand.svg` exists but no template references it **[?]**.

**Shared files.** A rewrite of any of these affects other pages:

| File | Used by |
|---|---|
| `design.css` | **every** page |
| `manager.css` | dashboard, login, error, paypal-return (`.auth-page`, `.auth-card`, `.auth-note`, `.panel`, `.panel-body`) |
| `orders.css` | dashboard, paypal-return (`.auth-shell`) |
| `ui.js` | landing and dashboard |

Either redesign all of these pages together, or give one side new files. Do not delete rules the other side still uses.

**Copy that lives in CSS.** If a CSS rewrite drops these, the copy disappears with no warning:

- `orders.css`: `.support-options:after{content:'Ordini e pagamenti si gestiscono qui. Discord è dedicato all’assistenza.'}`. It renders on the detail page. Move it into the template.
- `design.css`: `details > summary` `+` / `−` glyphs.

### 2.3 Template wiring

- Python references these templates by name, so keep the names and locations: `dashboard.html`, `error.html`, `login.html`, `intake.html`, `paypal-return.html`, `landing.html`.
- `dashboard.html` includes `'manager/'+page+'.html'` for these 10 pages: `overview, orders, activity, agenda, tutorial, detail, new, customers, payments, settings`. Its two `if` branches at lines 45-46 do the same thing and can be merged.
- dashboard.html declares these at the top, and **the partials use them without importing**:
  - `{% from 'macros.html' import icon, badge, avatar, csrf, order_table %}`
  - `{% from 'manager/plan-macro.html' import plan_part with context %}`
  - `{% set suffix = '?view=client' if demo and not user.staff else '' %}`

  If you move to `{% extends %}`/blocks, scoping changes, so add explicit imports in each partial.
- The breadcrumb is a dict subscripted by `[page]`. A new page key without a dict entry fails at render time.
- Filters: the manager has `money` (Italian format, `1.234,56 €`), `date` and `decimal`. The site app has **only** `money` (format `x.xx €`). The landing must not use manager filters or manager context.
- Autoescape is on. **Never apply `|safe` or `Markup` to user data.** Tests inject `<script>alert(1)</script>` and `<img src=x onerror=alert(1)>`. If data has to go inside a script, use `|tojson`, although CSP forbids inline scripts anyway.

### 2.4 Macros API (`macros.html`)

The names and signatures are an API for the whole template tree.

- **`icon(name, cls='')`**: outputs `<svg class="icon {{ cls }}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" … aria-hidden="true">`, whitespace-trimmed. Keep the `icon` class and `aria-hidden`.
  - Supported names: `grid, orders, users, wallet, settings, arrow, up, plus, calendar, bell, help, spark, star, messages, box, layers, columns, list, download, lock, close, check, clock, shield, logout, search, discord`. `logout` and `discord` are currently unused.
  - **Any unknown name falls back silently to an alert-circle**, so a missing or renamed icon raises no error and no test catches it.
  - Names passed dynamically: dashboard nav (`grid, orders, calendar, bell, wallet`), dialogs (`grid, orders, wallet, calendar, bell`), queues (`orders, layers, wallet, box, clock`), intake platforms (`grid` for web, `spark` for other).
  - The artwork and the default `.icon` size (20 px) can be redrawn freely.
- **`badge(stage, stages)`** outputs `<span class="badge {{ stage }}"><span class="badge-dot"></span>{{ stages[stage] }}</span>`.
  - Stage keys: `bozza, preventivo, confermato, in_corso, in_revisione, completato, annullato`.
  - Settings reuses `.badge.completato` and `.badge.bozza`.
- **`avatar(name, url=None, cls='')`** outputs an `<img class="avatar {{cls}}" … referrerpolicy="no-referrer">` when there is a URL (from the Discord CDN), otherwise a `<span class="avatar">` holding the initial. The `large` class is in use.
- **`csrf(user)`** outputs exactly `<input type="hidden" name="csrf" value="{{ user.csrf }}">`. **[TEST]** scrapes `name="csrf" value="([^"]+)"`. Keep the output byte-identical: `name` before `value`, double quotes, one space between them, nothing else between them.
- **`order_table(items, stages, query='', filter='', show_customer=True, demo=False, visible_ids=none)`** renders `div.project-list` > `a.project-row[href=/orders/{id}(?view=client when demo and not show_customer)]`. A row gets the `hidden` attribute when its id is not in `visible_ids`. The empty state is `div.empty-state`.
  - Branch order: for an intake with no quote, show "Da definire" plus "Richiesta chiusa" or "In valutazione". Only after that check paid or due ("Saldato" / "Da saldare"). **The intake check must come before the `due_cents==0` check [TEST].**

---

## 3. Per-page contracts

### 3.1 `landing.html` (site app)

**Context:** `public_url`, `manager_url`, `discord_url`. There is no `{% if %}` anywhere; only the URLs vary.

**Forms:** none, only links.

- CTA links go to `/ordina`, `/ordina?platform=fivem|minecraft|discord`. These paths are relative to the site host.
- Five links go to `{{ manager_url }}/login`.
- Two links go to `{{ discord_url }}` with `target=_blank rel="noopener noreferrer"`.

**JS hooks**. landing.js stops only if `.landing` is missing. **Every other lookup is unguarded [JS]:**

| Hook | Requirement |
|---|---|
| `body.landing` | Root element. ui.js reveals target `.landing .reveal`. |
| `[data-hero-sequence]` (`.hero-scroll-shell`) | Must contain `.site-hero`. Gets the `is-cinematic` class. |
| `[data-hero-title]` (h1), `[data-hero-object]`, `.hero-object` | Required. JS writes their transforms. |
| `.cursor-aura` | Must have a `firstElementChild`. That child is a 580×580 span, and JS offsets it by 290. Gets the `is-visible` class. |
| `[data-tilt]` (3 cards) | Each must contain `.card-shine`, which is 430×430. JS offsets it by 215. |
| `[data-ecosystem]` | Must contain `.ecosystem-sticky`. Gets `is-cinematic` and `is-paused`. |
| `[data-network]` | JS reads its `clientWidth`. |
| `[data-network-node]` | **Exactly 3**, valued 0, 1 and 2. JS uses a fixed 3-entry positions array. |
| `.ecosystem-track>span`, `.network-orbit.orbit-a` | Required. |
| `.journey` | Must contain `.journey-sticky`. Gets `is-enhanced`. |
| `[data-journey-display]`, `.journey-progress i` | Required. |
| `[data-chapter]`, `[data-scene]` | **Exactly 3 of each**, valued 0-2. JS uses a 3-entry weights array, so a 4th element throws a TypeError. |
| `.reveal` | ui.js adds `reveal-ready` and `reveal-pending`. |
| `.ambient` | ui.js toggles `is-paused`. |
| `html` | ui.js toggles `tab-hidden`. |

**CSS state contracts the JS math depends on:**

- `.hero-scroll-shell.is-cinematic`, `.ecosystem.is-cinematic` and `.journey.is-enhanced` (320svh) must be much taller than their sticky child (`.site-hero`, `.ecosystem-sticky`, `.journey-sticky`).
- Under `.is-enhanced`, chapters and scenes are absolutely stacked.
- The sticky header is **76 px on desktop and 68 px at widths ≤760**. These values are hardcoded in JS.
- JS breakpoints:
  - Width: 1000 / 760 / 420 / 350.
  - Height: 900 / 790 / 760.
  - `is-cinematic` applies when motion is not reduced, width > 1000 and height ≥ 900.
  - `is-enhanced` applies when motion is not reduced and height ≥ (790 if width ≤ 760, else 760).
- Reduced-motion and no-JS fallbacks: everything renders stacked and readable.

**Anchors:** `#main` (skip-link target), `#servizi`, `#metodo`, `#domande`, `#ecosystem-title`, `#journey-title`.

**Test-locked:** see [Section 5](#5-test-assertion-checklist).

### 3.2 `intake.html` (`/start`)

**Context:**

- `user`: None or `{id,name,csrf,staff,avatar,…}`
- `demo`
- `ai_enabled`
- `site_url`
- `platforms`, `services`, `budgets`, `timelines`: dicts. **Option and radio values must equal the dict keys exactly**, or the server returns 400.

Key sets:

| Dict | Keys |
|---|---|
| `platforms` | `fivem, minecraft, discord, web, other, discuss` |
| `services` | `complete, custom, improve, other, help` |
| `budgets` | `discuss, under500, 500-1500, 1500-5000, over5000, other` |
| `timelines` | `flexible, month, quarter, date, other` |

**Form.** `form#brief-form method="post" action="/requests" novalidate`. **It is never submitted natively.** intake.js sends a fetch POST as URL-encoded fields:

- `csrf`: from `body[data-csrf]`
- `submission`: a UUID matching `[a-zA-Z0-9_-]{20,80}`
- `brief`: JSON

The response is `{url:'/orders/<n>?submitted=1', id}` or `{detail}` with status 400. JS only follows a URL that matches `^/orders/\d+\?submitted=1$`.

Fields:

| Name | Control | Limit / note |
|---|---|---|
| `platform` | **radio** group | PLATFORMS keys. Preselected from `?platform=`. |
| `service` | **`<select id=service>`** | First option has value `""` ("Da decidere insieme"). |
| `budget`, `timeline` | **`<select>`** | The first key is the default. |
| `name` | input | 120 |
| `goal` | textarea | 2000 |
| `features` | textarea | 2400 |
| `technical` | textarea | 1200 |
| `texts` | textarea | 2000 |
| `style` | textarea | 1000 |
| `deadline` | input | 200 |
| `other_platform`, `other_service`, `other_budget`, `other_timeline` | input inside `label[data-other-for=…]` | 300. Shown and enabled only when the matching value is `other`. |
| `acknowledged` | checkbox, `required` | JS sends `true`; the server rejects anything else. |
| `followup_0..2` | JS-generated textareas in `#followups` | 1000. Sent as `brief.answers[{question,answer}]`, at most 3. |

- The **AI helper** sends `POST /requests/questions` with `{csrf, brief}` and gets `{source:'local-ai'|'guided', questions:[…]}`. It is rate limited to 6 per hour. A 429 comes back as error.html, so the response is non-JSON.
- **Login links** go to `href="/auth/discord?customer=1&amp;return=start"` and carry `data-connect`, which saves the draft before navigating.

**JS hooks** (intake.js returns early only when `#brief-form` is missing; **everything else is unguarded [JS]**):

- `#brief-form`
- `fieldset[data-step]`: **exactly 6**, in order 0-5, **each containing an `h2`**, which gets focus. The `hidden` attribute is toggled.
- `[data-step-to="0..5"]` buttons: `disabled` and `aria-current="step"` are toggled.
- `#step-counter` (text `0N / 06`) and `#saved-state` (`role=status`).
- `.brief-track span`: the first span gets `scaleX`.
- `.brief-sculpture`: JS sets the CSS variable `--phase`.
- `.brief-panel`: JS reads its rect and calls `scrollIntoView` on it.
- Buttons `#brief-back`, `#brief-next`, `#brief-skip` (all `type=button`) and `#brief-submit` (`type=submit`, hidden until step 6, `disabled` when `not user or demo`). JS changes the submit button's text.
- `#brief-error`: `p`, `role=alert`, `tabindex=-1`, `hidden`. JS may append a reconnect `<a>`.
- `#followups` and `#brief-summary`. JS generates `div.brief-summary-item > div > strong + button.text-link` plus a `p`.
- `#assistant-status`.
- `#ask-ai`: optional, rendered only when `ai_enabled and user`.
- `[data-connect]`.
- `#clear-brief`, **`<dialog id=clear-dialog>`** (uses `showModal`), `[data-clear-cancel]`, `[data-clear-confirm]`.
- Body attributes: `data-authenticated`, `data-csrf` (**[TEST]**, must be the first `data-csrf="…"` on the page), `data-demo`. `data-ai` is rendered but never read.
- `platform` must stay radios, and `service`/`budget`/`timeline` must stay `<select>`. JS reads `RadioNodeList.value` and `selectedOptions`, so custom listboxes break the summary and draft restore.
- Draft storage: sessionStorage key `lumia:brief:v1` with a 7-day TTL.

**States to design for:**

- Anonymous: header text "Area clienti". The step-6 `.connect-note` contains **"Non devi entrare nel server."** **[TEST]**, the submit button is disabled, and when `ai_enabled` an AI link reads "Accedi per altri suggerimenti".
- Logged in: header text "Il tuo workspace". Shows the hint "La richiesta sarà associata a {{ user.name }}" and the `#ask-ai` button.
- `ai_enabled` false: shows `span.muted` "Guida Lumia".
- Demo: shows a `.notice` saying sending is disabled, and the submit button is disabled.
- `<noscript>` notice.
- JS-driven states: one step visible at a time; the error banner; session expired (401 or 403 produces a reconnect link); generic error for non-JSON responses; JSON `{detail}`; a 20 s timeout; the sending state; a restored draft.

### 3.3 `login.html`

- **Context:** `demo` (unused) and `site_url`.
- **CTA:** `href="/auth/discord?customer=1"`, plus `site_url` links.
- No JS.
- Body class `auth-page`, `main.auth-card`, `noindex`.
- Styles come from manager.css.

### 3.4 `error.html`

- **Context: only `status` and `detail`.** It must render for anonymous requests and must never depend on `user`, `page`, `suffix` or any base layout that expects them. Otherwise every 4xx/5xx test turns into a 500, because tests run with `raise_server_exceptions=True`.
- It must stay **text/html**. intake.js treats non-JSON responses as generic errors and treats 401/403 as an expired session.
- Links: `/` and `/login`.
- Not used by the site app; site 404s are FastAPI JSON.

### 3.5 `paypal-return.html`

- **Context:** `user` (only `csrf` is used), `number`, `token`.
- **Form:** `<form method="post" action="/orders/{{ number }}/paypal/capture" data-paypal-capture>` containing `{{ csrf(user) }}`, `<input type="hidden" name="token" value="{{ token }}">` and a submit button ("Verifica pagamento").
  - The server validates Origin, csrf, visibility and token ownership.
  - On success it redirects 303 to `/orders/{n}?checkout=success`. Errors return 502, 409 or 404.
- **JS:** paypal-return.js calls `requestSubmit()` on load. Do not add required or invalid inputs to this form.
- Keep the `<noscript>` hint, the `p[role=status]`, and the back link `/orders/{{ number }}`.
- Markup today: `main.auth-shell > section.panel.panel-body`.

### 3.6 `dashboard.html` (shell)

**`<body>` contract.** These are the exact names and value formats:

- `class="workspace"` **[JS]**. Without it, workspace.js and customer-tutorial.js both stop working.
- `data-role`: `admin` or `client` **[TEST: `data-role="admin"`]**.
- `data-user-id`
- `data-page`
- `data-demo`: `true` or `false`
- `data-csrf`
- `data-snapshot`
- `data-tour-status="{{ tour.status|default('') }}"` **[TEST: `data-tour-status="started"` and `data-tour-status=""`]**
- `data-tour-step` (default 0)
- `data-tour-page` (default `overview`)
- `data-tour-version` (default 0)

**Context the shell uses:**

- `user{id,name,staff,csrf,avatar}`
- `page`
- `demo`
- `unread`: an int computed on the server. No JS updates it.
- `snapshot`
- `tour`
- `discord_url`, `site_url`
- `events`: staff only
- `orders`: for the palette

Many more variables are passed for the partials: `totals, stages, customers, payments, milestones, paypal, paypal_environment, public_url, brief_labels, platforms, services, budgets, timelines, attention, agenda, today, activity, read_at, customer_options, queues, tutorial_order, paypal_checkouts`, plus per-route extras.

**Form:** `POST /logout` inside `details.account-menu > .account-popover`. It contains `{{ csrf(user) }}` and a submit button reading **"Esci dall’account"** (U+2019).

- It is **not rendered in demo**.
- **It is the only csrf input on `GET /`**, and the tests scrape that input. Every page needs at least one non-demo csrf input for both staff and clients.

**JS hooks:**

- Exactly one `[data-workspace-updates]` (initially `hidden`, `role=status`) containing `[data-workspace-refresh]` **[JS]**.
- Exactly one `.workspace-toast` (`hidden`, `role=status`, `aria-live=polite`) **[JS]**.
- At least one `[data-command-open]` (the topbar search button, which also carries `data-tour="search"`).
- `[data-guide-open]` triggers.
- `details.account-menu` with a summary and a popover. JS closes it on Escape, on an outside pointerdown, and when the guide opens.
- `#main` / `main.manager-main`: the skip-link target and the guide fallback.
- Nav `data-tour` values: `nav-overview`, `nav-orders`, `nav-agenda`, `nav-activity`, `nav-payments`, and `nav-tutorial` (customer only).

**States to design for:**

| State | What it shows |
|---|---|
| Staff | `.workspace-kind.admin` "Management"; a "Gestione" divider; nav links to `/customers` and `/settings`; a `/settings` link in the popover; the breadcrumb prefix "Management". |
| Customer | Nav link `/tutorial{{suffix}}` (`.nav-tutorial`); a "Tutorial clienti" link in the popover; the label "Area clienti". |
| Staff with a `da_riconciliare` event | `.notice` **"Riconciliazione richiesta"** **[TEST]** with a link to `/payments`. |
| Demo | `.demo-banner` containing **"DEMO"** **[TEST]** and links to `/` and `/?view=client`. No logout. Polling and server-side tour saves are off. All POSTs return 403. `suffix` is added to every internal link. |
| `unread > 0` | `.nav-count` on activity, a `.notification-dot` on the bell, and the aria-label "Attività, N nuove". |
| Active nav item | `active` class plus `aria-current=page`. The `orders` item is also styled active on `detail` and `new`, but `aria-current` is only set on an exact page match. |

Per-page `<title>`:

| Page | Title |
|---|---|
| detail | `order.title` |
| tutorial | Tutorial clienti |
| orders | Progetti |
| new | Nuovo ordine |
| customers | Clienti |
| payments | Pagamenti |
| agenda | Agenda |
| activity | Attività |
| settings | Impostazioni |
| anything else | Workspace |

Every title ends with ` · Lumia`.

### 3.7 `manager/dialogs.html` (every dashboard page)

**Command palette** **[JS, no null checks]**:

- `dialog.command-dialog`: a native `<dialog>` opened with `showModal`.
- **Its first `<input>` must be the search box** (`#command-input`, `type=search`).
- `[data-command-item]`: focusable `<a>` elements linking to `/orders/{id}{{suffix}}`. JS filters them by `textContent`. Arrow keys and Enter work.
- `p.command-no-results`
- `[data-command-close]`
- Ctrl/Cmd+K toggles the palette.
- Quirk: a backdrop click closes it **only when `clientX < dialog rect.left`** (`workspace.js:133`). If you change the layout, adjust the JS.
- Staff-only items: Nuovo ordine, Clienti, Impostazioni. The customer-only item is Tutorial clienti. Project items show the customer name only to staff.
- **The palette must not carry `data-project-id`** **[TEST, indirectly]**.

**Guide dialog** **[JS, no null checks]**:

- `dialog.guide-dialog` (`showModal`; JS intercepts `cancel`; toggles the `is-welcome` class).
- `.guide-spotlight`: JS writes left/top/width/height in viewport px and toggles `hidden`.
- `.guide-card`: JS writes left/top in px and measures it.
- **The first `h2` in the dialog is the title** (`#guide-title`).
- `#guide-description`
- `.guide-step`
- `[data-guide-next]`: JS replaces its text.
- `[data-guide-back]`, `[data-guide-skip]`: JS toggles `hidden`.
- `[data-guide-close]`
- `.guide-dots`: JS fills it with `<i>` elements and adds `.active`.
- `.guide-welcome-icon`
- `.guide-save-status` (`role=status`)
- A customer-only link "Apri il tutorial completo" to `/tutorial{{suffix}}`.

**Guide CSS geometry contract:**

- `.guide-dialog` is fixed and covers the full viewport: `inset:0`, `margin:0`, `width:100%`, `height:100dvh`, no max-width or max-height, transparent background, `overflow:hidden`.
- `.guide-spotlight` and `.guide-card` are `position:absolute` at `left:0; top:0` relative to the dialog. No transforms or padding on ancestors.
- The dimming comes from the spotlight's huge `box-shadow` (`0 0 0 9999px`) with `pointer-events:none`.
- `::backdrop` is transparent in step mode.
- `.is-welcome .guide-card` must be **centred by CSS**, because JS clears the inline coordinates.
- `.guide-card` has a bounded width.

**Auto-open:** the guide auto-opens on every non-tutorial page when the tour status is empty or the tour version does not match (staff v2, client v3). Screenshots will show it.

### 3.8 `manager/overview.html`

- **Context:**
  - `totals.{active,quotes,paid,due}`
  - `attention[]`: up to 5 items `{title,text,kind quote|delivery|payment|draft,url}`
  - `agenda[]`: up to 4 items `{date,title,project,kind,url,overdue}`
  - `orders[:6]`
  - `queues`
  - `selected_focus` (`|default('')`)
  - `user.staff`, `suffix`, `demo`
- **Forms:** none.
- **Links:**
  - `/orders`, `/payments` (twice), `/agenda`, `/activity`, each with `suffix`
  - staff: `<a href="/orders/new" data-tour="create">` and a quicklink `<button type=button data-guide-open>`
  - customer: `/start{{suffix}}` and `/tutorial{{suffix}}`
- **JS hooks:**
  - `section.workspace-welcome[data-tour=welcome]`
  - `section.dashboard-metrics[data-tour=summary]` whose **direct** children are `.metric-card`
  - `[data-tour=attention]` containing a `.panel-heading`
  - `[data-tour=projects]` containing a `.workspace-section-heading`
  - `.dashboard-grid>.panel`: entry-animation selector, cosmetic only
  - `data-tour` values `upcoming`, `quicklinks` and `create` are not read by JS
- **States:**
  - Staff and customer copy differ: "Incassato"/"Pagato", "Da ricevere"/"Da saldare", "In primo piano"/"Tocca a te", "Progetti recenti"/"I tuoi progetti".
  - Singular and plural forms of preventivo.
  - Empty states: "Sei in pari.", "Spazio al lavoro.", and an empty projects panel.
  - Overdue agenda items show "Data trascorsa".
  - Queue cards: `requests` is staff-only; `queue-alert` applies when the overdue count is nonzero; `selected` marks the current focus.

### 3.9 `manager/orders.html`, `project-card.html`, `queues.html`

- **Context:**
  - `orders`, `stages`
  - `query` (`q[:200]`)
  - `selected_stage`
  - `selected_focus`: one of `requests|quotes|payments|deliveries|overdue`
  - `selected_sort`: one of `updated|deadline|amount`. The server does the sorting.
  - `user.staff`, `suffix`, `demo`
- **Template-side business logic that must be reproduced:**
  - `scoped` = orders that pass the focus filter. **Orders outside the focus are not rendered at all [TEST].**
  - `filtered` = orders that pass focus, q and stage. Cards outside it are rendered with the `hidden` attribute.
- **Form:** `GET /orders`, `form.project-filter`. Fields:
  - hidden `view=client`: only when `demo and not user.staff`
  - hidden `focus`: only when a focus is set
  - `q` (text)
  - `stage` (select: `''` plus the STAGES keys)
  - `sort` (select: `updated|deadline|amount`)
  - an unnamed submit button "Filtra"
  - a "Rimuovi filtro" link to `/orders{{suffix}}` when a focus is active
- **Other links:**
  - CSV: `/exports/projects.csv{{suffix}}`
  - CTA: `/orders/new` for staff, `/start{{suffix}}` for customers
  - Queues: `/orders?focus=KEY` plus `&view=client` in the demo client view
- **JS hooks:**
  - `.project-filter` must contain **all three** of `[name=q]`, `[name=stage]` and `[name=sort]` **[JS]**. A change to `sort` calls `requestSubmit()`.
  - `[data-only-favorites]` (`aria-pressed`)
  - `[data-project-view="board"|"list"]` (`aria-pressed`). Both `[data-project-board]` and `[data-project-list]` must exist.
  - `[data-project-count]` (`role=status`). It requires `[data-project-board]` **[JS]**.
  - `[data-project-board]` > `.board-column` > `.board-column-heading`. **The count must be the heading's last `span` child (`span:last-child`)** **[JS]**.
  - `[data-project-list]` (initially `hidden`) holding `order_table` rows `a.project-row` whose hrefs match `/orders/(\d+)`.
  - `.favorites-empty` (initially `hidden`)
  - `data-tour="filters"` on the controls. `data-tour="board"` is unused.
- **Project card:**
  - The root is `article.workspace-project` with `data-project-id="{{o.id}}"` **[TEST]**, `data-search="{{title}} {{customer_name}} {{customer}} {{id}}"` and `data-stage`.
  - **Its first `h3` is the title** **[JS]**.
  - `button.favorite-button[data-favorite=id][aria-pressed][aria-label]`. JS rewrites the label and shows a toast.
  - The card must sit inside `[data-project-board]`.
  - Card link: `/orders/{{o.id}}{{suffix}}`.
- **Card states:**
  - The badge override "In valutazione" applies when the order is an intake at stage `bozza`.
  - Bottom line: for an intake with no quote, "Richiesta chiusa" (annullato) or "Preventivo da definire". Otherwise "Saldato" when `due_cents==0`, or "<money> residui".
  - Staff see a client chip.
  - "Milestone X/Y" with a `<progress max=100>`.
  - The LM code `LM-%04d` is a user-facing identifier. Keep it.
- **Board columns:**

  | Column | Title | Stages |
  |---|---|---|
  | planning | Da definire | bozza, preventivo |
  | active | In lavorazione | confermato, in_corso |
  | review | In revisione | in_revisione |
  | done | Completati | completato, annullato |

  An empty column shows "Nessun progetto in questa fase.". The result count is singular or plural.

### 3.10 `manager/new.html` (staff)

- **Form:** `POST /orders` with these fields:
  - `csrf`
  - `title`: required, max 200
  - `customer`: `<select data-customer-select>`, first option value `""`
  - `total`: required, `inputmode=decimal`, pattern `[0-9]+([.,][0-9]{1,2})?`
  - `customer_id`: inside `<details class="manual-customer">`, numeric, `data-customer-manual`
  - `details`: textarea, max 8000
  - `ticket_id`: optional, numeric
  - submit button "Crea bozza", disabled in demo
- **Server rules:**
  - If `customer` and `customer_id` are both set and differ, the server returns 400.
  - On success it redirects 303 to `/orders/{id}`.
- **JS:** the select and the manual field clear each other (guarded with `?.`). `.form-panel` must exist; it is a tour target. `data-customer-form` is unused.
- Context: `customer_options` as `(id, name)` tuples.

### 3.11 `manager/detail.html` and its includes

**Context:**

- `order`, decorated with: `id, title, stage, customer, customer_name, details, total_cents, paid_cents, due_cents, intake{brief, quote}, payable{amount_cents, installment_id, title}, milestones[], installments[], ticket_url, support_open, completed_milestones, progress`
- `order_payments[]`, `order_audit[]` (rendered reversed), `messages[]` (internal notes are already filtered out for customers), `deliveries[]`
- `checkout_success`, `checkout_cancelled`
- `paypal`: true in demo or when PayPal is ready
- `demo`, `user`, `suffix`, `stages`, `discord_url`
- `brief_labels`, `platforms`, `services`, `budgets`, `timelines`
- A local value: `awaiting = order.intake and not order.intake.quote`.

**Forms.** Every form has `method="post"` (lowercase), urlencoded, `{{ csrf(user) }}`, no duplicate names, and `disabled` on its submit button in demo.

| Form | Action | Fields | Rendered when |
|---|---|---|---|
| Stage | `/orders/{id}/stage` | `stage` (`select#order-stage`, all STAGES keys) | staff. Disabled options when intake and (no quote and key ∉ {bozza, annullato}, or quote and key = bozza). This is UX only; the server re-checks. |
| Accept quote | `/orders/{id}/accept` | csrf only | `stage=='preventivo' and order.customer==user.id` |
| Checkout | `/orders/{id}/checkout` | hidden `installment_id`, only when a plan exists. It must equal the current payable installment, else 409. **No amount is sent.** | `due_cents>0`, stage ∉ {bozza, preventivo, annullato}, `payable.amount_cents>0`, `paypal`. **Must stay a native top-level POST** (the server answers 303 to paypal.com). Button "Paga con PayPal · <amount>". |
| Milestone toggle | `/orders/{id}/milestones/{mid}` | hidden `done` = `0`/`1` | staff, one per row |
| Add milestone | `/orders/{id}/milestones` | `title` (required, 200), `due` (date, required) | staff |
| Release tranche | `/orders/{id}/installments/{iid}/release` | csrf only | staff, when `remaining_cents` and not released |
| Tranche plan | `/orders/{id}/installments` | `part_count` (1-24), then for each contiguous index *i*: `part_{i}_title` (required, 120), `part_{i}_amount` (required, decimal pattern), `part_{i}_due` (date), `part_{i}_milestone` (select `''` = "Su richiesta" or a milestone id). A part sets due **or** milestone, not both. The sum must equal the total. | staff, not awaiting, no installments yet, `due_cents>0`. Prefilled with Acconto (total//2) and Saldo. |
| Reverse payment | `/orders/{id}/payments/{pid}/reverse` | `reason` (required, 1000) | staff, `provider=='manual'` and not reversed |
| Send quote (brief.html) | `/orders/{id}/quote` | `total` (required, decimal; `\d{1,7}([.,]\d{1,2})?`, no thousands separator), `scope` (textarea, 20-8000) | staff, intake, stage `bozza`, no quote |
| Approve delivery | `/orders/{id}/deliveries/{did}/review` | hidden `state=approved` | `d.state=='pending' and user.id==order.customer` |
| Request changes | same URL | hidden `state=changes`, `feedback` (required, 2000) | same condition. **Keep it a separate form.** Merging the two creates duplicate `state` fields and a 400. |
| Publish delivery | `/orders/{id}/deliveries` | `title` (required, 120), `url` (type url, required, 2000; https only, no credentials), `description` (2000) | staff |
| Message | `/orders/{id}/messages` | `body` (required, 4000). Staff also get a checkbox `internal` value `1`. A non-staff POST with `internal` returns 403. Rate limited to 8/min. | everyone |
| Support ticket (support.html) | `/orders/{id}/support` | `reason` (10-1800) | `order.customer==user.id and not order.support_open`. Returns 503 or 409 when Discord is unavailable. |

**JS hooks:**

- **ui.js plan builder:**
  - `[data-plan-form][data-total-cents]`
  - `[data-plan-parts]`, whose **direct children** are the `.plan-part` rows
  - `[data-part-label]`
  - `[data-field=title|amount|due|milestone]`: JS renames them to `part_{i}_{field}`
  - `[data-remove-part]` (`type=button`)
  - `[name=part_count]`
  - `<output data-plan-total>`
  - `.plan-total[data-invalid]`
  - `[data-add-part]` (`type=button`, maximum 24 rows)
  - **The first `<template>` in the form is the row template** (`plan_part(0, milestones)`)
- **`plan_part(index, milestones, title='', amount='')`:** the macro name and signature are fixed. It renders `div.plan-part`, `strong[data-part-label]`, `button[data-remove-part]` and the four `data-field` controls. The first input in each row gets focus after a row is added.
- **Tour targets:** `.detail-title` (must exist), `#request-brief .panel-heading`, `#prepare-quote .panel-heading`, `[data-tour=payment]` (the aside `.payment-callout`), `[data-tour=milestones] .panel-heading`, `[data-tour=plan] .panel-heading`, `[data-tour=deliveries] .panel-heading`, `[data-tour=conversation] .panel-heading`, `#support .panel-heading`.
- **Anchor ids.** Redirects, agenda items, attention items and the tutorial all link to these: `#conversation`, `#deliveries`, `#milestones`, `#payment-plan`, `#payments`, `#support`, `#request-brief`, `#prepare-quote`.

**States to design for:**

- **Heading:** the badge override "In valutazione". Staff see the customer as a link to `https://discord.com/users/{id}` (opens in a new tab).
- **Notices:** `checkout_success` shows "Ritorno da PayPal completato…" with an Aggiorna link. `checkout_cancelled` shows "Hai interrotto il checkout…".
- **Order journey:**
  - Steps: Richiesta, Preventivo, Conferma, Sviluppo, Revisione, Consegna.
  - Stage mapping: `bozza 0, preventivo 1, confermato 2, in_corso 3, in_revisione 4, completato 5`.
  - `annullato` renders nothing.
  - Steps before the current one get `is-done`; the current one gets `is-current` and `aria-current="step"`.
  - Done steps show a check; the others show their index formatted `%02d`.
- **Stats** (Totale, Ricevuto, Residuo): hidden when `awaiting`.
- **Payment callout h2.** Branch order matters **[TEST]**:
  1. awaiting: "Importo da definire."
  2. `not due_cents`: "Tutto saldato."
  3. `payable.amount_cents`: `payable.title`
  4. otherwise: "Una fase alla volta."
- **Payment callout body**, in order:
  1. awaiting: "Il team sta valutando…"
  2. paid: "I pagamenti … sono completi."
  3. stage in {bozza, preventivo, annullato}: "disponibile dopo la conferma del preventivo"
  4. payable: the amount, then the checkout form when `paypal`, otherwise "PayPal sarà disponibile appena…"
  5. otherwise: "La prossima tranche si attiverà…"

  Then an "Apri il ticket" link when there is a `ticket_url`, and `.support-options` (a `#conversation` link plus `discord_url`, plus the CSS-injected copy from §2.2).
- **Brief** (only when there is an intake):
  - Stage `bozza`: `.brief-received`. The staff eyebrow is "Nuova richiesta dal sito"; the customer eyebrow is **"Richiesta ricevuta"**.
  - `#request-brief` always: fact chips, plus `details.request-expand` holding every non-empty `brief_labels` key and every answer. **Collapsed content must be server-rendered [TEST].**
  - Then either "Il preventivo del team" or the `#prepare-quote` form.
- **"Il progetto" panel:** `order.details` or a fallback sentence, plus the accept form.
- **Milestones** `#milestones`: shown when not awaiting, or milestones exist, or the user is staff. Shows a done count, dates as dd/mm/yyyy, "Completata"/"Da completare", and the empty state "Nessuna milestone definita."
- **Payment plan** `#payment-plan`: shown when not awaiting.
  - Each row's sub-line is one of: "Dopo <milestone>", "Dal dd/mm/yyyy", "Disponibile", "Su richiesta".
  - Badges: "Pagata" (`badge completato`), "Da pagare", "In attesa". Partially paid rows show "Ricevuto X".
  - Empty state: "Pagamento unico di <total>."
- **Ledger** `#payments`: shown when not awaiting.
  - Columns are Data, Metodo, Importo, plus "Gestione" for staff. Staff see the reference under the date.
  - Provider labels: PayPal, "Stripe (storico)", "Manuale (storico)".
  - A reversed payment shows a struck-through amount plus a "Storno contabile" row with the negative amount; staff also see the reason.
  - Empty: "Nessun pagamento ricevuto." (colspan 4 for staff, 3 otherwise).
- **Deliveries** `#deliveries`: shown when `not order.intake or order.intake.quote or deliveries or user.staff`.
  - State labels: `pending` "Da verificare", `approved` "Approvata", `changes` "Modifiche richieste".
  - "Apri la consegna" opens in a new tab with `noopener noreferrer`.
  - Customer feedback appears under "Risposta del cliente".
  - Empty: "Le versioni pronte da provare appariranno qui."
- **Conversation** `#conversation`: always shown.
  - Message classes: `internal-message`, `own-message`.
  - Labels: "Nota interna", or "Team Lumia" for a staff author whose name differs.
  - Empty: "Domande sul progetto? Scrivi qui al team."
  - Staff see the internal-note checkbox; customers see "Visibile a te e a Management."
- **Support** `#support`: always shown.
  - "Apri il ticket" links to `https://discord.com/channels/{guild}/{channel}` **[TEST]**.
  - The collapsed form shows the code `LM-%04d` and a "Entra nel server Lumia" link to `discord_url`.
- **History:** `details.expandable` "Cronologia" with `ol.audit-list`. **Customers see it too.**
- **Demo:** every submit button is disabled.

### 3.12 `manager/activity.html`

- **Context:** `activity[]` `{kind message|note|delivery|review, order_id, title, text, author, author_name, created}`, `read_at`, `user`, `suffix`, `demo`.
- **Form:** `POST /activity/read` with csrf only. The button is disabled in demo. Redirects 303 to `/activity`.
- **Hooks:**
  - `data-tour="activity"` (must be visible).
  - Unread items: the class attribute must contain exactly **`activity-item unread`**, `activity-item` first **[TEST]**.
  - Item hrefs: `/orders/{id}{{suffix}}#conversation` for message and note, `#deliveries` for the rest.
- **States:**
  - Unread when `created > read_at` and the author is not the current user.
  - Icons: messages, lock (plus "Nota interna") or box.
  - `item.text` must be rendered.
  - Empty: "Qui arriva ciò che conta."

### 3.13 `manager/agenda.html`

- **Context:** `agenda[]` `{date 'YYYY-MM-DD', title, project, kind Milestone|Tranche, url, overdue}`. `url` is built by the server.
- **Hooks:** `[data-tour=agenda]` containing a `.panel-heading`.
- **States:**
  - Overdue rows get `is-overdue` and the text "Data trascorsa"; others read "In programma".
  - A count pill.
  - The date tile slices the ISO string (`[8:]`, `[5:7]`, `[:4]`), so the format is fixed.
  - Empty: "Nessuna data in programma."
  - `item.title` must be rendered **[TEST]**.

### 3.14 `manager/customers.html` (staff)

- **Context:** `customers[]` `{id,name,avatar,count,total,paid}`.
- **Links:** "Apri i progetti" goes to `/orders?q={{ c.id }}`. The empty state links to `/orders/new`.
- **Hooks:** `.customer-grid` must exist and be visible, even with zero customers.
- **States:** "cliente" vs "clienti"; an avatar image or an initial; the empty state "Nessun cliente".

### 3.15 `manager/payments.html` and `paypal-checkouts.html`

- **Context:**
  - `totals.paid`, `totals.due`
  - `payments[]` `{order_id,title,customer_name,created,provider,amount_cents,reversed_at,reversal_reason}`
  - `events[]` (staff, at most 100) `{provider,id,status,detail,created}`
  - `paypal_checkouts[]` (staff) `{order_id,title,amount_cents,session_id,status,created}`
- **Links:** export to `/exports/payments.csv{{suffix}}`; order links `/orders/{id}{{suffix}}`.
- **Form** (paypal-checkouts, one per row): `POST /payments/paypal/{{ c.session_id }}/verify` with csrf only. Button "Verifica con PayPal", disabled in demo. Rendered only when `user.staff and paypal_checkouts`. **Included once** (see Section 0).
- **Hooks:** `[data-tour=ledger]` on the movements table.
- **States:**
  - Copy: staff "Incassato"/"Da incassare", customer "Hai pagato"/"Da saldare".
  - Provider labels match detail.
  - Reversal rows.
  - Empty: "Nessun pagamento ricevuto."
  - Staff events `details` is auto-open when any event is `da_riconciliare`. Status is rendered with `|replace('_',' ')` **[TEST]**. Empty: "Nessun evento."
  - The checkout `session_id` is printed in `td.reference` **[TEST]**.

### 3.16 `manager/settings.html` (staff)

- **Context:** `demo`, `paypal`, `paypal_environment`, `public_url`.
- **Hooks:** `.settings-stack` must exist and be visible.
- **States:**
  - Discord badge: "Demo" or "Attivo".
  - PayPal badge: "Demo"; "Sandbox" or "Live" (`badge completato`); "Da configurare" (`badge bozza`).
  - A collapsed "Registro e riconciliazione" section.

### 3.17 `manager/tutorial.html`

- **Context:** `tutorial_order` (the user's first visible order, or None), `suffix`, `discord_url`.
- Local value: `project_url = '/orders/'~id~suffix` when there is an order, else `'/orders'~suffix`.
- **No forms.** Viewing the page changes no state **[TEST]**.
- **Hooks** (customer-tutorial.js exits only when the root is missing; **everything else is unguarded [JS]**):
  - `[data-customer-tutorial]` root.
  - `[data-tutorial-chapter]`: **exactly 8 with values `"0".."7"` [TEST]**, indexed in DOM order. Each has an id (`tutorial-account`, `-request`, `-quote`, `-payment`, `-tracking`, `-conversation`, `-delivery`, `-support`) used for hash deep links, and **a focusable `h2` with `tabindex=-1`**.
  - `[data-tutorial-jump="N"]` index links in the same order as the chapters. JS sets `aria-current=step` on the active one.
  - `[data-tutorial-next]`: **text only**, because JS overwrites `textContent` **[TEST: attribute present]**.
  - `[data-tutorial-back]` **[TEST]**.
  - `[data-tutorial-restart]`, `[data-tutorial-status]` (`role=status`), `[data-tutorial-position]` ("Capitolo X di 8").
  - `[data-tutorial-progress]`: an element with a `.value` property (`<progress max=8>`).
  - `[data-tutorial-complete]`: **must contain an `<a>`**, which gets focus.
  - `[data-tutorial-controls]`: rendered `hidden`; JS unhides it.
  - The tour target is `.tutorial-index`. The guide never auto-opens on this page.
  - localStorage key: `lumia:customer-tutorial:v1:{userId}:{role}:{demo}`.
- **States:**
  - Without JS: all chapters visible, controls hidden, plus a `<noscript>` note.
  - With JS: one chapter at a time.
  - Completed: the complete block shows and Next hides on the last chapter.
  - With a project, links point to `/orders/{id}{suffix}#conversation`, `#deliveries` and `#support`. Without one, they point to `/orders{suffix}`.

---

## 4. JS files and their selector dependencies

| File | Pages | Behaviour if hooks are missing |
|---|---|---|
| `landing.js` (218 lines) | landing | Exits only when `.landing` is missing. **Any other missing hook throws** and kills all landing motion. ui.js reveals still work because ui.js is a separate file. |
| `intake.js` (225 lines) | intake | Exits only when `#brief-form` is missing. **Any other missing hook breaks the whole wizard**, so requests cannot be submitted. Only `#ask-ai` and `[data-connect]` are optional. |
| `paypal-return.js` (1 line) | paypal-return | `document.querySelector('[data-paypal-capture]')?.requestSubmit()`. If the hook is missing, the user has to click manually. |
| `ui.js` (85 lines) | landing **and** dashboard | Mostly guarded. Shared, so do not trim it to the landing's needs. |
| `workspace.js` (312 lines) | every dashboard page | Exits when `.workspace` is missing. **Many hooks are unguarded**: a missing hook throws and kills the palette, the guide and polling. |
| `customer-tutorial.js` (63 lines) | tutorial | Exits when the root is missing. **The other hooks are unguarded.** |

**ui.js:**

1. `.landing .reveal`: adds `reveal-ready`; adds `reveal-pending` when the element's top is below 85% of the viewport; removes it on intersection. Off under reduced motion. The CSS contract is `.reveal`, `.reveal.reveal-ready`, `.reveal.reveal-pending`, `.reveal-pending:focus-within` visible, plus a reduced-motion override.
2. A `.manager-main` entry animation, only when no `.workspace` exists. It never runs on the dashboard. sessionStorage key `lumia-entered`.
3. `.ambient`: `is-paused` via IntersectionObserver.
4. `html.tab-hidden` on `visibilitychange`.
5. The plan builder (§3.11).
6. **Every `form[method="post"]`:** after a valid submit, JS disables `event.submitter` and sets `aria-busy="true"` on the next tick. A `pageshow` handler re-enables them. This needs real submit buttons inside the form. A `type=button` or a submit outside the form without a `form=` attribute loses the protection.

**workspace.js:**

- Storage keys: `lumia:favorites:{uid}:{role}`, `lumia:view:{uid}:{role}`, `lumia:tour:v{2|3}:{uid}:{role}`, and sessionStorage `lumia:workspace-entry:{scope}`. Renaming them resets user preferences.
- Toast: `.workspace-toast`, auto-hidden after 2400 ms.
- Favorites, filters and view: see §3.9.
- New order: `[data-customer-select]` and `[data-customer-manual]`.
- **Polling:** runs only when not demo. Every 30 s, and when the tab becomes visible, it fetches `GET /workspace/version` (adding `?view=client` when the URL has it) with `redirect:'error'` and a 10 s timeout. It compares the result with `body[data-snapshot]` and unhides `[data-workspace-updates]`. If the banner is already visible it skips the check, **so the banner must start `hidden`**. The interval is cleared on `pagehide`.
- Command palette and account menu: see §3.6 and §3.7.
- **Guide and tour.** `POST /preferences/tour` (fetch, urlencoded, `keepalive`) with `csrf`, `status` (`started|completed|skipped`), `step` (0-20) and `page`. The server allowlists `page` to `overview|orders|detail|payments|activity|agenda|customers|new|settings|tutorial`; **a new page key needs a web.py change**. The server stores version 2 for staff and 3 for clients. Steps whose target is missing or invisible are **silently skipped**. Step targets by `data-page`:

  | Page | Targets |
  |---|---|
  | overview | `[data-tour="welcome"]`, `[data-tour="summary"]`, `[data-tour="attention"] .panel-heading`, `[data-tour="projects"] .workspace-section-heading`, `[data-tour="search"]`, `[data-tour="nav-activity"]`, `[data-tour="nav-agenda"]`, `[data-tour="nav-tutorial"]` |
  | orders | `[data-tour="filters"]`, `[data-project-board]`, `[data-only-favorites]` |
  | detail | `.detail-title`, `#request-brief .panel-heading`, `#prepare-quote .panel-heading`, `[data-tour="payment"]`, `[data-tour="milestones"] .panel-heading`, `[data-tour="plan"] .panel-heading`, `[data-tour="deliveries"] .panel-heading`, `[data-tour="conversation"] .panel-heading`, `#support .panel-heading` |
  | tutorial | `.tutorial-index` |
  | payments | `[data-tour="ledger"]` |
  | agenda | `[data-tour="agenda"] .panel-heading` |
  | activity | `[data-tour="activity"]` |
  | customers | `.customer-grid` |
  | new | `.form-panel` |
  | settings | `.settings-stack` |
  | fallback | `.page-heading`, then `.manager-main` |

- Entry animation (cosmetic): `.workspace-welcome`, `.dashboard-metrics>.metric-card`, `.dashboard-grid>.panel`, first 6 matches.

**Unguarded workspace.js lookups. Any one of these missing throws:**

- `.workspace-toast`
- `[data-workspace-updates]`
- `.command-dialog`, its first `input`, `[data-command-close]`
- `.guide-dialog` and every guide child listed in §3.7
- a `.project-filter` missing any of `q`, `stage` or `sort`
- a `[data-favorite]` with no `.workspace-project h3` ancestor
- a `.board-column` with no `.board-column-heading>span:last-child`
- `[data-project-count]` with no `[data-project-board]`

---

## 5. Test assertion checklist

Run the suite from the repository root with `python -m unittest discover -s tests -v`.

### How the tests build the app

- `WebTests.setUp` (`test_web.py:34-76`) builds a temp sqlite store and a fake guild. Owner is 1000; members are 99 (Management role 500), 10 and 20.
- An `httpx.MockTransport` fakes Discord OAuth, the PayPal sandbox and Stripe.
- Env: `LUMIA_PUBLIC_URL=https://manager.example`. `LUMIA_SITE_URL` and `LUMIA_DISCORD_INVITE` are unset.
- The client is `TestClient(base_url='https://manager.example', follow_redirects=False)`.
- `login()` goes through `/auth/discord` and then `/auth/callback`.
- `csrf()` runs `GET /` and applies the regex `name="csrf" value="([^"]+)"`. Other test classes borrow these helpers.
- Other builders: `create_demo_app()` at `http://127.0.0.1:8765`; `create_site_app('https://site.example','https://manager.example')`; and `create_app` with `LUMIA_SITE_URL=https://studio.example` for Host routing.

### Shell and global

- [ ] `GET /` (staff and client, not demo) contains `name="csrf" value="…"` with that exact adjacency (`test_web.py:92`, used by almost every POST test).
- [ ] `data-role="admin"`, `data-tour-status="started"`, and `data-tour-status=""` when no tour is saved (`test_workspace.py:129,135,136`).
- [ ] Demo `/` contains `DEMO` (`test_web.py:168`).
- [ ] `Riconciliazione richiesta` appears on `/` for staff when a `da_riconciliare` event exists (`test_web.py:209`, `test_checkout_installments.py:150`).
- [ ] For a client, `/`, `/orders` and `/payments` each contain `href="/tutorial"` **at least twice** (`test_customer_tutorial.py:54`).
- [ ] Demo client view: `href="/tutorial?view=client"`, `href="/orders?view=client"`, and the regex `href="/orders/\d+\?view=client#conversation"` (`test_customer_tutorial.py:65-67`).
- [ ] Staff get 200 on `/`, `/orders`, `/orders/new`, `/customers`, `/payments`, `/settings` and `/orders/{id}`, and none of them contains raw `<script>alert(1)</script>` (`test_web.py:191`).
- [ ] Escaping: `&lt;script&gt;` and `&lt;img src=x onerror=alert(1)&gt;` appear escaped (`test_web.py:195-198`, `test_intake.py:215-216`, `test_workspace.py:53-54`).

### Tutorial

- [ ] Exactly 8 matches of `data-tutorial-chapter="[0-7]"` **anywhere on the page** (`test_customer_tutorial.py:28`).
- [ ] The text contains `Account Discord`, `Nuova richiesta`, `preventivo`, `PayPal`, `tranche`, `Milestone`, `Conversazione`, `Attività`, `consegna`, `Supporto Discord` and `Esci dall’account` (U+2019). Matching is case-sensitive (`:29-30`).
- [ ] Contains `data-tutorial-next`, `data-tutorial-back` and `/static/customer-tutorial.js` (`:31-33`).
- [ ] Contains `href="/orders/{own_id}#conversation"`, and never another customer's id or title (`:43-45`). A client with no project gets `href="/orders"` (`:51`).

### Orders

- [ ] `/orders?focus=payments` contains `data-project-id="{in-focus id}"` and does **not** contain `data-project-id="{out-of-focus id}"` (`test_checkout_installments.py:220`).
- [ ] An unquoted intake order shows `Preventivo da definire` and `In valutazione`, and the page has **no** `>Saldato<` (`test_intake.py:231-233`).
- [ ] A client sees their own titles and never another client's (`test_web.py:137-138`, `test_intake.py:169`).

### Detail

- [ ] Customer view of an unquoted intake: contains `Richiesta ricevuta`, `da definire` and `Testi di benvenuto da definire`; does **not** contain `Tutto saldato.` (`test_intake.py:61-64`).
- [ ] Contains `Dettagli da definire insieme.` (from `order.details`), `Ne parliamo insieme` and `Dopo le vacanze` (`test_intake.py:121,140-141`).
- [ ] With PayPal unconfigured, **no `Paga con PayPal` anywhere on the page**, including the shell and dialogs (`test_checkout_installments.py:225`).
- [ ] The ticket URL `https://discord.com/channels/1/4321` is present (`test_support_web.py:32`).
- [ ] Staff see the reversal reason `Errore di digitazione` (`test_web.py:230`).
- [ ] Customers never see internal notes (`test_workspace.py:37`).
- [ ] `?checkout=success` returns 200, and `/orders/{id}/paypal/return` returns 200 (404 for the wrong order).

### Activity, agenda and payments

- [ ] Unread items contain `activity-item unread`; after `POST /activity/read` the string is absent from the whole page (`test_workspace.py:147-149`).
- [ ] Staff see `NOTA INTERNA SEGRETA`; the client sees `AGGIORNAMENTO PUBBLICO` and not the note; another client sees neither (`test_workspace.py:33-42`).
- [ ] The agenda shows `MIA DATA` and not `DATA SEGRETA` (`test_workspace.py:145-146`).
- [ ] Staff `/payments` contains `da riconciliare`, `WH-REFUND` and the open checkout token (`test_checkout_installments.py:173,232`).

### Public

- [ ] The landing matches the regex `class="returning-client"[^>]*href="https://manager.example/login"`. **`returning-client` must be the only class, and it must come before `href`** (`test_customer_tutorial.py:81`).
- [ ] The landing contains `Hai già un ordine in corso?` and `Vai all’area clienti` (U+2019) (`:82-83`).
- [ ] The landing contains the exact substring `href="/ordina">Inizia il tuo progetto`: `href` is the last attribute and the text follows `>` directly, with no icon or whitespace in between (`test_intake.py:242`).
- [ ] The landing contains `Il tuo prossimo server.` and `PayPal` (`test_checkout_installments.py:204`).
- [ ] The site host returns 404 for `/orders`, `/customers`, `/auth/discord`, `/webhooks/paypal` and `/workspace/version`.
- [ ] Anonymous `/start` contains `Non devi entrare nel server.` and the header `cache-control: no-store` (`test_intake.py:49-50`). Logged-in `/start` has its first `data-csrf="…"` equal to the session token (`test_intake.py:41`).
- [ ] All 4xx/5xx assertions (400/403/404/409/413/415/429/502/503) depend on error.html rendering with only `{status, detail}`.

These test files have **no** template, asset or header assertions: `test_ticket_delete_button`, `test_verification_gate`, `test_orders`, `test_presentation`, `test_integration`, `test_deploy_checks`, `test_tickets`, `test_onboarding`, `test_events`, `test_channel_migration`, `test_setup`, `test_role_reuse`, `test_core`, `test_base`, `test_installments`, `test_operations`, `test_verification`, `test_ai_configuration`.

---

## 6. Rules, freedoms and risks

### 6.1 Must preserve

1. **Routes, template names and context variable names** as listed in Sections 1 and 3. Python does not change.
2. **Form contracts:**
   - lowercase `method="post"`
   - exact action URLs and field names
   - urlencoded body
   - `{{ csrf(user) }}` in every POST form
   - no duplicate names
   - real submit buttons
   - `disabled` on mutating buttons in demo
   - checkout stays a native POST
3. **Role and state conditions** that decide which forms and blocks render: §3.11 for detail, plus the staff/customer gating in the shell, queues, payments, collaboration and support. Do not expose staff-only data to customers (payment references, reversal management, events, checkouts, the `internal` checkbox). Do not hide data customers are meant to see (the audit history, "Apri il ticket").
4. **Template-side business logic:**
   - the focus, q and stage filtering in orders.html
   - the intake-before-paid branch order in detail, project-card and order_table
   - the unread condition
   - the `suffix` propagation for demo clients
   - the delivery-panel visibility condition
5. **The macros API**, with the `csrf` output byte-identical.
6. **Every JS hook** in Sections 3 and 4, including the parent/child relationships and the exact counts: 3 chapters, scenes and nodes on the landing; 6 intake steps, each with an h2; 8 tutorial chapters, each with a focusable h2.
7. **`[hidden]` must really hide.** Keep these rules or equivalents:
   - `.workspace [hidden]{display:none!important}` (workspace.css)
   - `.workspace-updates[hidden]{display:none!important}` (orders.css)
   - `#brief-form fieldset[hidden]`, `.brief-actions [hidden]`, `#brief-form label[data-other-for][hidden]` (intake.css)
   - `.tutorial-chapter[hidden]`, `.tutorial-progress[hidden]`, `.tutorial-complete[hidden]`, `.tutorial-navigation[hidden]` (tutorial.css)
   - `.project-row[hidden]`, which is covered by the workspace rule

   Author rules such as `display:flex`, `display:grid` or `.button{display:inline-flex}` override the UA's `[hidden]` style.
8. **The landing layout constants JS reads:** header heights 76 and 68 px, the 430 px shine, the 580 px aura, the tall cinematic wrappers with sticky children, and the breakpoints. Change them only together with landing.js.
9. **Guide geometry CSS** (§3.7).
10. **Anchor ids** `#conversation`, `#deliveries`, `#milestones`, `#payment-plan`, `#payments`, `#support`, `#request-brief`, `#prepare-quote`, `#tutorial-*`, `#main`, and the landing anchors.
11. **Exact strings** from Section 5, including the curly apostrophes (U+2019). Do not let an editor normalize them.
12. **CSP compliance** and same-origin assets. Keep `Referrer-Policy` semantics; do not use `no-referrer` on anything that submits.
13. **Accessibility hooks JS relies on:**
    - `aria-current="step"`
    - `role=status` on `#saved-state`, `#assistant-status`, `.workspace-toast`, `.guide-save-status`, `[data-tutorial-status]`
    - `role=alert` on `#brief-error`
    - skip links to `#main` (landing and dashboard) and `#brief` (intake)
    - `noindex` on intake, login and paypal-return
14. **Identifiers:** the `LM-%04d` project code, the money/date/decimal filters, and the agenda's ISO date slicing.

### 6.2 Free to change

- All visual CSS: colors, typography, spacing, radii, shadows, gradients, blur, motion. Breakpoints are free too, except the ones landing.js reads.
- Class names that only CSS reads. Examples:
  - Shell: `site-nav`, `hero-*` copy classes, `service-grid`, `faq-*`, `closing-*`, `site-footer`, `manager-shell`, `sidebar`, `topbar`, `nav-item`, `nav-count`, `notification-dot`, `brand`
  - Dashboard components: `metric-*`, `attention-*`, `calm-empty`, `agenda-row`, `date-tile`, `project-card-*`, `stat-card`, `payment-callout` styling, `milestone-row`, `installment-row`, `delivery-*`, `conversation-*`, `message-compose`, `customer-card`, `settings-row`, `queue-card`, `order-journey` visuals, `badge` visuals
  - Public pages: `auth-page`, `auth-card`, `auth-shell`, `pill`, `brief-story`, `platform-choice`, `connect-note`, `tutorial-*` (except the JS ones)

  **Not free:** the JS-read classes listed in Sections 3 and 4, the tour selectors (`.customer-grid`, `.form-panel`, `.settings-stack`, `.tutorial-index`, `.detail-title`, `.panel-heading` and `.workspace-section-heading` where a tour selector needs them, `.page-heading`, `.manager-main`), `.returning-client` and `activity-item`.
- Decorative landing markup with no hook: atmosphere, lenses, orbits other than `orbit-a`, platform tokens, wires, display chrome, scene content, FAQ content, footer.
- Intake decorative markup: atmosphere, orbit, core, roadmap.
- Section order and wrappers, as long as the hooks and their parent/child relationships stay. Tables vs cards, `<details>` vs always-open panels and modals vs inline are all free, as long as the form elements are unchanged and collapsed content is still server-rendered.
- Copy, except the test strings and server-meaningful values (`state=approved|changes`, `internal=1`, `done=0|1`).
- Icon artwork, nav placement (sidebar, top bar or bottom tabs), the mobile client bottom-nav, palette and guide visuals, the dot styling, the breadcrumb and title wording, and the footer.
- CSS file split, names and `?v=` values. Update the links and bump the versions. `app.css` can be deleted.
- Unused attributes: `body[data-ai]`, `data-customer-form`, `data-tour` values `create`, `upcoming`, `quicklinks` and `board`.
- The login template may ignore `demo`.
- The duplicated include branches in dashboard.html can be merged.
- Client-side `maxlength`, `pattern`, `inputmode` and placeholders, since the server re-validates. Keeping them in line with the server limits is recommended.
- The submit icon on intake. JS resets the text to `Invia richiesta →`.

### 6.3 Risks

1. **Shared files.** `design.css`, `manager.css`, `orders.css` and `ui.js` serve both public and dashboard pages. A public-only rewrite will restyle or break the dashboard, and the reverse is also true.
2. **Silent JS breakage.** Tests do not run JS. landing.js, intake.js, workspace.js and customer-tutorial.js throw on missing hooks. A missing guide step degrades without any error. Check every page in a real browser with the console open.
3. **Silent CSP breakage.** TestClient does not enforce CSP. Inline styles and scripts, `style=""`, web fonts and CDNs all fail only in a real browser.
4. **CSRF regex fragility.** Reordering attributes, changing the quotes, inserting an `id` between `name` and `value`, or removing the logout form from `/` breaks nearly every POST test.
5. **Whole-page string counts.** Any of these anywhere on the page fails a test:
   - an extra `data-tutorial-chapter="N"`
   - `Paga con PayPal` in shared copy
   - `>Saldato<` on /orders for intake orders
   - a static `activity-item unread`
   - `data-project-id` in any new list that renders out-of-focus orders (a sidebar, the palette)
6. **error.html extending a base layout** that needs `user`, `page` or `suffix` turns every error into a 500.
7. **Landing adjacency regexes.** `class="returning-client"` must be the only class and must come first. `href="/ordina">Inizia…` must have the text immediately after `>`.
8. **Form merging or nesting** creates duplicate field names, which the server rejects with 400. This includes merging the review forms, adding a hidden+checkbox pair for `internal`, and nested includes that emit two csrf inputs.
9. **Plan-builder markup:**
   - rows that are not direct children of `[data-plan-parts]`
   - another `<template>` before the row template
   - non-contiguous `part_{i}` indices

   Any of these breaks add, remove and renumber, or produces a server 400.
10. **Converting the checkout or the PayPal capture to fetch** breaks the 303 navigation to PayPal and the `form-action` allowance. Adding required inputs to the capture form stops the auto-capture.
11. **Intake controls.** Turning `platform`, `service`, `budget` or `timeline` into custom widgets, or changing option values, breaks the summary and draft restore, and makes the server return 400. Renaming fields orphans sessionStorage drafts.
12. **`{% extends %}` refactors** change macro and `suffix` scoping for the partials. Add explicit imports.
13. **Cache.** If you forget to bump `?v=`, users get mismatched CSS, JS and markup for up to 1 h on the manager and 5 min on the site.
14. **Guide auto-open.** It is a modal on the first visit to each non-tutorial page and will appear in screenshots. Changing the tour version semantics requires a web.py change.
15. **Hidden nav items on mobile** make the guide skip the `nav-*` and `search` steps. That is acceptable, but it shortens the tour.
16. **Command palette backdrop dismissal** only triggers on clicks to the left of the box. A redesigned layout can make outside clicks do nothing.
17. **CSS-injected copy** (`.support-options:after`, the summary `+`/`−`) disappears in a CSS rewrite unless it moves into the templates.
18. **Demo mode.** The middleware rejects every POST, but buttons must still render `disabled`, and links must keep `suffix`, or the demo client view switches to the staff view.
