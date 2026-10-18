(() => {
  'use strict';
  const form = document.querySelector('#brief-form');
  if (!form) return;
  const body = document.body, steps = [...form.querySelectorAll('[data-step]')];
  const nav = [...document.querySelectorAll('[data-step-to]')];
  const back = document.querySelector('#brief-back'), next = document.querySelector('#brief-next');
  const submit = document.querySelector('#brief-submit'), error = document.querySelector('#brief-error');
  const followups = document.querySelector('#followups'), summary = document.querySelector('#brief-summary');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const storageKey = 'lumia:brief:v1', ttl = 7 * 86400000;
  const names = ['platform','service','name','goal','features','technical','texts','style','budget','timeline','deadline'];
  const guided = {
    fivem: ['Partiamo da un server esistente? Quale framework e versione utilizzi?','Qual è il flusso che i giocatori devono poter completare?','Quali script, inventari o sistemi devono integrarsi?'],
    minecraft: ['Quale versione, software server e modalità di gioco utilizzi?','Che cosa devono poter fare i giocatori, dall’ingresso in poi?','Quali plugin esistenti e sistemi devono funzionare insieme?'],
    discord: ['Quali azioni vuoi automatizzare per utenti e staff?','Hai già un server, dei ruoli e un sistema di ticket?','Servono integrazioni con un sito o con il gioco?'],
    web: ['Chi userà il sito e quale azione deve riuscire a completare?','Quali pagine e integrazioni ti servono?','Hai già dominio, hosting, logo e contenuti?'],
    other: ['Chi utilizzerà il progetto?','Quali sono le tre funzioni indispensabili?','Hai già materiali o sistemi da integrare?']
  };
  let current = 0, reached = 0, key = crypto.randomUUID(), source = 'guided', pending, timer, sending = false;
  let questions = guided.other;
  function read() {
    const data = new FormData(form), result = {};
    names.forEach(name => { result[name] = String(data.get(name) || ''); });
    result.acknowledged = data.get('acknowledged') === 'on';
    result.answers = [...followups.querySelectorAll('textarea')].map((input,i) => ({question:questions[i],answer:input.value}));
    return result;
  }
  function save() {
    clearTimeout(timer);
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({at:Date.now(),current,reached,key,brief:read(),questions,source}));
      document.querySelector('#saved-state').textContent = 'Bozza salvata nella scheda';
    } catch { document.querySelector('#saved-state').textContent = 'Salvataggio locale non disponibile'; }
  }
  function setQuestions(list, answers = []) {
    questions = list.slice(0,3); followups.replaceChildren();
    questions.forEach((question,i) => {
      const label = document.createElement('label'), input = document.createElement('textarea');
      label.append(document.createTextNode(question));
      input.rows = 3; input.maxLength = 1000; input.name = `followup_${i}`;
      input.placeholder = 'Facoltativo · anche «da definire» va bene';
      input.value = answers.find(item => item.question === question)?.answer || '';
      label.append(input); followups.append(label);
    });
  }
  function field(name) { return form.elements.namedItem(name); }
  function clearError() { error.hidden = true; error.replaceChildren(); }
  function showError(message, reconnect = false) {
    error.textContent = message; error.hidden = false;
    if (reconnect) {
      const link = document.createElement('a'); link.href = '/auth/discord?customer=1&return=start';
      link.textContent = ' Accedi e riprendi la bozza.'; link.addEventListener('click',save); error.append(link);
    }
    error.focus();
  }
  function valid(index, focus = true) {
    const fields = [...steps[index].querySelectorAll('input,select,textarea')];
    field('deadline').required = field('timeline').value === 'date';
    for (const input of fields) {
      input.setCustomValidity('');
      if (input.required && input.type !== 'checkbox' && input.type !== 'radio' && !input.value.trim()) input.setCustomValidity('Completa questo campo.');
      if (input.minLength > 0 && input.value.trim().length < input.minLength) input.setCustomValidity(`Scrivi almeno ${input.minLength} caratteri.`);
      if (!input.checkValidity()) {
        if (focus) { input.focus(); input.reportValidity(); }
        return false;
      }
    }
    return true;
  }
  function summaryItem(label,text,index) {
    const row = document.createElement('div'), top = document.createElement('div');
    const heading = document.createElement('strong'), edit = document.createElement('button'), copy = document.createElement('p');
    row.className = 'brief-summary-item'; heading.textContent = label; copy.textContent = text || 'Da definire insieme';
    edit.type = 'button'; edit.className = 'text-link'; edit.textContent = 'Modifica'; edit.setAttribute('aria-label',`Modifica: ${label}`);
    edit.addEventListener('click',() => go(index)); top.append(heading,edit); row.append(top,copy); summary.append(row);
  }
  function selected(name) { return field(name).selectedOptions?.[0]?.textContent || ''; }
  function renderSummary() {
    const data = read(); summary.replaceChildren();
    summaryItem('Piattaforma',`${({fivem:'FiveM',minecraft:'Minecraft',discord:'Discord',web:'Web',other:'Altro'})[data.platform]} · ${selected('service')}`,0);
    summaryItem(data.name,data.goal,1); summaryItem('Funzioni richieste',data.features,1);
    summaryItem('Contesto tecnico',data.technical,2);
    data.answers.filter(item => item.answer.trim()).forEach(item => summaryItem(item.question,item.answer,2));
    summaryItem('Testi e contenuti',data.texts,3); summaryItem('Stile e riferimenti',data.style,3);
    summaryItem('Budget e tempi',`${selected('budget')}\n${selected('timeline')}${data.deadline ? '\n'+data.deadline : ''}`,4);
  }
  function go(index, focus = true) {
    if (sending) return;
    pending?.abort(); pending = null;
    if (index > current) {
      for (let i=0;i<index;i++) if (!valid(i,false)) { index=i; break; }
    }
    clearError(); const direction = index >= current ? 1 : -1;
    current = Math.max(0,Math.min(5,index)); reached = Math.max(reached,current);
    steps.forEach((step,i) => { step.hidden = i !== current; });
    nav.forEach((button,i) => { button.disabled = i > reached; if (i===current) button.setAttribute('aria-current','step'); else button.removeAttribute('aria-current'); });
    back.hidden = current===0; next.hidden = current===5; submit.hidden = current!==5;
    document.querySelector('#step-counter').textContent = `0${current+1} / 06`;
    document.querySelector('.brief-track span').style.transform = `scaleX(${(current+1)/6})`;
    document.querySelector('.brief-sculpture').style.setProperty('--phase',current);
    if (current===5) renderSummary();
    steps[current].getAnimations().forEach(animation => animation.cancel());
    if (!reduced.matches && focus) steps[current].animate([
      {opacity:0,transform:`translateX(${direction*14}px) rotateY(${direction*2}deg)`},
      {opacity:1,transform:'translateX(0) rotateY(0)'}
    ],{duration:280,easing:'cubic-bezier(.22,1,.36,1)'});
    if (focus) {
      const heading = steps[current].querySelector('h2'); heading.tabIndex=-1; heading.focus({preventScroll:true});
      const panel = document.querySelector('.brief-panel');
      if (panel.getBoundingClientRect().top<12) panel.scrollIntoView({behavior:reduced.matches?'instant':'smooth',block:'start'});
    }
    save();
  }
  setQuestions(guided.other);
  try {
    const cached = JSON.parse(sessionStorage.getItem(storageKey));
    if (cached && Date.now()-cached.at<ttl && typeof cached.brief==='object') {
      for (const name of names) {
        const input = field(name), value = String(cached.brief[name] || '').slice(0,2400);
        if (name==='platform') [...form.querySelectorAll('[name=platform]')].forEach(radio => {radio.checked=radio.value===value;});
        else input.value = value;
      }
      field('acknowledged').checked = cached.brief.acknowledged===true;
      key = /^[a-zA-Z0-9_-]{20,80}$/.test(cached.key) ? cached.key : key;
      reached = Number.isInteger(cached.reached) ? Math.max(0,Math.min(5,cached.reached)) : 0;
      current = Number.isInteger(cached.current) ? Math.max(0,Math.min(reached,cached.current)) : 0;
      const safe = Array.isArray(cached.questions) && cached.questions.length<=3 && cached.questions.every(q => typeof q==='string' && q.length<=240);
      source = cached.source==='local-ai' ? 'local-ai' : 'guided';
      setQuestions(safe?cached.questions:(guided[cached.brief.platform] || guided.other),Array.isArray(cached.brief.answers)?cached.brief.answers:[]);
      if (source==='local-ai') document.querySelector('#assistant-status').textContent='Approfondimenti suggeriti dall’AI locale. Controllali liberamente: sono facoltativi.';
    }
  } catch { /* A corrupt or blocked browser draft never blocks the form. */ }
  const requestedPlatform = new URL(location.href).searchParams.get('platform');
  if (!read().platform && guided[requestedPlatform]) {
    form.querySelector(`[name=platform][value="${requestedPlatform}"]`).checked=true;
    setQuestions(guided[requestedPlatform]);
  }
  // Never restore a later step when an earlier required answer is missing.
  for (let i=0;i<current;i++) if (!valid(i,false)) { current=i; reached=i; break; }
  go(current,false);
  next.addEventListener('click',() => { if (valid(current)) go(current+1); });
  back.addEventListener('click',() => go(current-1));
  nav.forEach(button => button.addEventListener('click',() => go(Number(button.dataset.stepTo))));
  form.addEventListener('input',event => {
    event.target.setCustomValidity?.(''); clearError();
    if (event.target.name==='platform') {
      pending?.abort(); source='guided';setQuestions(guided[read().platform] || guided.other);
      document.querySelector('#assistant-status').textContent='Tre spunti per aiutarci a capire il progetto. Sono facoltativi.';
    }
    clearTimeout(timer);timer=setTimeout(save,180);
  });
  document.querySelectorAll('[data-connect]').forEach(link => link.addEventListener('click',save));
  addEventListener('pagehide',save);
  async function responseJSON(response) {
    if (response.redirected || response.status===401 || response.status===403) throw new Error('SESSION');
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error(response.status===429?'Attendi prima di riprovare. Puoi continuare con le domande guidate.':'Richiesta non riuscita. Controlla i campi e riprova.');
    const result=await response.json();
    if (!response.ok) throw new Error(typeof result.detail==='string'?result.detail:'Richiesta non riuscita. Riprova.');
    return result;
  }
  document.querySelector('#ask-ai')?.addEventListener('click',async event => {
    const button=event.currentTarget, status=document.querySelector('#assistant-status');
    if (pending || sending) return;
    const controller=new AbortController(); pending=controller;
    const context=read(), signature=JSON.stringify([context.platform,context.goal,context.features,context.technical]);
    button.disabled=true;button.textContent='Sto approfondendo…';
    status.textContent='L’assistente locale sta leggendo il brief. Puoi proseguire mentre aspetti.';
    const timeout=setTimeout(() => controller.abort(),38000);
    try {
      const result=await responseJSON(await fetch('/requests/questions',{method:'POST',body:new URLSearchParams({csrf:body.dataset.csrf,brief:JSON.stringify(context)}),signal:controller.signal}));
      const now=read();
      if (current!==2 || signature!==JSON.stringify([now.platform,now.goal,now.features,now.technical])) return;
      if (result.source==='local-ai' && Array.isArray(result.questions)) {
        const answered=now.answers.filter(item=>item.answer.trim()).map(item=>item.question);
        const combined=[...new Set([...answered,...result.questions])].slice(0,3);
        source='local-ai'; setQuestions(combined,now.answers);
        status.textContent='Approfondimenti suggeriti dall’AI locale. Puoi rispondere, modificarli nel riepilogo o proseguire.';
      } else status.textContent='L’AI non è disponibile adesso. Le domande guidate sono già pronte: puoi continuare.';
      save();
    } catch (failure) {
      status.textContent='L’assistente non è disponibile adesso. Continua con le domande guidate.';
      if (failure.message==='SESSION') showError('La sessione è scaduta.',true);
    } finally { clearTimeout(timeout); if(pending===controller) pending=null;button.disabled=false;button.textContent='Approfondisci con AI locale'; }
  });
  form.addEventListener('submit',async event => {
    event.preventDefault();
    if(current!==5) {if(valid(current)) go(current+1);return;}
    if(sending || body.dataset.authenticated!=='true' || body.dataset.demo==='true') return;
    for(let i=0;i<6;i++) if(!valid(i,false)){go(i);valid(i);return;}
    save();sending=true;submit.disabled=true;submit.textContent='Invio della richiesta…';next.disabled=true;back.disabled=true;
    const controller=new AbortController(), timeout=setTimeout(() => controller.abort(),20000);
    try {
      const result=await responseJSON(await fetch('/requests',{method:'POST',body:new URLSearchParams({csrf:body.dataset.csrf,submission:key,brief:JSON.stringify(read())}),signal:controller.signal}));
      if(!/^\/orders\/\d+\?submitted=1$/.test(result.url)) throw new Error('Risposta non valida. Riprova.');
      removeEventListener('pagehide',save);clearTimeout(timer);try{sessionStorage.removeItem(storageKey);}catch{}
      location.assign(result.url);
    } catch(failure) {
      showError(failure.message==='SESSION'?'La sessione è scaduta.':failure.name==='AbortError'?'La conferma sta impiegando più tempo. Riprova: la stessa richiesta non sarà duplicata.':failure.message,failure.message==='SESSION');
      sending=false;submit.disabled=false;submit.textContent='Invia richiesta →';next.disabled=false;back.disabled=false;
    } finally {clearTimeout(timeout);}
  });
  const dialog=document.querySelector('#clear-dialog');
  document.querySelector('#clear-brief').addEventListener('click',() => {if(!sending)dialog.showModal();});
  document.querySelector('[data-clear-cancel]').addEventListener('click',() => dialog.close());
  document.querySelector('[data-clear-confirm]').addEventListener('click',() => {
    pending?.abort();form.reset();key=crypto.randomUUID();reached=0;source='guided';setQuestions(guided.other);dialog.close();go(0);
  });
})();
