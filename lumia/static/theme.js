// Applies the saved theme before first paint and wires [data-theme-toggle] buttons.
(() => {
  const root = document.documentElement;
  const read = () => { try { return localStorage.getItem('lumia:theme'); } catch { return null; } };
  // The browser chrome follows the theme: the page's own light value, black in dark.
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.dataset.light = meta.content;
  const apply = theme => {
    root.dataset.theme = theme === 'dark' ? 'dark' : 'light';
    if (meta) meta.content = root.dataset.theme === 'dark' ? '#000000' : meta.dataset.light;
  };
  apply(read());
  if (navigator.userAgentData) root.classList.add('lg-refract'); // Only Chromium renders SVG refraction in backdrop-filter; others keep the plain blur.
  document.addEventListener('DOMContentLoaded', () => {
    const sync = () => document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      // The label names the action and flips with it, like the visible text;
      // no aria-pressed, which would contradict it ("Usa il tema chiaro, premuto").
      button.setAttribute('aria-label', root.dataset.theme === 'dark' ? 'Usa il tema chiaro' : 'Usa il tema scuro');
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
