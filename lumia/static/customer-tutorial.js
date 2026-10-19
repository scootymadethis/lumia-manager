(() => {
  'use strict';
  const tutorial = document.querySelector('[data-customer-tutorial]');
  if (!tutorial) return;
  const root = document.querySelector('.workspace');
  const chapters = [...tutorial.querySelectorAll('[data-tutorial-chapter]')];
  const jumps = [...tutorial.querySelectorAll('[data-tutorial-jump]')];
  const next = tutorial.querySelector('[data-tutorial-next]');
  const back = tutorial.querySelector('[data-tutorial-back]');
  const status = tutorial.querySelector('[data-tutorial-status]');
  const complete = tutorial.querySelector('[data-tutorial-complete]');
  const key = `lumia:customer-tutorial:v1:${root.dataset.userId}:${root.dataset.role}:${root.dataset.demo}`;
  let state = {chapter: 0, completed: false};
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    if (saved && Number.isInteger(saved.chapter) && saved.chapter >= 0 && saved.chapter < chapters.length) {
      state = {chapter: saved.chapter, completed: saved.completed === true};
    }
  } catch (_) { /* Navigation also works when browser storage is unavailable. */ }
  const save = () => {
    try {
      localStorage.setItem(key, JSON.stringify(state));
      status.textContent = state.completed ? 'Hai completato il percorso. Puoi rileggere i capitoli quando vuoi.' : 'Punto di lettura salvato su questo browser.';
    } catch (_) {
      status.textContent = 'Puoi continuare a leggere. Questo browser non consente di salvare il punto di lettura.';
    }
  };
  const show = (chapter, focus = false) => {
    state.chapter = Math.max(0, Math.min(chapters.length - 1, chapter));
    chapters.forEach((section, index) => { section.hidden = index !== state.chapter; });
    jumps.forEach((link, index) => {
      if (index === state.chapter) link.setAttribute('aria-current', 'step');
      else link.removeAttribute('aria-current');
    });
    back.disabled = state.chapter === 0;
    next.textContent = state.chapter === chapters.length - 1 ? 'Concludi il tutorial ✓' : 'Avanti →';
    next.hidden = state.completed && state.chapter === chapters.length - 1;
    complete.hidden = !state.completed;
    tutorial.querySelector('[data-tutorial-position]').textContent = `Capitolo ${state.chapter + 1} di ${chapters.length}`;
    tutorial.querySelector('[data-tutorial-progress]').value = state.chapter + 1;
    save();
    if (focus) chapters[state.chapter].querySelector('h2').focus();
  };
  jumps.forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    show(Number(link.dataset.tutorialJump), true);
  }));
  back.addEventListener('click', () => show(state.chapter - 1, true));
  next.addEventListener('click', () => {
    if (state.chapter === chapters.length - 1) {
      state.completed = true;
      show(state.chapter);
      complete.querySelector('a').focus();
    } else show(state.chapter + 1, true);
  });
  tutorial.querySelector('[data-tutorial-restart]').addEventListener('click', () => {
    state.completed = false;
    show(0, true);
  });
  tutorial.querySelectorAll('[data-tutorial-controls]').forEach(element => { element.hidden = false; });
  const linked = chapters.findIndex(chapter => `#${chapter.id}` === location.hash);
  show(linked < 0 ? state.chapter : linked);
})();
