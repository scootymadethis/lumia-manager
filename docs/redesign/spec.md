# Redesign "Bianco" con Liquid Glass — specifica

Data: 19 ottobre 2026 · Branch: `redesign/bianco`

## 1. Obiettivo

Ridisegnare tutta l'interfaccia web di Lumia (landing, richiesta guidata, accesso, area clienti, manager) nella direzione **Bianco** scelta dal cliente, con tocchi di **Liquid Glass**. Il risultato deve sembrare un prodotto Apple: chiaro, preciso, calmo nei dati e sorprendente nel primo schermo della landing.

Criteri di successo:

1. Ogni pagina usa lo stesso sistema visivo (token, tipografia, componenti, movimento).
2. Il backend Python non cambia: route, handler, contesto dei template, permessi, pagamenti.
3. Tutti i test esistenti passano (baseline: 263 test verdi su `main` al commit `b0413ae`).
4. In un browser reale, con la CSP di produzione, nessuna pagina produce errori in console o violazioni CSP, per cliente e staff, su desktop e telefono, in tema chiaro e scuro.
5. Ogni flusso funziona come prima: richiesta guidata, preventivo, pagamento PayPal, consegne, messaggi, supporto, tutorial, palette ⌘K, tour guidato, preferiti, filtri, aggiornamenti automatici.

## 2. Riferimenti

- Mockup approvato: `design/mockups/bianco/index.html` (locale, escluso da git). Viste `#landing`, `#cliente`, `#manager`. Screenshot in `design/mockups/shots/bianco-*.png`.
- Vincoli tecnici: [`contract-map.md`](contract-map.md). **È vincolante**: ogni aggancio JS, form, stringa testata e regola CSP elencati lì va rispettato.

## 3. Ambito

| Area | File |
|---|---|
| Landing (sito pubblico) | `templates/landing.html`, `static/landing.js` (riscritto), nuovo `static/site.css` |
| Richiesta guidata | `templates/intake.html`, `static/intake.css` (riscritto). `static/intake.js` resta invariato |
| Accesso, errori, ritorno PayPal | `templates/login.html`, `error.html`, `paypal-return.html`, nuovo `static/auth.css` |
| Shell dashboard | `templates/dashboard.html`, `templates/manager/dialogs.html`, `static/workspace.css` (riscritto) |
| Progetto (cliente e staff) | `manager/detail.html`, `order-journey.html`, `brief.html`, `collaboration.html`, `support.html`, `plan-macro.html`, nuovo `static/project.css` |
| Home, progetti, bacheca | `manager/overview.html`, `orders.html`, `project-card.html`, `queues.html`, `new.html`, nuovo `static/board.css` |
| Altre pagine | `manager/activity.html`, `agenda.html`, `customers.html`, `payments.html`, `paypal-checkouts.html`, `settings.html`, nuovo `static/pages.css` |
| Tutorial clienti | `manager/tutorial.html`, `static/tutorial.css` (riscritto). `customer-tutorial.js` resta invariato |
| Fondamenta condivise | nuovo `static/base.css`, `templates/macros.html` (icone ridisegnate, nuova macro `glass_defs`), nuovo `static/theme.js`, font `static/fonts/InterVariable.woff2` |

Fuori ambito: codice Python (`lumia/*.py`), bot Discord, database, testi di `server_texts.json`, test esistenti (non si modificano per farli passare).

File da eliminare a fine lavoro, dopo aver verificato che nessun template li richiami: `static/app.css` (già inutilizzato), `design.css`, `manager.css`, `orders.css`, `landing.css`, `cinematic.css`.

JS esistenti: `intake.js`, `workspace.js`, `customer-tutorial.js`, `paypal-return.js`, `ui.js` restano. Sono ammesse solo modifiche minime e motivate (per esempio il pulsante del tema o la chiusura della palette con clic sullo sfondo, oggi limitata al lato sinistro). `landing.js` viene riscritto da zero insieme alla landing.

## 4. Sistema visivo

### 4.1 Token (in `base.css`, su `:root`)

Dal mockup approvato:

- **Colori chiari**: `--canvas #ffffff`, `--canvas-alt #f5f5f7`, `--surface #ffffff`, `--surface-2 #f5f5f7`, `--surface-3 #e8e8ed`, `--ink #000000`, `--ink-2 #424245`, `--ink-3 #6e6e73` (minimo per testo), `--ink-4 #aeaeb2` (solo decorativo), `--line rgba(0,0,0,.08)`, `--line-2 rgba(0,0,0,.13)`.
- **Accento**: il blu ghiaccio del logo scurito, `--accent #0a5bb5` (6,6:1 sul bianco), `--accent-press #084c97`, `--accent-bg #e8f1fb`, `--accent-ice #a8c9ee`, bagliore `--glow 90,169,240`.
- **Stati**: `--ok #1f7a3d / --ok-bg #e9f5ec`, `--warn #a15c00 / #fff4e2`, `--bad #c0311f / #fdecea`, `--review #6a45c4 / #f1ecfb`.
- **Fasi** (badge): bozza grigio, preventivo warn, confermato e in_corso accent, in_revisione review, completato ok, annullato bad.
- **Profondità**: `--sh-1`, `--sh-2`, `--sh-3` a strati morbidi, mai un'unica ombra grigia piatta.
- **Raggi**: 8 / 12 / 16 / 22 / 32 px e pill. Concentrici: un elemento dentro una card ha raggio = raggio card − padding.
- **Spazi**: scala da 4 pt (4…144 px), `--gutter clamp(16px, 4.2vw, 48px)`, `--maxw 1200px`.
- **Movimento**: `--ease-out cubic-bezier(.23,1,.32,1)`, `--ease-in-out cubic-bezier(.77,0,.175,1)`, `--ease-drawer cubic-bezier(.32,.72,0,1)`; durate 140 (pressione), 180, 240, 520, 1500 ms (hero).

### 4.2 Tipografia

- **Inter variabile**, ospitato in `/static/fonts/InterVariable.woff2` con `@font-face` (`font-display: swap`, `font-weight 100 900`), con fallback `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`. Licenza OFL in `static/fonts/Inter-LICENSE.txt`. Precaricato (`<link rel="preload" as="font" crossorigin>`) sulla landing e nelle pagine pubbliche.
- Scala del mockup: hero `clamp(3rem, 1rem + 5.6vw, 6.5rem)`, display, title1–3, lede, body 17 px, callout 15 px, footnote 13 px, caption 12 px.
- Tracking ottico: più stretto sui titoli grandi (fino a −0,045em), 0 sul testo. `font-feature-settings: "cv11", "ss01"` dove migliora la resa; numeri tabulari (`tnum`) in importi, date, conteggi e tabelle.
- Titoli con `text-wrap: balance`, paragrafi con `text-wrap: pretty`.

### 4.3 Tema scuro

- La landing è sempre chiara: è la dichiarazione del brand.
- Pagine pubbliche e dashboard: chiaro di default. Un interruttore nella shell passa al tema scuro.
- Memorizzazione: `localStorage['lumia:theme'] = 'light' | 'dark'`, applicata su `<html data-theme>` da `static/theme.js`. Lo script è caricato **senza `defer` nel `<head>`**, prima dei CSS, così non c'è un lampo di tema sbagliato. Le CSP vietano gli script inline: va in file esterno.
- Ogni token ha la versione scura in `html[data-theme="dark"]`, con contrasto AA verificato per testi, badge e grafici. In scuro le superfici si schiariscono salendo di livello, come su macOS.

### 4.4 Liquid Glass

Materiale per gli strati che galleggiano sopra i contenuti. Mai sui contenuti stessi (card di dati, tabelle, testi lunghi).

Dove:

- landing: barra di navigazione a pillola fluttuante; didascalie in vetro sopra i loghi delle piattaforme; cornice del dispositivo nella sezione "percorso";
- dashboard: barra superiore sticky, tab bar mobile, popover dell'account, palette ⌘K, card del tour guidato, toast, banner "aggiornamenti disponibili";
- controlli: segmented control (vista bacheca/elenco, filtri), pulsanti flottanti.

Come (classe `.glass` più varianti, in `base.css`):

1. Fondo tinto semitrasparente (chiaro `rgba(255,255,255,.62)`, scuro `rgba(30,30,32,.55)`) con `backdrop-filter: blur(20px) saturate(180%)`.
2. Bordo speculare: `inset 0 1px 0` bianco intenso in alto, `inset 0 -1px 0` tenue in basso, hairline esterna `rgba(0,0,0,.06)` e ombra `--sh-2`.
3. Riflesso: pseudo-elemento con gradiente radiale chiaro in alto a sinistra, `mix-blend-mode: plus-lighter` dove supportato.
4. Rifrazione (miglioramento progressivo): un filtro SVG `#lg-refract` (`feTurbulence` + `feDisplacementMap` leggeri) definito una sola volta per pagina dalla macro `glass_defs()` (SVG inline, consentito dalla CSP). Dichiarazione doppia: prima `backdrop-filter: blur() saturate()`, poi `backdrop-filter: url(#lg-refract) blur() saturate()`. Chrome ed Edge applicano la rifrazione; Safari e Firefox scartano la seconda riga e mantengono la prima.
5. Pressione: `transform: scale(.97)` in 140 ms con `--ease-out`; il riflesso si sposta verso il punto toccato solo con puntatore fine.
6. Accessibilità: con `prefers-reduced-transparency: reduce` o `prefers-contrast: more` il vetro diventa una superficie piena con bordo visibile. Il testo sul vetro resta sempre AA.
7. Prestazioni: al massimo 3 superfici di vetro visibili insieme. Niente `backdrop-filter` animato. Su schermi piccoli la sfocatura scende a 14 px.

### 4.5 Componenti condivisi (`base.css`)

Pulsanti (primario nero, accento, secondario grigio, ghost, distruttivo; piccolo, normale, grande; stato `disabled` e `aria-busy`), link testuali, input, textarea, select nativi stilizzati, checkbox e radio, badge di fase (macro `badge`), avatar (macro `avatar`), card/panel con intestazione, tabelle con numeri tabulari e versione a schede su telefono, stati vuoti, notice, demo banner, segmented control, pill, progress, `details/summary` (i glifi + e − passano nel template o in un'icona, non più nel CSS), dialoghi, toast, skip link, focus ring (2 px accento, offset 2 px, segue il raggio dell'elemento), `.sr-only`.

Regole sempre valide:

- `[hidden]` nasconde davvero: `[hidden]{display:none!important}` globale.
- Interazioni hover solo con `@media (hover:hover) and (pointer:fine)`.
- Target tattili ≥ 44 px.
- Solo `transform` e `opacity` nelle animazioni; `prefers-reduced-motion` ha sempre una versione statica curata.

### 4.6 Icone

`icon()` in `macros.html` mantiene nome, firma e output (`<svg class="icon …" aria-hidden="true">`) e tutti i nomi supportati. Il disegno passa a uno stile tipo SF Symbols: tratto 1,6, terminali arrotondati, griglia 24. Vanno aggiunti i nomi `sun` e `moon` (interruttore del tema) e, se servono, altri, senza rimuovere quelli esistenti.

## 5. Le aree

### 5.1 Landing

- Struttura del mockup Bianco: navigazione a pillola in vetro; hero con il marchio presentato come prodotto (la tessera nera con la "L" che sale e si posa con un riflesso morbido, luce del bordo che si accende una volta) e titolo enorme; servizi FiveM, Minecraft, Discord e web in una griglia bento con didascalie in vetro sopra i loghi; "Tre mondi. Un'unica visione."; il percorso in tre capitoli con racconto sticky su desktop; principi; FAQ; chiusura; footer.
- Stringhe e markup fissati dai test (vedi contract map §5 "Public"): `class="returning-client"` unica classe e prima di `href`; la sottostringa esatta `href="/ordina">Inizia il tuo progetto`; `Hai già un ordine in corso?`; `Vai all’area clienti` (apostrofo U+2019); `Il tuo prossimo server.`; `PayPal`.
- I link restano gli stessi (`/ordina`, `/ordina?platform=…`, `{{ manager_url }}/login`, `{{ discord_url }}`), così come gli anchor `#main`, `#servizi`, `#metodo`, `#domande`.
- `landing.js` viene riscritto e controlla l'esistenza di ogni elemento prima di usarlo. Movimento: ingresso del marchio con molla smorzata (una volta), luce che segue il puntatore solo su puntatore fine, capitoli del percorso attivati da IntersectionObserver o da `animation-timeline: view()` dove supportato. Tutto si ferma con `prefers-reduced-motion` e quando la scheda è nascosta.
- Solo immagini proprie o `data:`: la CSP del sito non ammette altro.

### 5.2 Richiesta guidata (`/start`)

- Layout Bianco: colonna centrale stretta, domanda grande per ogni passo, indicatore dei 6 passi, scelta della piattaforma come card con il logo (restano radio nativi nascosti visivamente ma accessibili), select nativi stilizzati, barra delle azioni in vetro fissa in basso su telefono.
- Restano tutti gli agganci di `intake.js` (contract map §3.2): 6 `fieldset[data-step]` con un `h2` ciascuno, gli id dei pulsanti, `#brief-error`, `#followups`, `#brief-summary`, `<dialog id=clear-dialog>`, gli attributi del `<body>`, i valori delle opzioni.
- Stati: anonimo (con `Non devi entrare nel server.`), connesso, demo, AI attiva o no, `<noscript>`, errori e invio in corso.

### 5.3 Accesso, errore, ritorno PayPal

Una card centrata con la tessera del marchio, titolo e azione principale, su fondo `--canvas-alt` con un bagliore ghiaccio appena accennato. `error.html` riceve solo `status` e `detail` e non estende layout che richiedono altre variabili. `paypal-return.html` mantiene il form con `data-paypal-capture`, il `<noscript>` e il link di ritorno.

### 5.4 Shell della dashboard

- Desktop: sidebar chiara (bianca su `--canvas-alt`) con marchio, ricerca ⌘K, navigazione con icone, contatori, sezione "Gestione" per lo staff, account in basso con interruttore del tema; contenuto a destra con barra superiore sticky in vetro (titolo della pagina, breadcrumb, azioni).
- Telefono: la sidebar sparisce; tab bar in vetro in basso con le 4–5 destinazioni principali per ruolo; ricerca e account nella barra superiore. Rispetta `safe-area-inset`.
- Restano: attributi del `<body>` (contract map §3.6), form di logout con `Esci dall’account` (unico csrf sulla home), `[data-workspace-updates]` e `.workspace-toast` (unici, partono `hidden`), `[data-command-open]` con `data-tour="search"`, `details.account-menu`, `#main` / `main.manager-main`, i valori `data-tour` della navigazione, titoli `… · Lumia`, il banner demo con `DEMO`, la notice `Riconciliazione richiesta`.
- Palette ⌘K e tour (dialogs.html): in vetro, con la geometria del tour richiesta da `workspace.js` (contract map §3.7). Il primo `input` della palette resta la ricerca; il primo `h2` del tour resta il titolo.

### 5.5 Progetto (cliente e staff)

Ispirato alla vista `#cliente` del mockup:

1. intestazione con breadcrumb, titolo (`.detail-title`), badge di fase e data prevista;
2. **card "Il prossimo passo"** in evidenza: è la `payment-callout` (`data-tour="payment"`), con importo grande e pulsante `Paga con PayPal · <importo>` (form nativo invariato) oppure, a seconda dello stato, il messaggio corrispondente nell'ordine di priorità fissato (contract map §3.11);
3. stepper delle 6 fasi (`order-journey.html`);
4. riepilogo pagato, residuo e consegna prevista;
5. piano di pagamento, milestone, movimenti, consegne, conversazione, supporto, cronologia, con tutti gli anchor (`#payment-plan`, `#milestones`, `#payments`, `#deliveries`, `#conversation`, `#support`, `#request-brief`, `#prepare-quote`);
6. per lo staff, gli strumenti di gestione (fase, milestone, tranche, storni, preventivo, consegne, nota interna) in pannelli ordinati e compatti, senza che il cliente li veda.

Restano tutti i form della tabella §3.11 della contract map, con gli stessi campi, condizioni e testi testati.

### 5.6 Home, progetti, bacheca (staff e cliente)

Ispirato alla vista `#manager` del mockup:

- **Home staff**: saluto e data, KPI (progetti attivi, incassato, da incassare, consegne in attesa) come `.metric-card` figli diretti di `section.dashboard-metrics[data-tour=summary]`, "Richiede attenzione", agenda breve, progetti recenti, code (`queues.html`), accesso rapido.
- **Home cliente**: in alto "Tocca a te" con le azioni che il cliente deve fare (preventivo da confermare, consegna da provare, tranche da pagare), poi i suoi progetti come card grandi e accessi al tutorial e a una nuova richiesta.
- **Progetti**: filtri (`.project-filter` con `q`, `stage`, `sort`), segmented control bacheca/elenco in vetro, preferiti, conteggio, bacheca a 4 colonne (Da definire, In lavorazione, In revisione, Completati) con card `article.workspace-project` complete di tutti gli attributi richiesti, ed elenco `order_table`.
- **Nuovo ordine** (staff): form in un pannello centrale (`.form-panel`).

### 5.7 Altre pagine

Attività (feed con `activity-item unread`), agenda (tessere calendario con giorno, mese e anno, scadenze passate evidenziate), clienti (`.customer-grid` di card), pagamenti (totali, registro con versione a schede su telefono, esportazione CSV, eventi e checkout PayPal per lo staff), impostazioni (`.settings-stack` di righe di stato), tutorial (8 capitoli, indice laterale `.tutorial-index`, avanzamento).

## 6. Architettura dei file statici

| File | Contenuto | Pagine |
|---|---|---|
| `base.css` | `@font-face`, token chiari e scuri, reset, tipografia, componenti condivisi, vetro, utilità | tutte |
| `site.css` | landing | landing |
| `auth.css` | login, errore, ritorno PayPal | quelle tre |
| `intake.css` | richiesta guidata | intake |
| `workspace.css` | shell, palette, tour, toast, componenti comuni della dashboard (intestazioni pagina, pannelli, griglie) | dashboard |
| `project.css` | pagina progetto e include | dashboard |
| `board.css` | home, bacheca, card progetto, code, nuovo ordine | dashboard |
| `pages.css` | attività, agenda, clienti, pagamenti, impostazioni | dashboard |
| `tutorial.css` | tutorial | dashboard, solo su `/tutorial` |
| `theme.js` | applica il tema salvato prima del rendering e gestisce `[data-theme-toggle]` | intake, auth, dashboard |

Tutti i link usano `?v=20261019` (stessa versione per i file nuovi o modificati). Ordine nella dashboard: `base.css`, `workspace.css`, `project.css`, `board.css`, `pages.css` (più `tutorial.css` sul tutorial); script `theme.js` nel `<head>` senza `defer`, poi `ui.js` e `workspace.js` con `defer` in quest'ordine.

## 7. Verifica

1. **Test**: `python -m unittest discover -s tests` deve dare 263 test OK.
2. **Browser reale con CSP**: l'app demo (`create_demo_app`) e il sito (`create_site_app`) girano in locale con i loro header di sicurezza. Uno script Puppeteer su Chrome visita ogni pagina come staff (`/`) e come cliente (`?view=client`) e raccoglie errori di console, eccezioni JS e violazioni CSP. Obiettivo: zero.
3. **Screenshot**: ogni pagina a 1440×900 e 390×844, in tema chiaro e scuro, con il tour chiuso. Revisione visiva contro il mockup.
4. **Interazioni**: palette ⌘K (apertura, filtro, frecce, Invio, Esc), tour (avanti, indietro, salta), preferiti, filtri e vista, wizard della richiesta (6 passi, riepilogo, bozza ripristinata), tutorial (8 capitoli), menu account, interruttore del tema.
5. **Revisione avversaria**: revisori indipendenti per contratti e agganci JS, accessibilità, mobile, tema scuro, CSP e prestazioni, qualità visiva. Ogni problema confermato viene corretto e riverificato.

## 8. Consegna

Commit sul branch `redesign/bianco`, PR verso `main` con screenshot e risultati delle verifiche. Il merge avvia il deploy automatico: niente merge senza l'approvazione del cliente. `STILE.txt` viene aggiornato con il nuovo sistema visivo.
