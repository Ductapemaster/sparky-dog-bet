/* Bet page client logic.
 *
 * Loaded once (deferred) via bet.html's {% block head %} so it survives the
 * inline-reveal swap of the <main> content. initBetPage() wires up whichever
 * widgets are present in the current DOM and is safe to call repeatedly (it
 * no-ops on already-bound nodes / rebinds freshly-swapped ones).
 *
 * Data that used to be inlined by Jinja (guest names, breeds) is now read from
 * <script type="application/json"> tags in the markup, since this file is static.
 */
(function () {
  'use strict';

  // Colloquial / spelling aliases so casual searches surface the right breed.
  // Aliases only affect filtering — the value saved is always the canonical name.
  var BREED_ALIASES = {
    "Pit Bull (Am Staff / Pit Bull Terrier)":
      "pitbull pittie staffy staff amstaff american staffordshire terrier american pit bull terrier"
  };

  var BREEDS = [];
  var BREEDS_LOWER = [];

  function readJSON(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  // ── Generic combobox helper for a single breed input ──────────────────────
  function makeBreedCombo(input) {
    var listbox = input.nextElementSibling;
    var errorEl = input.closest('.breed-row').querySelector('.breed-error');
    var activeIdx = -1;

    function getOpts() { return listbox.querySelectorAll('[role=option]'); }

    function renderOpts(q) {
      var ql = q.toLowerCase();
      var filtered = q.length
        ? BREEDS.filter(function (b) {
            var hay = (b + ' ' + (BREED_ALIASES[b] || '')).toLowerCase();
            return hay.indexOf(ql) !== -1;
          })
        : BREEDS;
      listbox.innerHTML = '';
      activeIdx = -1;
      filtered.forEach(function (name) {
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', 'false');
        li.textContent = name;
        li.addEventListener('mousedown', function (e) { e.preventDefault(); });
        li.addEventListener('click', function () { pick(name); });
        listbox.appendChild(li);
      });
    }

    function pick(name) {
      input.value = name;
      input.dataset.valid = 'true';
      if (errorEl) errorEl.hidden = true;
      input.classList.remove('breed-invalid');
      close();
      updateFormState();
    }

    function open() { renderOpts(input.value); listbox.hidden = false; }
    function close() { listbox.hidden = true; activeIdx = -1; }

    function validateOnBlur() {
      var val = input.value.trim();
      if (val && BREEDS_LOWER.indexOf(val.toLowerCase()) !== -1) {
        input.dataset.valid = 'true';
        input.classList.remove('breed-invalid');
        if (errorEl) errorEl.hidden = true;
      } else if (val) {
        input.dataset.valid = 'false';
        input.classList.add('breed-invalid');
        if (errorEl) errorEl.hidden = false;
      } else {
        input.dataset.valid = 'false';
        input.classList.remove('breed-invalid');
        if (errorEl) errorEl.hidden = true;
      }
      updateFormState();
    }

    function highlight(idx) {
      var opts = getOpts();
      if (!opts.length) return;
      opts.forEach(function (o) { o.setAttribute('aria-selected', 'false'); o.classList.remove('active'); });
      activeIdx = Math.max(0, Math.min(idx, opts.length - 1));
      opts[activeIdx].setAttribute('aria-selected', 'true');
      opts[activeIdx].classList.add('active');
      opts[activeIdx].scrollIntoView({ block: 'nearest' });
    }

    input.addEventListener('focus', open);
    input.addEventListener('click', function () { if (listbox.hidden) open(); });
    input.addEventListener('blur', function () { close(); validateOnBlur(); });
    input.addEventListener('input', function () {
      input.dataset.valid = 'false';
      input.classList.remove('breed-invalid');
      if (errorEl) errorEl.hidden = true;
      open();
      updateFormState();
    });

    input.addEventListener('keydown', function (e) {
      var opts = getOpts();
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (listbox.hidden) open();
        highlight(activeIdx < 0 ? 0 : activeIdx + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        highlight(activeIdx <= 0 ? 0 : activeIdx - 1);
      } else if (e.key === 'Enter' && !listbox.hidden && activeIdx >= 0 && opts[activeIdx]) {
        e.preventDefault();
        pick(opts[activeIdx].textContent);
      } else if (e.key === 'Escape') {
        close();
      } else if (e.key === 'Tab' && !listbox.hidden && activeIdx >= 0 && opts[activeIdx]) {
        pick(opts[activeIdx].textContent);
      }
    });
  }

  function updateRemoveButtons() {
    var btns = document.querySelectorAll('.btn-remove');
    var show = btns.length > 1;
    btns.forEach(function (b) { b.style.display = show ? '' : 'none'; });
  }

  // Exposed globally because the breed-form markup uses inline on* handlers.
  function addRow() {
    var container = document.getElementById('breed-rows');
    var row = document.createElement('div');
    row.className = 'breed-row';

    var col = document.createElement('div');
    col.className = 'breed-col';

    var wrap = document.createElement('div');
    wrap.className = 'autocomplete-wrap';
    var inp = document.createElement('input');
    inp.type = 'text'; inp.name = 'breed[]'; inp.required = true;
    inp.className = 'breed-combo'; inp.autocomplete = 'off';
    inp.placeholder = 'Start typing a breed…';
    inp.dataset.valid = 'false';
    var ul = document.createElement('ul');
    ul.setAttribute('role', 'listbox');
    ul.className = 'combo-listbox';
    ul.hidden = true;
    wrap.appendChild(inp);
    wrap.appendChild(ul);
    col.appendChild(wrap);

    var errDiv = document.createElement('div');
    errDiv.className = 'breed-error';
    errDiv.hidden = true;
    errDiv.textContent = 'Please select a breed from the list.';
    col.appendChild(errDiv);
    row.appendChild(col);

    var controls = document.createElement('div');
    controls.className = 'breed-controls';

    var pct = document.createElement('input');
    pct.type = 'number'; pct.name = 'percentage[]'; pct.className = 'breed-pct';
    pct.placeholder = '%'; pct.min = '1'; pct.max = '99'; pct.required = true;
    pct.setAttribute('inputmode', 'numeric');
    pct.setAttribute('oninput', 'updateFormState()');
    controls.appendChild(pct);

    var btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'btn-remove'; btn.textContent = '×';
    btn.setAttribute('onclick', 'removeRow(this)');
    controls.appendChild(btn);
    row.appendChild(controls);

    container.appendChild(row);
    makeBreedCombo(inp);
    inp.focus();
    updateTotal();
    updateRemoveButtons();
  }

  function removeRow(btn) {
    if (document.querySelectorAll('.breed-row').length > 1) {
      btn.closest('.breed-row').remove();
      updateFormState();
      updateRemoveButtons();
    }
  }

  function updateFormState() {
    var total = 0;
    document.querySelectorAll('input[name="percentage[]"]').forEach(function (i) {
      total += parseInt(i.value) || 0;
    });
    var bar = document.getElementById('total-bar');
    if (!bar) return;
    document.getElementById('total-display').textContent = total + '%';
    bar.className = 'total-bar ' + (total === 100 ? 'total-ok' : 'total-bad');
    var allBreedsValid = true;
    document.querySelectorAll('.breed-combo').forEach(function (inp) {
      if (inp.dataset.valid !== 'true') allBreedsValid = false;
    });
    document.getElementById('btn-submit').disabled = (total !== 100 || !allBreedsValid);
  }

  function updateTotal() { updateFormState(); }

  // ── Breed form (the actual bet) ───────────────────────────────────────────
  function initBreedForm() {
    var form = document.getElementById('bet-form');
    if (!form || form.dataset.betBound) return;
    form.dataset.betBound = '1';

    var data = readJSON('breeds-data');
    if (data) {
      BREEDS = data;
      BREEDS_LOWER = BREEDS.map(function (b) { return b.toLowerCase(); });
    }

    updateTotal();
    updateRemoveButtons();
    document.querySelectorAll('.breed-combo').forEach(makeBreedCombo);

    function showSubmitError(msg) {
      var card = form.closest('.card') || form.parentNode;
      var el   = card.querySelector('.alert');
      if (!el) {
        el = document.createElement('div');
        el.className = 'alert alert-error';
        form.parentNode.insertBefore(el, form);
      }
      el.textContent = msg;
    }

    form.addEventListener('submit', function (e) {
      var btn     = document.getElementById('btn-submit');
      var label   = document.getElementById('btn-submit-label');
      var spinner = document.getElementById('btn-submit-spinner');
      btn.disabled          = true;
      label.textContent     = 'Submitting…';
      spinner.style.display = '';

      // Submit via fetch and swap in the result, so a bet/edit never leaves the
      // betting card. Falls back to a normal navigation on network/JS failure.
      e.preventDefault();
      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'fetch' }
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data && data.ok && data.next) return swapBet(data.next);
          showSubmitError((data && data.error) || 'Could not submit your bet. Please try again.');
          spinner.style.display = 'none';
          var editing = !!form.querySelector('input[name="editing"]');
          label.textContent = editing ? 'Update My Bet' : 'Submit My Bet';
          updateFormState();
        })
        .catch(function () {
          form.dataset.betBound = '';
          form.submit();
        });
    });
  }

  // ── Name lookup combobox (login screen) ───────────────────────────────────
  function initNameCombo() {
    var input   = document.getElementById('name');
    if (!input || input.dataset.nameBound) return;
    input.dataset.nameBound = '1';

    var NAMES   = readJSON('names-data') || [];
    var listbox = document.getElementById('name-listbox');
    var activeIdx = -1;

    function getOpts() { return listbox.querySelectorAll('[role=option]'); }

    function renderOpts(q) {
      var filtered = q.length
        ? NAMES.filter(function (n) { return n.toLowerCase().indexOf(q.toLowerCase()) !== -1; })
        : NAMES;
      listbox.innerHTML = '';
      activeIdx = -1;
      input.setAttribute('aria-activedescendant', '');
      filtered.forEach(function (name, i) {
        var li = document.createElement('li');
        li.id = 'nopt-' + i;
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', 'false');
        li.textContent = name;
        li.addEventListener('mousedown', function (e) { e.preventDefault(); });
        li.addEventListener('click', function () { pick(name); });
        listbox.appendChild(li);
      });
    }

    function open() {
      renderOpts(input.value);
      listbox.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    }
    function close() {
      listbox.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.setAttribute('aria-activedescendant', '');
      activeIdx = -1;
    }
    function pick(name) { input.value = name; close(); }

    function highlight(idx) {
      var opts = getOpts();
      if (!opts.length) return;
      opts.forEach(function (o) { o.setAttribute('aria-selected', 'false'); o.classList.remove('active'); });
      activeIdx = Math.max(0, Math.min(idx, opts.length - 1));
      opts[activeIdx].setAttribute('aria-selected', 'true');
      opts[activeIdx].classList.add('active');
      input.setAttribute('aria-activedescendant', opts[activeIdx].id);
      opts[activeIdx].scrollIntoView({ block: 'nearest' });
    }

    input.addEventListener('blur', close);
    input.addEventListener('input', function () {
      if (this.value.length) { renderOpts(this.value); listbox.hidden = false; input.setAttribute('aria-expanded', 'true'); }
      else close();
    });

    input.addEventListener('keydown', function (e) {
      var opts = getOpts();
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (listbox.hidden) open();
        highlight(activeIdx < 0 ? 0 : activeIdx + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        highlight(activeIdx <= 0 ? 0 : activeIdx - 1);
      } else if (e.key === 'Enter' && !listbox.hidden && activeIdx >= 0 && opts[activeIdx]) {
        e.preventDefault();
        pick(opts[activeIdx].textContent);
      } else if (e.key === 'Escape') {
        close();
      } else if (e.key === 'Tab' && !listbox.hidden && activeIdx >= 0 && opts[activeIdx]) {
        pick(opts[activeIdx].textContent);
      }
    });

    input.addEventListener('focus', function () {
      setTimeout(function () { input.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }, 350);
    });

    if (input.value) { renderOpts(input.value); listbox.hidden = false; input.setAttribute('aria-expanded', 'true'); }
  }

  // ── Kiosk gas-pump countdowns (thank-you / auto-logout buttons) ────────────
  function initKioskCountdown() {
    document.querySelectorAll('[data-countdown-href]').forEach(function (btn) {
      if (btn.dataset.countdownBound) return;
      btn.dataset.countdownBound = '1';
      var secs  = parseInt(btn.dataset.countdownSeconds || '10', 10);
      var href  = btn.dataset.countdownHref;
      var label = btn.dataset.countdownLabel || btn.textContent.trim();
      var left  = secs;
      function render() { btn.textContent = label + ' (' + left + ')'; }
      render();
      var iv = setInterval(function () {
        left -= 1;
        if (left <= 0) { clearInterval(iv); window.location.href = href; return; }
        render();
      }, 1000);
    });
  }

  // ── Inline reveal: verify on the login screen via AJAX, then morph <main> ──
  function initLoginAjax() {
    var form = document.getElementById('verify-form');
    if (!form || form.dataset.ajaxBound) return;
    form.dataset.ajaxBound = '1';

    function showError(msg) {
      var el = form.parentNode.querySelector('.alert');
      if (!el) {
        el = document.createElement('div');
        el.className = 'alert alert-error';
        form.parentNode.insertBefore(el, form);
      }
      el.textContent = msg;
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var submitBtn = form.querySelector('button[type=submit]');
      if (submitBtn) submitBtn.disabled = true;

      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'fetch' }
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data && data.ok) return swapToBet();
          if (submitBtn) submitBtn.disabled = false;
          showError((data && data.error) || 'Could not verify. Please try again.');
        })
        .catch(function () {
          // Network/JS failure — fall back to a normal full-page submit.
          form.dataset.ajaxBound = '';
          form.submit();
        });
    });
  }

  // Fetch a bet-flow URL and swap its <main> into the current page (no navigation),
  // then re-wire the freshly-injected widgets. Falls back to a real navigation if
  // the response doesn't contain a <main> we can graft in.
  function swapMain(url) {
    return fetch(url, { headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var nm  = doc.querySelector('main.main');
        var cur = document.querySelector('main.main');
        if (nm && cur) {
          cur.innerHTML = nm.innerHTML;
          initBetPage();
          window.scrollTo(0, 0);
        } else {
          window.location.href = url;
        }
      })
      .catch(function () { window.location.href = url; });
  }

  // Swap ONLY the right column (#bet-panel) so the persistent two-column shell —
  // rules in the left column — stays put and never re-renders. If the response
  // has no #bet-panel (the full-width "Bet locked in" confirmation), fall back to
  // swapping all of <main> so that state can take over the screen.
  function swapPanel(url) {
    return fetch(url, { headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var np  = doc.querySelector('#bet-panel');
        var cp  = document.querySelector('#bet-panel');
        if (np && cp) {
          cp.innerHTML = np.innerHTML;
          initBetPage();
          window.scrollTo(0, 0);
          return;
        }
        var nm  = doc.querySelector('main.main');
        var cur = document.querySelector('main.main');
        if (nm && cur) { cur.innerHTML = nm.innerHTML; initBetPage(); window.scrollTo(0, 0); }
        else { window.location.href = url; }
      })
      .catch(function () { window.location.href = url; });
  }

  // Pick the swap strategy by viewport: wide screens (kiosk + desktop) replace
  // only the right panel; narrow screens keep the existing full-<main> swap.
  function swapBet(url) {
    return window.matchMedia('(min-width: 900px)').matches ? swapPanel(url) : swapMain(url);
  }
  function swapToBet() { return swapBet('/bet'); }

  // Links flagged data-inline-nav (Edit My Bet, Cancel) swap in place instead of
  // navigating, so the whole bet/edit flow stays on the one "betting card".
  function initInlineNav() {
    if (document.body.dataset.inlineNavBound) return;
    document.body.dataset.inlineNavBound = '1';
    document.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('a[data-inline-nav]');
      if (!a) return;
      e.preventDefault();
      swapBet(a.getAttribute('href'));
    });
  }

  // Wire up every widget present in the current DOM. Safe to call repeatedly.
  function initBetPage() {
    initNameCombo();
    initBreedForm();
    initKioskCountdown();
    initLoginAjax();
    initInlineNav();
  }

  // Inline on* handlers in the breed-form markup call these by global name.
  window.addRow          = addRow;
  window.removeRow       = removeRow;
  window.updateFormState = updateFormState;
  window.updateTotal     = updateTotal;
  window.initBetPage     = initBetPage;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBetPage);
  } else {
    initBetPage();
  }
})();
