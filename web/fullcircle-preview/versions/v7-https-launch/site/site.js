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
  const sendButton = document.querySelector('#send-request');
  const sendStatus = document.querySelector('#send-status');
  const editButton = document.querySelector('#edit-answers');
  const retryConnection = document.querySelector('#retry-connection');
  const newRequest = document.querySelector('#new-request');
  let csrf = '';
  let sending = false;
  let accepted = false;
  const requestJson = async (options = {}) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch('contact.php', {credentials: 'same-origin', cache: 'no-store',
        ...options, signal: controller.signal});
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Unavailable');
      const body = await response.json();
      if (body.service !== 'fullcircle-contact-v1') throw new Error('Unavailable');
      return {response, body};
    } finally { clearTimeout(timeout); }
  };
  const connectContact = async () => {
    if (sending || accepted) return;
    csrf = '';
    sendButton.disabled = true;
    retryConnection.hidden = true;
    sendStatus.textContent = 'Checking the contact connection. Nothing has been sent.';
    try {
      const {response, body} = await requestJson();
      if (!response.ok || body.ready !== true || typeof body.csrf !== 'string' || !/^[a-f0-9]{64}$/.test(body.csrf)) throw new Error('Unavailable');
      csrf = body.csrf;
      sendButton.disabled = false;
      sendStatus.textContent = 'Review your answers, then choose Send consultation request.';
      document.querySelector('#contact-status').textContent = 'Your answers are emailed to Full Circle only when you choose Send consultation request.';
    } catch {
      sendStatus.textContent = 'This preview is not connected to email delivery. Nothing has been sent. You can email sales@estatesalesfullcircle.com directly.';
      retryConnection.hidden = false;
    }
  };
  retryConnection.addEventListener('click', connectContact);
  sendButton.addEventListener('click', async () => {
    if (sending || accepted || !csrf) return;
    const payload = Object.fromEntries(new FormData(form));
    payload.csrf = csrf;
    sending = true;
    sendButton.disabled = true;
    editButton.disabled = true;
    sendButton.textContent = 'Submitting…';
    sendStatus.textContent = 'Submitting your request. Please wait.';
    review.setAttribute('aria-busy', 'true');
    try {
      const {response, body} = await requestJson({method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      if (response.ok && body.accepted === true) {
        accepted = true;
        sendStatus.textContent = 'Your request has been submitted. Your preferred sale dates still need confirmation.';
        sendButton.textContent = 'Request submitted';
        editButton.hidden = true;
        newRequest.hidden = false;
      } else {
        sendStatus.textContent = body.message || 'We could not confirm submission. Your answers are still here; please try again or email us directly.';
        if (response.status === 403) { csrf = ''; retryConnection.hidden = false; }
      }
    } catch {
      sendStatus.textContent = 'We could not confirm submission. Your answers are still here. You can retry or email us directly.';
    } finally {
      sending = false;
      review.removeAttribute('aria-busy');
      if (!accepted) {
        sendButton.textContent = 'Send consultation request';
        sendButton.disabled = !csrf;
        editButton.disabled = false;
      }
    }
  });
  newRequest.addEventListener('click', () => {
    accepted = false;
    editButton.hidden = false;
    editButton.disabled = false;
    newRequest.hidden = true;
    sendButton.textContent = 'Send consultation request';
    form.reset();
    review.hidden = true;
    form.hidden = false;
    document.querySelector('#sale-help').focus();
    connectContact();
  });
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
  // Connection checks contain no answers. Answers are posted only on explicit Send.
  setContactMethod();
  setTiming();
  form.hidden = false;
  document.querySelectorAll('[data-preview-only]').forEach((element) => {
    element.hidden = !['127.0.0.1', 'localhost'].includes(location.hostname);
  });
  connectContact();
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
