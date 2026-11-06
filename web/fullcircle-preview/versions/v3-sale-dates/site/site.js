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
  const timing = document.querySelector('#sale-timing');
  const saleDate = document.querySelector('#sale-date');
  const saleStart = document.querySelector('#sale-start');
  const saleEnd = document.querySelector('#sale-end');
  const validateDateRange = () => {
    saleEnd.min = saleStart.value;
    const reversed = timing.value === 'date-range' && saleStart.value && saleEnd.value && saleEnd.value < saleStart.value;
    saleEnd.setCustomValidity(reversed ? 'Choose an end date on or after the start date.' : '');
  };
  const setTiming = () => {
    const single = timing.value === 'specific-date';
    const range = timing.value === 'date-range';
    document.querySelector('#sale-date-options').hidden = !(single || range);
    for (const [input, field, enabled] of [
      [saleDate, 'single-date-field', single],
      [saleStart, 'start-date-field', range],
      [saleEnd, 'end-date-field', range]
    ]) {
      document.querySelector('#' + field).hidden = !enabled;
      input.disabled = !enabled;
      input.required = enabled;
    }
    validateDateRange();
  };
  timing.addEventListener('change', setTiming);
  saleStart.addEventListener('input', validateDateRange);
  saleEnd.addEventListener('input', validateDateRange);
  const readableDate = (value) => new Date(value + 'T12:00:00').toLocaleDateString(undefined, {
    year: 'numeric', month: 'long', day: 'numeric'
  });
  const timingAnswer = () => {
    if (timing.value === 'specific-date') return readableDate(saleDate.value);
    if (timing.value === 'date-range') return readableDate(saleStart.value) + ' – ' + readableDate(saleEnd.value);
    return timing.value;
  };
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
      answer.textContent = (name === 'timing' ? timingAnswer() : form.elements.namedItem(name).value.trim()) || 'Not provided';
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
    requestAnimationFrame(() => { setContactMethod(); setTiming(); });
  });
  // Preview only: no fetch, storage, submission endpoint or analytics.
  setContactMethod();
  setTiming();
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
