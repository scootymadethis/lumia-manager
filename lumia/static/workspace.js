(() => {
  'use strict';
  const root = document.querySelector('.workspace');
  if (!root) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const staff = root.dataset.role === 'admin';
  const demo = root.dataset.demo === 'true';
  const scope = `${root.dataset.userId}:${root.dataset.role}`;
  const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (_) { return fallback; } };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (_) { return false; } };
  let toastTimer = 0;
  const toast = message => {
    const el = document.querySelector('.workspace-toast');
    clearTimeout(toastTimer);
    el.textContent = message;
    el.hidden = false;
    if (!reduced.matches) el.animate([{opacity: 0}, {opacity: 1}], {duration: 180, easing: 'ease-out'});
    toastTimer = setTimeout(() => el.hidden = true, 2400);
  };

  // Preferences affect presentation only. Permissions are always checked by the server.
  const favoritesKey = `lumia:favorites:${scope}`;
  const storedFavorites = read(favoritesKey, []);
  const favorites = new Set(Array.isArray(storedFavorites) ? storedFavorites.map(String).filter(value => /^\d+$/.test(value)) : []);
  let onlyFavorites = false;
  let liveQuery = document.querySelector('.project-filter [name="q"]')?.value.trim().toLocaleLowerCase('it') || '';
  let liveStage = document.querySelector('.project-filter [name="stage"]')?.value || '';
  const board = document.querySelector('[data-project-board]');
  const list = document.querySelector('[data-project-list]');
  const favoriteButtons = [...document.querySelectorAll('[data-favorite]')];
  const applyFavorites = () => {
    favoriteButtons.forEach(button => {
      const selected = favorites.has(button.dataset.favorite);
      button.setAttribute('aria-pressed', String(selected));
      const title = button.closest('.workspace-project').querySelector('h3').textContent;
      button.setAttribute('aria-label', `${selected ? 'Rimuovi' : 'Aggiungi'} ${title} ${selected ? 'dai' : 'ai'} preferiti`);
    });
    const matches = item => (!liveQuery || item.dataset.search.toLocaleLowerCase('it').includes(liveQuery)) && (!liveStage || item.dataset.stage === liveStage);
    document.querySelectorAll('[data-project-id]').forEach(card => card.hidden = (onlyFavorites && !favorites.has(card.dataset.projectId)) || !matches(card));
    list?.querySelectorAll('.project-row').forEach(row => {
      const id = new URL(row.href).pathname.match(/\/orders\/(\d+)/)?.[1];
      const card = board?.querySelector(`[data-project-id="${id}"]`);
      row.hidden = card ? card.hidden : onlyFavorites && !favorites.has(id);
    });
    board?.querySelectorAll('.board-column').forEach(column => {
      column.querySelector('.board-column-heading>span:last-child').textContent = column.querySelectorAll('[data-project-id]:not([hidden])').length;
    });
    const empty = document.querySelector('.favorites-empty');
    if (empty) empty.hidden = !onlyFavorites || !!board?.querySelector('[data-project-id]:not([hidden])');
    const count = document.querySelector('[data-project-count]');
    if (count) { const n = board.querySelectorAll('[data-project-id]:not([hidden])').length; count.textContent = `${n} ${n === 1 ? 'progetto trovato' : 'progetti trovati'}`; }
  };
  const filters = document.querySelector('.project-filter');
  filters?.querySelector('[name="q"]').addEventListener('input', event => {
    liveQuery = event.target.value.trim().toLocaleLowerCase('it');
    applyFavorites();
  });
  filters?.querySelector('[name="stage"]').addEventListener('change', event => {
    liveStage = event.target.value;
    applyFavorites();
  });
  filters?.querySelector('[name="sort"]').addEventListener('change', () => filters.requestSubmit());

  // Never overwrite an in-progress form when another person updates the project.
  const updateBanner = document.querySelector('[data-workspace-updates]');
  document.querySelector('[data-workspace-refresh]')?.addEventListener('click', () => location.reload());
  let pollTimer;
  let checking = false;
  const checkUpdates = async () => {
    if (demo || document.hidden || checking || !updateBanner.hidden) return;
    checking = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(`/workspace/version${location.search.includes('view=client') ? '?view=client' : ''}`, {signal: controller.signal, redirect: 'error'});
      if (response.ok && (await response.json()).version !== root.dataset.snapshot) updateBanner.hidden = false;
    } catch (_) { /* Keep the current workspace usable during a network outage. */ }
    finally { clearTimeout(timeout); checking = false; }
  };
  if (!demo) pollTimer = setInterval(checkUpdates, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) checkUpdates(); });
  addEventListener('pagehide', () => clearInterval(pollTimer));
  favoriteButtons.forEach(button => button.addEventListener('click', () => {
    const id = button.dataset.favorite;
    if (favorites.has(id)) favorites.delete(id); else favorites.add(id);
    const saved = write(favoritesKey, [...favorites]);
    applyFavorites();
    toast(saved ? (favorites.has(id) ? 'Aggiunto ai preferiti' : 'Rimosso dai preferiti') : 'Preferenza valida per questa pagina: lo spazio locale non è disponibile.');
  }));
  document.querySelector('[data-only-favorites]')?.addEventListener('click', event => {
    onlyFavorites = !onlyFavorites;
    event.currentTarget.setAttribute('aria-pressed', String(onlyFavorites));
    applyFavorites();
  });
  const setView = (value, animate = false) => {
    if (!board || !list) return;
    const mode = value === 'list' ? 'list' : 'board';
    board.hidden = mode !== 'board';
    list.hidden = mode !== 'list';
    document.querySelectorAll('[data-project-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.projectView === mode)));
    if (animate && !reduced.matches) (mode === 'board' ? board : list).animate([{opacity: .45}, {opacity: 1}], {duration: 180, easing: 'ease-out'});
  };
  setView(read(`lumia:view:${scope}`, 'board'));
  document.querySelectorAll('[data-project-view]').forEach(button => button.addEventListener('click', event => {
    setView(button.dataset.projectView, event.detail > 0);
    write(`lumia:view:${scope}`, button.dataset.projectView);
  }));
  applyFavorites();
  const customerSelect = document.querySelector('[data-customer-select]');
  const customerManual = document.querySelector('[data-customer-manual]');
  customerSelect?.addEventListener('change', () => { if (customerSelect.value) customerManual.value = ''; });
  customerManual?.addEventListener('input', () => { if (customerManual.value) customerSelect.value = ''; });

  const command = document.querySelector('.command-dialog');
  const search = command.querySelector('input');
  const commandItems = [...command.querySelectorAll('[data-command-item]')];
  const filterCommands = () => {
    const query = search.value.trim().toLocaleLowerCase('it');
    commandItems.forEach(item => item.hidden = !item.textContent.toLocaleLowerCase('it').includes(query));
    command.querySelector('.command-no-results').hidden = commandItems.some(item => !item.hidden);
  };
  const openCommand = animate => {
    if (guide.open) return;
    search.value = '';
    filterCommands();
    command.showModal();
    search.focus({preventScroll: true});
    if (animate && !reduced.matches) command.animate([{opacity: 0, transform: 'scale(.97)'}, {opacity: 1, transform: 'none'}], {duration: 180, easing: 'cubic-bezier(.23,1,.32,1)'});
  };
  document.querySelectorAll('[data-command-open]').forEach(button => button.addEventListener('click', event => openCommand(event.detail > 0)));
  command.querySelector('[data-command-close]').addEventListener('click', () => command.close());
  search.addEventListener('input', filterCommands);
  command.addEventListener('click', event => { if (event.target === command && event.clientX < command.getBoundingClientRect().left) command.close(); });
  command.addEventListener('keydown', event => {
    const items = commandItems.filter(item => !item.hidden);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const current = items.indexOf(document.activeElement);
      const next = event.key === 'ArrowDown' ? Math.min(current + 1, items.length - 1) : current - 1;
      if (next < 0) search.focus(); else items[next]?.focus();
    } else if (event.key === 'Enter' && event.target === search) {
      event.preventDefault();
      items[0]?.click();
    }
  });
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (command.open) command.close(); else openCommand(false);
    }
    if (event.key === 'Escape') document.querySelectorAll('.account-menu[open]').forEach(el => el.open = false);
  });
  document.addEventListener('pointerdown', event => {
    document.querySelectorAll('.account-menu[open]').forEach(el => { if (!el.contains(event.target)) el.open = false; });
  });

  // Guided waypoints use a native modal dialog: focus stays in the controls and
  // background actions cannot be triggered accidentally while a step is open.
  const guide = document.querySelector('.guide-dialog');
  const guideCard = guide.querySelector('.guide-card');
  const spotlight = guide.querySelector('.guide-spotlight');
  const title = guide.querySelector('h2');
  const description = guide.querySelector('#guide-description');
  const stepLabel = guide.querySelector('.guide-step');
  const nextButton = guide.querySelector('[data-guide-next]');
  const backButton = guide.querySelector('[data-guide-back]');
  const skipButton = guide.querySelector('[data-guide-skip]');
  const dots = guide.querySelector('.guide-dots');
  const tourVersion = staff ? 2 : 3;
  const tourKey = `lumia:tour:v${tourVersion}:${scope}`;
  const serverTour = {status: root.dataset.tourStatus, step: Number(root.dataset.tourStep), page: root.dataset.tourPage, version: Number(root.dataset.tourVersion)};
  let tour = serverTour.version === tourVersion && serverTour.status ? serverTour : read(tourKey, {});
  let index = -1;
  let steps = [];
  let saveQueue = Promise.resolve();
  const configs = {
    overview: [
      ['[data-tour="welcome"]', staff ? 'Il tuo centro operativo.' : 'Il tuo progetto parte da qui.', staff ? 'Qui trovi il lavoro aperto e puoi creare un nuovo ordine. Ogni progetto raccoglie messaggi, consegne, milestone e pagamenti.' : 'Questo è il tuo spazio con Lumia. Vedi soltanto i progetti associati al tuo account Discord.'],
      ['[data-tour="summary"]', 'I numeri che servono.', staff ? 'Progetti aperti, pagamenti ricevuti e residuo dei lavori confermati. Tocca un riepilogo per aprire i dettagli.' : 'Vedi i tuoi progetti attivi, quanto hai già pagato e quanto resta da saldare. Apri una voce per i dettagli.'],
      ['[data-tour="attention"] .panel-heading', staff ? 'Parti da ciò che richiede attenzione.' : 'Il tuo prossimo passo.', 'Preventivi, tranche disponibili e consegne da verificare vengono raccolti qui. Apri una voce per andare al progetto giusto.'],
      ['[data-tour="projects"] .workspace-section-heading', 'Un posto per ogni progetto.', 'Apri una card per parlare con il team, seguire le milestone e controllare le consegne. La stella salva i preferiti su questo browser.'],
      ['[data-tour="search"]', 'Trova. Apri. Continua.', 'Usa la ricerca per raggiungere una pagina o un progetto. Da tastiera puoi aprirla anche con Ctrl K o ⌘ K.'],
      ['[data-tour="nav-activity"]', 'Resta aggiornato.', staff ? 'Qui arrivano messaggi dei clienti, consegne e risposte. Le note interne rimangono visibili solo a Management.' : 'Qui ritrovi messaggi del team, consegne e risposte alle revisioni.'],
      ['[data-tour="nav-agenda"]', 'Le date, tutte insieme.', 'L’agenda raccoglie le tappe del progetto e le tranche con una data. Puoi riaprire questa guida dal menu account.'],
      ['[data-tour="nav-tutorial"]', 'Il percorso completo è sempre qui.', 'Il tutorial clienti spiega account, richieste, preventivi, PayPal, avanzamento, consegne e assistenza. Puoi fermarti e riprendere dall’ultimo capitolo su questo browser.']
    ],
    orders: [
      ['[data-tour="filters"]', 'Ritrova il progetto giusto.', 'Cerca per nome o numero LM e filtra per stato. Puoi scegliere le colonne o l’elenco.'],
      ['[data-project-board]', 'Il lavoro segue un percorso.', staff ? 'Le colonne separano preventivi, sviluppo, revisioni e progetti conclusi. Apri una scheda per gestire il lavoro.' : 'Le colonne separano preventivi, sviluppo, revisioni e progetti conclusi. Apri una scheda per seguire il lavoro o rispondere al team.'],
      ['[data-only-favorites]', 'Tieni vicini i progetti importanti.', 'Aggiungi una card ai preferiti con la stella, poi usa questo filtro. I preferiti vengono salvati per il tuo account su questo browser.']
    ],
    detail: [
      ['.detail-title', 'Tutto il progetto, in una pagina.', staff ? 'Qui trovi lo stato e tutti gli strumenti del progetto.' : 'Controlla stato e dettagli. Se il preventivo è pronto, leggi proposta e piano di pagamento, chiarisci i dubbi nella conversazione e poi usa Accetta preventivo.'],
      ['#request-brief .panel-heading','La tua idea, conservata qui.',staff ? 'La richiesta originale resta consultabile. Se serve un dettaglio in più, chiedilo nella conversazione del progetto.' : 'Qui ritrovi ciò che hai inviato dal sito. Il team ti proporrà prezzo e lavoro compreso prima di iniziare.'],
      ['#prepare-quote .panel-heading','Dal brief alla proposta.','Definisci importo, ambito e tempi concordati. Dopo l’invio il cliente può leggere e accettare il preventivo; puoi aggiungere un piano a tranche.'],
      ['[data-tour="payment"]', 'Il prossimo pagamento è qui.', 'Il riepilogo mostra l’importo disponibile. Dopo la conferma del preventivo puoi aprire PayPal: confermi tu ogni pagamento. Il saldo si aggiorna quando PayPal lo conferma; se è in attesa, controlla prima di riprovare.'],
      ['[data-tour="milestones"] .panel-heading', 'Segui le tappe concordate.', staff ? 'Aggiungi le date e completa le milestone quando il lavoro è pronto. Una tranche collegata diventa pagabile al completamento.' : 'Le milestone sono le tappe concordate. Il team aggiorna gli avanzamenti e l’agenda raccoglie le date.'],
      ['[data-tour="plan"] .panel-heading', 'Un piano chiaro.', staff ? 'Qui imposti le tranche, le date o le milestone di sblocco. Gli importi devono sommare al totale e, dopo la conferma, restano fissi.' : 'Qui vedi quanto è stato pagato e quali tranche restano. Si pagano in ordine quando diventano disponibili.'],
      ['[data-tour="deliveries"] .panel-heading', 'Le versioni da provare.', staff ? 'Pubblica un link HTTPS alla versione e spiega come verificarla. Il cliente può approvarla o richiedere modifiche.' : 'Apri una consegna, provala e poi approva o descrivi cosa va rivisto. La risposta viene conservata nel progetto.'],
      ['[data-tour="conversation"] .panel-heading', 'Parliamone nel progetto.', staff ? 'Scrivi al cliente oppure seleziona Nota interna per lasciare un appunto riservato a Management. Il cliente non vede le note interne.' : 'Scrivi domande e riscontri qui: la conversazione rimane collegata al progetto.'],
      ['#support .panel-heading', 'Se serve assistenza privata.', 'Entra nel server Discord e completa la verifica. Da questa sezione puoi descrivere il problema e aprire un ticket collegato al progetto, oppure riaprire quello esistente.']
    ],
    tutorial: [['.tutorial-index', 'Scegli il capitolo che ti serve.', 'Segui gli otto capitoli con Avanti e Indietro o scegli dall’indice. Il punto di lettura resta su questo browser. I collegamenti aprono le pagine: per accettare, pagare o inviare una risposta devi usare i rispettivi comandi.']],
    payments: [['[data-tour="ledger"]', 'Il registro dei pagamenti.', staff ? 'Qui trovi gli incassi registrati. Puoi esportare i movimenti in CSV. Il riepilogo non sostituisce una fattura.' : 'Qui vedi quanto hai pagato, il residuo e i movimenti registrati. Apri il progetto per la tranche disponibile; puoi anche esportare i movimenti.']],
    agenda: [['[data-tour="agenda"] .panel-heading', 'Una vista sulle prossime date.', 'Milestone e tranche datate restano collegate al progetto. Le date trascorse sono segnalate per aiutarti a verificarle.']],
    activity: [['[data-tour="activity"]', 'Riprendi il filo.', 'Apri un’attività per tornare alla conversazione o alla consegna. Segna come lette le attività già controllate.']],
    customers: [['.customer-grid', 'Le relazioni, ordinate.', 'Qui trovi i clienti con progetti registrati. Apri i loro progetti per consultare accordi, consegne e pagamenti.']],
    new: [['.form-panel', 'Partiamo dai dati essenziali.', 'Inserisci il cliente Discord, il titolo e l’importo del progetto. Potrai aggiungere milestone, consegne e un piano a tranche nei dettagli.']],
    settings: [['.settings-stack', 'Servizi e accessi.', 'Controlla gli indirizzi e la configurazione di PayPal. Le credenziali restano sul server; i permessi seguono i ruoli Discord.']]
  };
  const saveTour = status => {
    tour = {status, step: Math.max(0, index), page: root.dataset.page, version: tourVersion};
    write(tourKey, tour);
    if (demo) return;
    const body = new URLSearchParams({csrf: root.dataset.csrf, status, step: String(tour.step), page: tour.page});
    saveQueue = saveQueue.catch(() => {}).then(async () => {
      const response = await fetch('/preferences/tour', {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body, keepalive: true});
      if (!response.ok) throw new Error('Tour preference not saved');
    }).catch(() => {
      guide.querySelector('.guide-save-status').textContent = 'Progressi salvati su questo browser. Puoi riaprire la guida dal menu account.';
    });
  };
  const visible = element => !!element && element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden';
  const prepareSteps = () => {
    steps = (configs[root.dataset.page] || configs.overview).map(([selector, heading, copy]) => ({selector, heading, copy, target: document.querySelector(selector)})).filter(step => visible(step.target));
    if (!steps.length) steps = [{selector: '.page-heading', heading: 'Il tuo workspace.', copy: 'Apri un progetto dalla navigazione per trovare conversazioni, consegne e pagamenti.', target: document.querySelector('.page-heading') || document.querySelector('.manager-main')}];
  };
  const place = () => {
    if (!guide.open || index < 0) return;
    const target = steps[index]?.target;
    if (!visible(target)) return;
    const rect = target.getBoundingClientRect();
    const gap = 9;
    const x = Math.max(8, rect.left - gap);
    const y = Math.max(8, rect.top - gap);
    const w = Math.max(20, Math.min(rect.right + gap, innerWidth - 8) - x);
    const h = Math.max(20, Math.min(rect.bottom + gap, innerHeight - 8) - y);
    spotlight.style.left = `${x}px`; spotlight.style.top = `${y}px`;
    spotlight.style.width = `${w}px`; spotlight.style.height = `${h}px`;
    const box = guideCard.getBoundingClientRect();
    let top = y + h + 16;
    if (top + box.height > innerHeight - 16) top = y - box.height - 16;
    if (top < 16) top = Math.max(16, innerHeight - box.height - 20);
    const left = Math.max(16, Math.min(x, innerWidth - box.width - 16));
    guideCard.style.left = `${left}px`; guideCard.style.top = `${top}px`;
  };
  const showStep = (next, animate = false) => {
    index = Math.min(Math.max(0, next), steps.length - 1);
    const step = steps[index];
    guide.classList.remove('is-welcome');
    guide.querySelector('.guide-welcome-icon').hidden = true;
    spotlight.hidden = false;
    title.textContent = step.heading;
    description.textContent = step.copy;
    stepLabel.textContent = `Passaggio ${index + 1} di ${steps.length}`;
    nextButton.textContent = index === steps.length - 1 ? 'Ci sono!' : 'Avanti →';
    backButton.hidden = index === 0;
    skipButton.hidden = false;
    dots.hidden = false;
    dots.replaceChildren(...steps.map((_, i) => { const dot = document.createElement('i'); if (i <= index) dot.className = 'active'; return dot; }));
    const rect = step.target.getBoundingClientRect();
    if (rect.top < 85 || rect.bottom > innerHeight - 95) step.target.scrollIntoView({block: 'center', behavior: 'instant'});
    place();
    requestAnimationFrame(place);
    if (animate && !reduced.matches) [title, description].forEach(el => {
      el.getAnimations().forEach(animation => animation.cancel());
      el.animate([{opacity: .7}, {opacity: 1}], {duration: 160, easing: 'ease-out'});
    });
    nextButton.focus({preventScroll: true});
    saveTour('started');
  };
  const openGuide = () => {
    if (command.open) command.close();
    document.querySelectorAll('.account-menu[open]').forEach(el => el.open = false);
    prepareSteps();
    index = -1;
    guide.classList.add('is-welcome');
    guideCard.style.left = ''; guideCard.style.top = '';
    spotlight.hidden = true;
    guide.querySelector('.guide-welcome-icon').hidden = false;
    title.textContent = tour.status === 'started' && tour.page === root.dataset.page ? 'Riprendiamo da qui.' : (staff ? 'Il tuo nuovo centro operativo.' : 'Benvenuto nel tuo workspace.');
    description.textContent = staff ? 'Ti guido tra progetti, clienti, consegne e pagamenti. Puoi fermarti e riaprire la guida quando vuoi.' : 'Ti mostro i comandi di questa pagina. Per scoprire tutto il sito, apri il tutorial completo: otto capitoli dalla richiesta all’assistenza.';
    stepLabel.textContent = staff ? 'Lumia / Management' : 'Lumia / Area clienti';
    backButton.hidden = true; skipButton.hidden = false; dots.hidden = true;
    nextButton.textContent = tour.status === 'started' && tour.page === root.dataset.page ? 'Riprendi →' : 'Iniziamo →';
    guide.showModal();
    nextButton.focus({preventScroll: true});
  };
  const closeGuide = status => { saveTour(status); guide.close(); };
  document.querySelectorAll('[data-guide-open]').forEach(button => button.addEventListener('click', openGuide));
  nextButton.addEventListener('click', event => {
    if (index < 0) showStep(tour.status === 'started' && tour.page === root.dataset.page ? tour.step || 0 : 0, event.detail > 0);
    else if (index === steps.length - 1) { closeGuide('completed'); toast('Tutto pronto. La guida resta nel menu account.'); }
    else showStep(index + 1, event.detail > 0);
  });
  backButton.addEventListener('click', event => showStep(index - 1, event.detail > 0));
  skipButton.addEventListener('click', () => closeGuide(index >= 0 ? 'started' : 'skipped'));
  guide.querySelector('[data-guide-close]').addEventListener('click', () => closeGuide(index >= 0 ? 'started' : 'skipped'));
  guide.addEventListener('cancel', event => { event.preventDefault(); closeGuide(index >= 0 ? 'started' : 'skipped'); });
  addEventListener('resize', () => { if (guide.open) place(); }, {passive: true});
  addEventListener('scroll', () => { if (guide.open && index >= 0) place(); }, {passive: true});
  if (root.dataset.page !== 'tutorial' && (!tour.status || tour.version !== tourVersion)) requestAnimationFrame(openGuide);

  try {
    const key = `lumia:workspace-entry:${scope}`;
    if (!reduced.matches && !sessionStorage.getItem(key)) {
      const items = [...document.querySelectorAll('.workspace-welcome,.dashboard-metrics>.metric-card,.dashboard-grid>.panel')].slice(0, 6);
      items.forEach((el, i) => el.animate([{opacity: .25, transform: 'translateY(10px)'}, {opacity: 1, transform: 'none'}], {duration: 240, delay: i * 35, easing: 'cubic-bezier(.23,1,.32,1)'}));
      sessionStorage.setItem(key, '1');
    }
  } catch (_) { /* The complete interface remains available without web storage. */ }
})();
