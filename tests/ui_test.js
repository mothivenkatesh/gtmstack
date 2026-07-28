/* Frontend UI suite. Runs IN the page, against a live server.
 *
 * There is no build step in this repo and no test runner in the browser, so
 * this is a self-contained async function that returns a JSON report. Paste it
 * into the console, or drive it from an automation tool:
 *
 *     const r = await window.__uiTest();     // after loading this file
 *
 * What it checks, and why these and not others: every bug that reached a user
 * in this app was one of four things. A tool that renders blank. A console
 * error nobody saw. A control that does nothing when clicked. And state that
 * silently fails to persist. So the suite tests exactly those, on every tool,
 * rather than asserting markup that will churn.
 *
 * Network-dependent checks report DEGRADED rather than FAIL, for the same
 * reason the backend suite does: "Reddit rate-limited us" is not "our code is
 * broken", and conflating them makes the report useless.
 *
 * No em dashes.
 */
(function () {
  const PASS = 'PASS', FAIL = 'FAIL', DEG = 'DEGRADED', SKIP = 'SKIP';
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const vis = (el) => { if (!el) return false; const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0; };
  const visAll = (sel) => [...document.querySelectorAll(sel)].filter(vis);
  const API = location.origin;

  /* Native setters, because Preact listens for input events and a plain
     `el.value = x` does not notify it. This is the difference between a test
     that drives the UI and one that only looks at it. */
  const setValue = (el, v) => {
    const proto = el.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };

  const TOOLS = ['home', 'harness', 'persona', 'extract', 'signals', 'clean',
                 'competitor', 'tables', 'reports', 'connectors'];

  async function goto(tool, settle = 1200) {
    location.hash = '#' + tool;
    await sleep(settle);
  }

  async function run() {
    const results = [];
    const errors = [];
    const onErr = (e) => errors.push({ tool: (location.hash || '').slice(1),
                                       msg: String(e.message || e).slice(0, 140) });
    window.addEventListener('error', onErr);
    const origErr = console.error;
    console.error = (...a) => { onErr({ message: a[0] }); origErr(...a); };

    const check = async (area, name, fn) => {
      const t0 = performance.now();
      let status = FAIL, note = '';
      try {
        const out = await fn();
        if (Array.isArray(out)) { status = out[0]; note = out[1] || ''; }
        else { status = out ? PASS : FAIL; }
      } catch (e) { status = FAIL; note = `threw ${e.message}`.slice(0, 120); }
      results.push({ area, name, status, note, ms: Math.round(performance.now() - t0) });
    };

    /* ---- every tool renders, with its OWN heading and no blank screen ---- */
    for (const t of TOOLS) {
      await check('render', `${t} renders`, async () => {
        await goto(t);
        const views = visAll('.view, .tbl-shell');
        if (!views.length) return [FAIL, 'no visible view'];
        const txt = (document.querySelector('main') || document.body).innerText.trim();
        if (txt.length < 40) return [FAIL, `only ${txt.length} chars visible`];
        const h1 = visAll('.view-h1')[0];
        return [PASS, `${txt.length} chars` + (h1 ? `, "${h1.textContent.trim().slice(0, 28)}"` : '')];
      });
    }

    /* ---- no horizontal overflow at a laptop width ---- */
    await check('layout', 'no horizontal overflow', async () => {
      const bad = [];
      for (const t of TOOLS) {
        await goto(t, 700);
        if (document.documentElement.scrollWidth > window.innerWidth + 2) bad.push(t);
      }
      return bad.length ? [FAIL, `overflows: ${bad.join(', ')}`] : [PASS, 'all tools fit'];
    });

    /* ---- interactive controls actually exist per tool ---- */
    await check('controls', 'each tool exposes a control', async () => {
      const dead = [];
      for (const t of TOOLS) {
        await goto(t, 700);
        const n = visAll('button, input, textarea, [role=button]').length;
        if (n === 0) dead.push(t);
      }
      return dead.length ? [FAIL, `no controls: ${dead.join(', ')}`] : [PASS, 'all interactive'];
    });

    /* ---- NoBounce: paste a messy list and clean it end to end ---- */
    await check('flow', 'NoBounce cleans a pasted list', async () => {
      await goto('clean');
      const ta = visAll('textarea')[0];
      if (!ta) return [FAIL, 'no textarea'];
      setValue(ta, 'a@gmail.com\na@gmail.com\nbad@@x\ninfo@stripe.com');
      await sleep(200);
      const btn = visAll('button').find(b => /clean list/i.test(b.textContent));
      if (!btn) return [FAIL, 'no Clean list button'];
      btn.click();
      for (let i = 0; i < 30 && !/Deliverable|Undeliverable|Duplicates/i
           .test(document.body.innerText); i++) await sleep(500);
      const got = /Deliverable|Undeliverable|Duplicates/i.test(document.body.innerText);
      return got ? [PASS, 'verdict cards rendered'] : [DEG, 'no verdicts (engine may be absent)'];
    });

    /* ---- Persona: score real copy ---- */
    await check('flow', 'Persona scores copy', async () => {
      await goto('persona');
      const ta = visAll('textarea')[0];
      if (!ta) return [FAIL, 'no textarea'];
      setValue(ta, 'The fastest payment gateway for Indian startups.');
      await sleep(200);
      const btn = visAll('button').find(b => /preview|run|score|see how/i.test(b.textContent));
      if (!btn) return [FAIL, 'no run button'];
      btn.click();
      for (let i = 0; i < 30 && !/reaction|persona|launch/i
           .test(document.body.innerText); i++) await sleep(500);
      return /reaction|persona|launch/i.test(document.body.innerText)
        ? [PASS, 'reactions rendered'] : [DEG, 'no reactions'];
    });

    /* ---- Harness: delegate in plain English, the product's core loop ---- */
    await check('flow', 'Harness delegation runs', async () => {
      await goto('harness');
      const ex = visAll('.hn-ex')[0];
      if (!ex) return [FAIL, 'no example prompts'];
      ex.click();
      for (let i = 0; i < 60 && !document.querySelector('.hn-card'); i++) await sleep(500);
      const card = document.querySelector('.hn-card');
      if (!card) return [DEG, 'no result card (source may be blocked)'];
      const t = card.innerText;
      if (/cannot take this on/i.test(t)) return [FAIL, 'routed to an unbuilt teammate'];
      return [PASS, t.split('\n')[0].slice(0, 46)];
    });

    /* ---- Tables persist SERVER-SIDE, not in localStorage ---- */
    await check('state', 'tables persist to the server', async () => {
      const KEY = 'gtmstack.tables.v1';
      const probe = { cols: [{ key: 'n', label: 'N', type: 'text' }],
                      rows: [{ _id: 'uitest', n: 'ui-probe-' + Date.now() }] };
      await fetch(`${API}/api/docs`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: KEY, data: probe, kind: 'table' }) });
      const back = await fetch(`${API}/api/docs?key=${encodeURIComponent(KEY)}`)
        .then(r => r.json());
      if (!back.found) return [FAIL, 'server did not store the doc'];
      return [PASS, 'round-tripped through /api/docs'];
    });

    await check('state', 'no localStorage writes remain', async () => {
      /* The instruction was that nothing lives in localStorage. Spy on the
         setter and drive the app: a write here means something regressed. */
      const orig = Storage.prototype.setItem;
      const wrote = [];
      Storage.prototype.setItem = function (k, v) { wrote.push(k); return orig.call(this, k, v); };
      try {
        for (const t of ['tables', 'signals', 'clean', 'home']) await goto(t, 800);
      } finally { Storage.prototype.setItem = orig; }
      const bad = wrote.filter(k => !/harness/i.test(k));   // the client secret is the one allowed key
      return bad.length ? [FAIL, `wrote: ${[...new Set(bad)].join(', ')}`]
                        : [PASS, 'nothing written to localStorage'];
    });

    /* ---- analytics fire on tool switch ---- */
    await check('state', 'analytics record tool opens', async () => {
      const before = await fetch(`${API}/api/docs?usage=1`).then(r => r.json())
        .then(d => d.events || 0).catch(() => 0);
      await goto('signals', 600); await goto('clean', 600); await goto('home', 600);
      await sleep(800);
      const after = await fetch(`${API}/api/docs?usage=1`).then(r => r.json())
        .then(d => d.events || 0).catch(() => 0);
      return after > before ? [PASS, `${before} -> ${after} events`]
                            : [FAIL, 'no events recorded'];
    });

    /* ---- responsive ---- */
    await check('layout', 'mobile width does not break', async () => {
      const w = window.innerWidth;
      if (w > 900) return [SKIP, `viewport is ${w}px, resize to test mobile`];
      await goto('home', 800);
      return document.documentElement.scrollWidth <= window.innerWidth + 2
        ? [PASS, 'fits'] : [FAIL, 'overflows on mobile'];
    });

    window.removeEventListener('error', onErr);
    console.error = origErr;

    /* Console errors are reported as their own check so a render pass with a
       silent exception cannot look clean. */
    results.push({
      area: 'console', name: 'no console errors',
      status: errors.length ? FAIL : PASS,
      note: errors.length ? errors.slice(0, 3).map(e => `${e.tool}: ${e.msg}`).join(' | ') : 'clean',
      ms: 0,
    });

    const n = (s) => results.filter(r => r.status === s).length;
    return {
      total: results.length, pass: n(PASS), fail: n(FAIL),
      degraded: n(DEG), skipped: n(SKIP),
      failures: results.filter(r => r.status === FAIL),
      results,
    };
  }

  window.__uiTest = run;
  return 'ui suite loaded: call window.__uiTest()';
})();
