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
