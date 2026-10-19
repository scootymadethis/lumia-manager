/* Marketing motion only. Native scrolling, no scroll interception or dependencies. */
(() => {
  'use strict';
  const landing = document.querySelector('.landing');
  if (!landing) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const precise = matchMedia('(hover: hover) and (pointer: fine)');
  const journey = document.querySelector('.journey');
  const display = document.querySelector('[data-journey-display]');
  const chapters = [...document.querySelectorAll('[data-chapter]')];
  const scenes = [...document.querySelectorAll('[data-scene]')];
  const bar = document.querySelector('.journey-progress i');
  const hero = document.querySelector('[data-hero-object]');
  const aura = document.querySelector('.cursor-aura');
  const cards = [...document.querySelectorAll('[data-tilt]')];
  const heroSequence = document.querySelector('[data-hero-sequence]');
  const heroTitle = document.querySelector('[data-hero-title]');
  const ecosystem = document.querySelector('[data-ecosystem]');
  const network = document.querySelector('[data-network]');
  const nodes = [...document.querySelectorAll('[data-network-node]')];
  const networkTrack = document.querySelector('.ecosystem-track>span');
  const networkOrbit = document.querySelector('.network-orbit.orbit-a');
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const smooth = value => value * value * (3 - 2 * value);
  let frame = 0;
  let last = 0;
  let scrollDirty = true;
  let storyStart = 0;
  let storyTravel = 1;
  let heroTop = 0;
  let heroHeight = 1;
  let enhanced = false;
  let heroPinned = false;
  let heroStart = 0;
  let heroTravel = 1;
  let ecosystemStart = 0;
  let ecosystemTravel = 1;
  let networkWidth = 1000;
  let activeCard = null;
  let pointerSeen = false;
  let pointer = {x: 0, y: 0};
  let tilt = {x: 0, y: 0, vx: 0, vy: 0};
  let targetTilt = {x: 0, y: 0};
  let shinePoint = {x: 0, y: 0};
  let cardBounds = null;
  const canPoint = () => precise.matches && !reduced.matches;
  // Unit mass, stiffness 100, damping 10: velocity survives every retarget.
  const spring = (value, velocity, target, dt) => {
    velocity += ((target - value) * 100 - velocity * 10) * dt;
    value += velocity * dt;
    return [value, velocity];
  };
  const requestFrame = () => {
    if (!frame && !document.hidden) frame = requestAnimationFrame(render);
  };
  const resetStory = () => {
    chapters.forEach(el => { el.style.opacity = ''; el.style.transform = ''; });
    scenes.forEach(el => { el.style.opacity = ''; el.style.transform = ''; });
    display.style.transform = '';
    bar.style.transform = '';
  };
  const measure = () => {
    enhanced = !reduced.matches && innerHeight >= (innerWidth <= 760 ? 790 : 760);
    heroPinned = !reduced.matches && innerWidth > 1000 && innerHeight >= 900;
    heroSequence.classList.toggle('is-cinematic', heroPinned);
    ecosystem.classList.toggle('is-cinematic', enhanced);
    const header = innerWidth <= 760 ? 68 : 76;
    heroStart = heroSequence.getBoundingClientRect().top + scrollY - header;
    heroTravel = Math.max(1, heroSequence.offsetHeight - heroSequence.querySelector('.site-hero').offsetHeight);
    ecosystemStart = ecosystem.getBoundingClientRect().top + scrollY - header;
    ecosystemTravel = Math.max(1, ecosystem.offsetHeight - ecosystem.querySelector('.ecosystem-sticky').offsetHeight);
    networkWidth = network.clientWidth;
    journey.classList.toggle('is-enhanced', enhanced);
    resetStory();
    const rect = journey.getBoundingClientRect();
    const sticky = journey.querySelector('.journey-sticky');
    const stickyTop = innerWidth <= 760 ? 68 : 76;
    storyStart = rect.top + scrollY - stickyTop;
    storyTravel = Math.max(1, journey.offsetHeight - sticky.offsetHeight);
    const heroRect = document.querySelector('.hero-object').getBoundingClientRect();
    heroTop = heroRect.top + scrollY;
    heroHeight = heroRect.height;
    cardBounds = activeCard?.getBoundingClientRect() || null;
    scrollDirty = true;
    requestFrame();
  };
  const renderScroll = () => {
    if (enhanced) {
      const progress = clamp((scrollY - storyStart) / storyTravel, 0, 1);
      // Hold each chapter for reading; crossfade through the intervening quarter.
      const phase = progress * 2;
      const weights = [
        1 - smooth(clamp((phase - .55) / .45, 0, 1)),
        smooth(clamp((phase - .55) / .45, 0, 1)) * (1 - smooth(clamp((phase - 1.55) / .45, 0, 1))),
        smooth(clamp((phase - 1.55) / .45, 0, 1))
      ];
      chapters.forEach((el, index) => {
        el.style.opacity = weights[index].toFixed(3);
        el.style.transform = `translate3d(0,${((1 - weights[index]) * 18).toFixed(2)}px,0)`;
      });
      scenes.forEach((el, index) => {
        el.style.opacity = weights[index].toFixed(3);
        const direction = phase > index ? -1 : 1;
        el.style.transform = `translate3d(0,${(direction * (1 - weights[index]) * 24).toFixed(2)}px,0) rotateX(${(direction * (1 - weights[index]) * 6).toFixed(2)}deg)`;
      });
      const amplitude = innerWidth <= 760 ? .45 : 1;
      display.style.transform = `rotateY(${((progress - .5) * 24 * amplitude).toFixed(2)}deg) rotateX(${(Math.sin(progress * Math.PI * 2) * 7 * amplitude).toFixed(2)}deg) rotateZ(${((progress - .5) * -5 * amplitude).toFixed(2)}deg)`;
      bar.style.transform = `scaleX(${progress.toFixed(4)})`;
    }
    if (!reduced.matches) {
      const progress = heroPinned ? clamp((scrollY - heroStart) / heroTravel,0,1) : clamp((scrollY - heroTop + innerHeight * .65) / (heroHeight + innerHeight * .4), 0, 1);
      const scale = innerWidth <= 350 ? .6 : innerWidth <= 420 ? .7 : innerWidth <= 760 ? .8 : 1;
      hero.style.transform = `translate3d(0,${(-progress * 20).toFixed(2)}px,0) rotateX(${(24 - progress * 35).toFixed(2)}deg) rotateY(${(-24 + progress * 70).toFixed(2)}deg) rotateZ(${(-9 + progress * 18).toFixed(2)}deg) scale(${(scale*(1+progress*.12)).toFixed(3)})`;
      heroTitle.style.transform = heroPinned ? `translate3d(0,${(-progress*14).toFixed(2)}px,0) scale(${(1-progress*.045).toFixed(3)})` : '';
      const netProgress = enhanced ? clamp((scrollY-ecosystemStart)/ecosystemTravel,0,1) : clamp((scrollY-ecosystemStart+innerHeight*.65)/(ecosystem.offsetHeight+innerHeight*.3),0,1);
      const spread = smooth(clamp(netProgress*1.5,0,1));
      const distance = Math.min(networkWidth*.31,310);
      const mobile = innerWidth<=760;
      const positions = [[-distance,-(mobile?53:60)],[distance,-(mobile?53:60)],[0,mobile?80:110]];
      nodes.forEach((node,i)=>{
        const [x,y] = positions[i];
        node.style.transform = `translate3d(${(x*(.14+spread*.86)).toFixed(2)}px,${(y*(.2+spread*.8)).toFixed(2)}px,${(100-spread*50).toFixed(2)}px) rotateY(${((i===0?1:i===1?-1:0)*(30-spread*18)).toFixed(2)}deg) rotateZ(${((i-1)*(1-spread)*16).toFixed(2)}deg) scale(${(.75+spread*.25).toFixed(3)})`;
        node.style.opacity = (.3+spread*.7).toFixed(3);
      });
      networkOrbit.style.transform = `rotateX(${(68-netProgress*10).toFixed(2)}deg) rotateZ(${(-18+netProgress*100).toFixed(2)}deg)`;
      networkTrack.style.transform = `scaleX(${netProgress.toFixed(4)})`;
    } else {
      hero.style.transform = ''; heroTitle.style.transform = '';
      nodes.forEach(node=>{node.style.transform='';node.style.opacity=''});
      networkOrbit.style.transform='';networkTrack.style.transform='';
    }
  };
  function render(now) {
    frame = 0;
    if (document.hidden) { last = 0; return; }
    const dt = Math.min((now - (last || now - 16)) / 1000, .032);
    last = now;
    if (scrollDirty) { renderScroll(); scrollDirty = false; }
    let unsettled = false;
    if (activeCard && canPoint()) {
      [tilt.x, tilt.vx] = spring(tilt.x, tilt.vx, targetTilt.x, dt);
      [tilt.y, tilt.vy] = spring(tilt.y, tilt.vy, targetTilt.y, dt);
      activeCard.style.transform = `rotateX(${tilt.x.toFixed(3)}deg) rotateY(${tilt.y.toFixed(3)}deg)`;
      const shine = activeCard.querySelector('.card-shine');
      shine.style.transform = `translate3d(${(shinePoint.x - 215).toFixed(2)}px,${(shinePoint.y - 215).toFixed(2)}px,0)`;
      const moving = Math.abs(tilt.x - targetTilt.x) + Math.abs(tilt.y - targetTilt.y) + Math.abs(tilt.vx) + Math.abs(tilt.vy) > .02;
      unsettled ||= moving;
      if (!moving && targetTilt.x === 0 && targetTilt.y === 0 && !activeCard.matches(':hover')) {
        activeCard.style.transform = '';
        activeCard = null;
      }
    }
    if (unsettled) requestFrame();
    else last = 0;
  }
  document.addEventListener('pointermove', event => {
    if (!canPoint() || event.pointerType === 'touch') return;
    pointer = {x: event.clientX, y: event.clientY};
    // Pointer coordinates are applied directly: no interpolation or spring lag.
    aura.firstElementChild.style.transform = `translate3d(${pointer.x - 290}px,${pointer.y - 290}px,0)`;
    pointerSeen = true;
    aura.classList.add('is-visible');
    if (activeCard && cardBounds && activeCard.matches(':hover')) {
      const x = clamp((event.clientX - cardBounds.left) / cardBounds.width, 0, 1);
      const y = clamp((event.clientY - cardBounds.top) / cardBounds.height, 0, 1);
      targetTilt = {x: (y - .5) * -14, y: (x - .5) * 14};
      shinePoint = {x: x * cardBounds.width, y: y * cardBounds.height};
    }
    requestFrame();
  }, {passive: true});
  cards.forEach(card => {
    card.addEventListener('pointerenter', event => {
      if (!canPoint() || event.pointerType === 'touch') return;
      if (activeCard && activeCard !== card) activeCard.style.transform = '';
      activeCard = card;
      cardBounds = card.getBoundingClientRect();
      tilt = {x: 0, y: 0, vx: 0, vy: 0};
      targetTilt = {x: 0, y: 0};
    });
    card.addEventListener('pointerleave', () => { targetTilt = {x: 0, y: 0}; requestFrame(); });
  });
  document.documentElement.addEventListener('pointerleave', () => {
    aura.classList.remove('is-visible');
    pointerSeen = false;
    targetTilt = {x: 0, y: 0};
    requestFrame();
  });
  addEventListener('scroll', () => {
    scrollDirty = true;
    // Stop tilting while the surface moves underneath the cursor.
    targetTilt = {x: 0, y: 0};
    requestFrame();
  }, {passive: true});
  addEventListener('resize', measure, {passive: true});
  addEventListener('pageshow', measure);
  document.addEventListener('visibilitychange', () => {
    last = 0;
    if (document.hidden) { cancelAnimationFrame(frame); frame = 0; }
    else { scrollDirty = true; requestFrame(); }
  });
  const preferenceChange = () => {
    if (!canPoint()) {
      aura.classList.remove('is-visible');
      aura.firstElementChild.style.transform = '';
      pointerSeen = false;
      cards.forEach(card => card.style.transform = '');
      activeCard = null;
    }
    measure();
  };
  reduced.addEventListener('change', preferenceChange);
  precise.addEventListener('change', preferenceChange);
  if ('IntersectionObserver' in window) {
    const visibility = new IntersectionObserver(entries=>entries.forEach(entry=>entry.target.classList.toggle('is-paused',!entry.isIntersecting)));
    visibility.observe(ecosystem);
  }
  measure();
})();
