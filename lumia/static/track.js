// First-party analytics: page views, clicks, reading depth and the request steps.
// No cookies and no storage; typed text and field values are never read.
// Honors Global Privacy Control and Do Not Track. Disabled in the demo.
(() => {
  'use strict';
  const body = document.body;
  if (!body || body.dataset.demo === 'true' || navigator.globalPrivacyControl || navigator.doNotTrack === '1' || !navigator.sendBeacon) return;
  const view = Array.from(crypto.getRandomValues(new Uint8Array(8)), b => b.toString(16).padStart(2, '0')).join('');
  const path = location.pathname;
  const queue = [];
  let timer = 0, depth = 0, active = 0, since = document.hidden ? 0 : performance.now();

  const flush = () => {
    clearTimeout(timer); timer = 0;
    while (queue.length) {
      const batch = queue.splice(0, 40);
      navigator.sendBeacon('/_t', new Blob([JSON.stringify({events: batch})], {type: 'text/plain'}));
    }
  };
  const push = event => {
    queue.push({view, path, ...event});
    if (queue.length >= 20) flush();
    else if (!timer) timer = setTimeout(flush, 4000);
  };
  const clean = text => (text || '').replace(/\s+/g, ' ').trim().slice(0, 120);

  const params = new URLSearchParams(location.search);
  const referrer = document.referrer && new URL(document.referrer).host !== location.host ? document.referrer : '';
  push({kind: 'view', ref: referrer, w: innerWidth,
    utm_source: params.get('utm_source') || '', utm_medium: params.get('utm_medium') || '', utm_campaign: params.get('utm_campaign') || ''});

  // Clicks: the control that was hit, named by what a person reads on it.
  document.addEventListener('click', event => {
    const el = event.target instanceof Element && event.target.closest('a,button,summary,label,select,[role="button"],[data-track]');
    if (!el || el.closest('[data-track-ignore]')) return;
    if (event.target.matches('input') && el.matches('label')) return; // the label's own click was already counted
    const heading = el.matches('a,button') && el.querySelector('strong,h2,h3');
    const label = el.closest('[data-private]') ? '•••' : clean(el.dataset.track || el.getAttribute('aria-label') || (heading && heading.innerText) || (el.matches('select') ? '' : el.innerText) || el.getAttribute('title') || el.getAttribute('name'));
    const href = el.getAttribute('href');
    const target = href ? href.split('?')[0].slice(0, 300) : el.id ? '#' + el.id : el.tagName.toLowerCase() + (el.getAttribute('type') ? `[${el.getAttribute('type')}]` : '');
    const doc = document.documentElement;
    push({kind: 'click', label, target, x: event.pageX / Math.max(doc.scrollWidth, 1), y: event.pageY / Math.max(doc.scrollHeight, 1)});
    if (href && !href.startsWith('#')) flush(); // the page is about to go away
  }, {capture: true, passive: true});

  // Reading depth, and which sections actually came on screen.
  const measure = () => {
    const doc = document.documentElement;
    depth = Math.max(depth, Math.min(1, (scrollY + innerHeight) / Math.max(doc.scrollHeight, 1)));
  };
  addEventListener('scroll', measure, {passive: true});
  measure();
  const sections = [...document.querySelectorAll('main section[id], main section[aria-labelledby], [data-track-section]')]
    .filter((el, i, all) => !all.some(other => other !== el && other.contains(el)))
    .slice(0, 30)
    .map(el => {
      const heading = el.getAttribute('aria-labelledby') && document.getElementById(el.getAttribute('aria-labelledby'));
      return {el, id: el.dataset.trackSection || el.id || el.getAttribute('aria-labelledby'), label: clean((heading || el.querySelector('h1,h2,h3') || {}).innerText).slice(0, 80), seen: false};
    });
  if (sections.length && 'IntersectionObserver' in window) {
    const watch = new IntersectionObserver(entries => entries.forEach(entry => {
      const part = sections.find(item => item.el === entry.target);
      if (entry.isIntersecting && part) { part.seen = true; watch.unobserve(entry.target); }
    }), {threshold: 0.35});
    sections.forEach(part => watch.observe(part.el));
  }

  // The request form announces its steps; intake.js dispatches 'lumia:track'.
  document.addEventListener('lumia:track', event => {
    const detail = event.detail || {};
    if (detail.kind === 'step') push({kind: 'step', label: clean(detail.label).slice(0, 60), value: Number(detail.value) || 0});
  });

  const leave = () => {
    if (since) active += performance.now() - since;
    since = 0;
    push({kind: 'leave', value: Math.round(active / 100) / 10, y: Math.round(depth * 1000) / 1000,
      sections: sections.map(({id, label, seen}) => ({id, label, seen}))});
    flush();
  };
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) leave();
    else since = performance.now();
  });
  addEventListener('pagehide', () => { if (since) leave(); });
})();
