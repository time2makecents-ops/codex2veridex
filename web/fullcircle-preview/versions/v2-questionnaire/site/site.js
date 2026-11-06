(() => {
  'use strict';
  const menu = document.querySelector('.menu-toggle');
  const navigation = document.querySelector('#site-navigation');
  const setOpen = (open) => {
    menu.setAttribute('aria-expanded', String(open));
    navigation.dataset.open = String(open);
  };
  menu.addEventListener('click', () => setOpen(menu.getAttribute('aria-expanded') !== 'true'));
  navigation.addEventListener('click', (event) => {
    if (event.target.closest('a')) setOpen(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') {
      setOpen(false);
      menu.focus();
    }
  });
  const form = document.querySelector('#inquiry-form');
  const review = document.querySelector('#inquiry-review');
  const method = document.querySelector('#contact-method');
  const setContactMethod = () => {
    for (const kind of ['email', 'phone']) {
      const selected = method.value === kind;
      const input = document.querySelector('#contact-' + kind);
      document.querySelector('#' + kind + '-field').hidden = !selected;
      input.disabled = !selected;
      input.required = selected;
    }
  };
  method.addEventListener('change', setContactMethod);
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const summary = document.querySelector('#answer-summary');
    summary.replaceChildren();
    const rows = [
      ['Help with', 'help'], ['City', 'city'], ['Timing', 'timing'],
      ['Amount to sell', 'size'], ['Details', 'details'], ['Name', 'name'],
      [method.value === 'email' ? 'Email' : 'Phone', method.value]
    ];
    for (const [label, name] of rows) {
      const row = document.createElement('div');
      const term = document.createElement('dt');
      const answer = document.createElement('dd');
      term.textContent = label;
      answer.textContent = form.elements.namedItem(name).value.trim() || 'Not provided';
      row.append(term, answer);
      summary.append(row);
    }
    form.hidden = true;
    review.hidden = false;
    document.querySelector('#review-title').focus();
  });
  document.querySelector('#edit-answers').addEventListener('click', () => {
    review.hidden = true;
    form.hidden = false;
    document.querySelector('#sale-help').focus();
  });
  form.addEventListener('reset', () => {
    document.querySelector('#answer-summary').replaceChildren();
    requestAnimationFrame(setContactMethod);
  });
  // Preview only: no fetch, storage, submission endpoint or analytics.
  setContactMethod();
  form.hidden = false;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  if ('IntersectionObserver' in window && !reducedMotion.matches) {
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add('reveal-arrival');
          observer.unobserve(entry.target);
        }
      }
    }, { threshold: 0.08 });
    document.querySelectorAll('[data-reveal]').forEach((element) => observer.observe(element));
  }
})();
