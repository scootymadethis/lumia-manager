(() => {
  'use strict';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (!reduced.matches && 'IntersectionObserver' in window) {
    const reveals = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        entry.target.classList.remove('reveal-pending');
        reveals.unobserve(entry.target);
      }
    }, { threshold: .08, rootMargin: '0px 0px -40px 0px' });
    document.querySelectorAll('.landing .reveal').forEach(el => {
      el.classList.add('reveal-ready');
      if (el.getBoundingClientRect().top > window.innerHeight * .85) el.classList.add('reveal-pending');
      reveals.observe(el);
    });
    try {
      if (document.querySelector('.manager-main') && !document.querySelector('.workspace') && !sessionStorage.getItem('lumia-entered')) {
        document.querySelector('.manager-main').animate([{opacity: .2, transform: 'translateY(8px)'}, {opacity: 1, transform: 'none'}], {duration: 220, easing: 'cubic-bezier(.23,1,.32,1)'});
        sessionStorage.setItem('lumia-entered', '1');
      }
    } catch (_) { /* Storage can be unavailable in private browser policies. */ }
  }
  reduced.addEventListener('change', () => {
    if (reduced.matches) document.querySelectorAll('.reveal-pending').forEach(el => el.classList.remove('reveal-pending'));
  });
  const glows = document.querySelectorAll('.ambient');
  if ('IntersectionObserver' in window) {
    const visible = new IntersectionObserver(entries => entries.forEach(e => e.target.classList.toggle('is-paused', !e.isIntersecting)));
    glows.forEach(el => visible.observe(el));
  }
  document.addEventListener('visibilitychange', () => document.documentElement.classList.toggle('tab-hidden', document.hidden));
  const plan = document.querySelector('[data-plan-form]');
  if (plan) {
    const parts = plan.querySelector('[data-plan-parts]');
    const total = Number(plan.dataset.totalCents);
    const format = new Intl.NumberFormat('it-IT', {style: 'currency', currency: 'EUR'});
    const cents = value => /^\d+(?:[.,]\d{1,2})?$/.test(value.trim()) ? Math.round(Number(value.replace(',', '.')) * 100) : 0;
    const update = () => {
      const rows = [...parts.querySelectorAll('.plan-part')];
      let sum = 0;
      rows.forEach((row, index) => {
        row.querySelector('[data-part-label]').textContent = 'Tranche ' + (index + 1);
        row.querySelectorAll('[data-field]').forEach(input => input.name = `part_${index}_${input.dataset.field}`);
        row.querySelector('[data-remove-part]').disabled = rows.length === 1;
        sum += cents(row.querySelector('[data-field="amount"]').value);
      });
      plan.querySelector('[name="part_count"]').value = rows.length;
      plan.querySelector('[data-plan-total]').value = format.format(sum);
      plan.querySelector('.plan-total').dataset.invalid = String(sum !== total);
      plan.querySelector('[data-add-part]').disabled = rows.length >= 24;
    };
    plan.querySelector('[data-add-part]').addEventListener('click', () => {
      const fragment = plan.querySelector('template').content.cloneNode(true);
      parts.append(fragment);
      update();
      parts.lastElementChild.querySelector('input').focus();
    });
    parts.addEventListener('click', event => {
      const remove = event.target.closest('[data-remove-part]');
      if (remove && parts.children.length > 1) { remove.closest('.plan-part').remove(); update(); }
    });
    parts.addEventListener('input', update);
    parts.addEventListener('change', event => {
      const field = event.target.dataset.field;
      if (event.target.value && ['due', 'milestone'].includes(field)) {
        const other = field === 'due' ? 'milestone' : 'due';
        event.target.closest('.plan-part').querySelector(`[data-field="${other}"]`).value = '';
      }
      update();
    });
    update();
  }
  document.querySelectorAll('form[method="post"]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!form.checkValidity() || event.defaultPrevented) return;
      const button = event.submitter;
      if (!button) return;
      // The native submit includes any submitter value before the next task.
      window.setTimeout(() => { button.disabled = true; button.setAttribute('aria-busy', 'true'); }, 0);
    });
  });
  window.addEventListener('pageshow', () => document.querySelectorAll('[aria-busy="true"]').forEach(button => {
    button.disabled = false; button.removeAttribute('aria-busy');
  }));
})();
