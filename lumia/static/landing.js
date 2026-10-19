if (navigator.userAgentData) document.documentElement.classList.add("lg-refract");
// Lumia landing: the hero mark's pointer tilt, the light on the service cards,
// the converging worlds and the sticky journey. Every hook is optional, and all
// motion stops under prefers-reduced-motion and while the tab is hidden.
(() => {
  const root = document.documentElement;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const fine = matchMedia('(hover: hover) and (pointer: fine)');
  const wide = matchMedia('(min-width: 981px)');
  const observe = 'IntersectionObserver' in window;
  const onVisible = [];

  // A hidden tab pauses every CSS animation (site.css) and every frame loop.
  const syncHidden = () => {
    root.classList.toggle('tab-hidden', document.hidden);
    onVisible.forEach(fn => fn());
  };
  document.addEventListener('visibilitychange', syncHidden);
  root.classList.toggle('tab-hidden', document.hidden);

  // Over the bento three glass captions are on screen: the bar turns solid (spec §4.4.7).
  const nav = document.querySelector('[data-site-nav]');
  const bento = document.querySelector('[data-bento]');
  if (nav && bento && observe) {
    new IntersectionObserver(([entry]) => nav.classList.toggle('is-quiet', entry.isIntersecting)).observe(bento);
  }

  // Hero: the tile leans toward a fine pointer on a critically damped spring.
  const hero = document.querySelector('[data-hero]');
  const tilt = document.querySelector('[data-tilt]');
  const refl = document.querySelector('[data-tilt-refl]');
  const spec = document.querySelector('[data-tilt-spec]');
  if (hero && tilt) {
    const K = 140, C = 2 * Math.sqrt(K); // damping ratio 1: no overshoot
    const s = { x: 0, y: 0, vx: 0, vy: 0, tx: 0, ty: 0 };
    let raf = 0, last = 0, inView = true;
    const paint = () => {
      const rx = (-s.y * 9).toFixed(3), ry = (s.x * 13).toFixed(3);
      tilt.style.transform = `rotateX(${rx}deg) rotateY(${ry}deg)`;
      if (refl) refl.style.transform = `rotateX(${-rx}deg) rotateY(${ry}deg)`;
      if (spec) spec.style.transform = `translate3d(${(s.x * -22).toFixed(2)}%, ${(s.y * -22).toFixed(2)}%, 0)`;
    };
    const step = t => {
      const dt = Math.min((t - last) / 1000, 1 / 30);
      last = t;
      s.vx += ((s.tx - s.x) * K - s.vx * C) * dt; s.x += s.vx * dt;
      s.vy += ((s.ty - s.y) * K - s.vy * C) * dt; s.y += s.vy * dt;
      paint();
      const settled = Math.abs(s.tx - s.x) < 1e-3 && Math.abs(s.ty - s.y) < 1e-3 && Math.abs(s.vx) < 1e-3 && Math.abs(s.vy) < 1e-3;
      raf = settled ? 0 : requestAnimationFrame(step);
    };
    const kick = () => {
      if (raf || document.hidden || reduce.matches) return;
      last = performance.now();
      raf = requestAnimationFrame(step);
    };
    const stop = () => { cancelAnimationFrame(raf); raf = 0; };
    const rest = () => { s.tx = 0; s.ty = 0; kick(); };
    window.addEventListener('pointermove', event => {
      if (!inView || event.pointerType === 'touch' || !fine.matches || reduce.matches) return;
      const box = tilt.getBoundingClientRect();
      s.tx = Math.max(-1, Math.min(1, (event.clientX - box.left - box.width / 2) / (innerWidth / 2)));
      s.ty = Math.max(-1, Math.min(1, (event.clientY - box.top - box.height / 2) / (innerHeight / 2)));
      kick();
    }, { passive: true });
    root.addEventListener('pointerleave', rest);
    if (observe) {
      new IntersectionObserver(([entry]) => {
        inView = entry.isIntersecting;
        if (!inView) rest();
      }).observe(hero);
    }
    onVisible.push(() => (document.hidden ? stop() : kick()));
    reduce.addEventListener('change', () => {
      if (!reduce.matches) return;
      stop();
      Object.assign(s, { x: 0, y: 0, vx: 0, vy: 0, tx: 0, ty: 0 });
      paint();
    });
  }

  // Services: a soft light follows a fine pointer across each card.
  document.querySelectorAll('[data-service]').forEach(card => {
    const light = card.querySelector('.service-light');
    if (!light) return;
    const move = event => {
      const box = card.getBoundingClientRect();
      light.style.transform = `translate3d(${(event.clientX - box.left - 280).toFixed(1)}px, ${(event.clientY - box.top - 280).toFixed(1)}px, 0)`;
    };
    card.addEventListener('pointerenter', event => {
      if (event.pointerType === 'touch' || !fine.matches || reduce.matches) return;
      move(event);
      card.classList.add('is-lit');
    });
    card.addEventListener('pointermove', event => { if (card.classList.contains('is-lit')) move(event); });
    card.addEventListener('pointerleave', () => card.classList.remove('is-lit'));
  });

  // Three worlds converge on the mark once, the first time they scroll in.
  const worlds = document.querySelector('[data-worlds]');
  const worldsArt = worlds && worlds.querySelector('.worlds-art');
  if (worldsArt && observe && !reduce.matches && worldsArt.getBoundingClientRect().top > innerHeight) {
    worlds.classList.add('is-armed');
    const io = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      worlds.classList.add('is-in');
      io.disconnect();
    }, { threshold: 0.5 });
    io.observe(worldsArt);
  }

  // Journey: on desktop the chapter in the middle of the viewport drives the device.
  const story = document.querySelector('[data-story]');
  if (story && observe) {
    const steps = [...story.querySelectorAll('[data-step]')];
    const cards = [...story.querySelectorAll('[data-card]')];
    const dots = [...story.querySelectorAll('.stage-dots span')];
    const show = n => {
      steps.forEach(item => item.classList.toggle('is-active', Number(item.dataset.step) === n));
      cards.forEach(card => {
        const k = Number(card.dataset.card);
        card.classList.toggle('is-active', k === n);
        card.classList.toggle('is-before', k < n);
      });
      dots.forEach((dot, i) => dot.classList.toggle('is-on', i === n));
    };
    const io = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) show(Number(entry.target.dataset.step));
    }), { rootMargin: '-45% 0px -45% 0px' });
    const sync = () => {
      story.classList.toggle('is-live', wide.matches);
      io.disconnect();
      if (wide.matches) steps.forEach(item => io.observe(item));
    };
    wide.addEventListener('change', sync);
    sync();
  }
})();
