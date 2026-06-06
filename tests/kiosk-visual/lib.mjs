// Shared helpers + end-to-end flows for the Sparky visual/functional harness.
// Used by kiosk.mjs (frozen iPad layout) and mobile.mjs (vertical phone).
//
// Flows drive the real UI: identity login, the inline "Place My Bet" form on the
// right, submit, the kiosk gas-pump + auto-logout, inline edit, manual logout,
// and the shared photo carousel. Each step screenshots and asserts, so a broken
// flow fails loudly instead of silently.

export class Reporter {
  constructor() { this.pass = 0; this.fails = []; }
  ok(name)        { this.pass++; console.log(`  ✓ ${name}`); }
  fail(name, err) { this.fails.push(name); console.log(`  ✗ ${name} — ${err && err.message || err}`); }
  async step(name, fn) {
    try { await fn(); this.ok(name); }
    catch (e) { this.fail(name, e); }
  }
  summary() {
    console.log(`\n${this.pass} passed, ${this.fails.length} failed`);
    if (this.fails.length) console.log('FAILED: ' + this.fails.join(', '));
    return this.fails.length === 0;
  }
}

export function shooter(page, out, prefix) {
  return (name) => page.screenshot({ path: `${out}/${prefix}_${name}.png` });
}

// Navigation detector: set a marker on window. An in-place swap keeps the same
// document (marker survives); a full page navigation wipes it. Use markPage()
// just before an action, then assertNoNav() after, to prove the action took over
// the card instead of loading a new page.
export async function markPage(page) { await page.evaluate(() => { window.__noNav = 1; }); }
export async function assertNoNav(page, label) {
  const survived = await page.evaluate(() => window.__noNav === 1);
  if (!survived) throw new Error(`${label}: full-page navigation occurred (should take over the card in place)`);
}

// Left-column persistence: tag the live .bet-info node, then after a swap assert
// the SAME node still carries the tag — proving only #bet-panel changed and the
// rules column was never re-rendered.
export async function tagLeftPanel(page) {
  await page.evaluate(() => { const el = document.querySelector('.bet-info'); if (el) el.dataset.persist = '1'; });
}
export async function assertLeftPanelPersisted(page, label) {
  const ok = await page.evaluate(() => {
    const el = document.querySelector('.bet-info');
    return !!(el && el.dataset.persist === '1');
  });
  if (!ok) throw new Error(`${label}: left rules column was re-rendered (only #bet-panel should swap)`);
}

// Confirm the two-column layout is active: rules sit to the left of the panel.
export async function assertTwoColumn(page, label) {
  const ok = await page.evaluate(() => {
    const info = document.querySelector('.bet-info'), panel = document.querySelector('#bet-panel');
    if (!info || !panel) return false;
    const a = info.getBoundingClientRect(), b = panel.getBoundingClientRect();
    return b.left >= a.right - 2;
  });
  if (!ok) throw new Error(`${label}: expected two-column (rules left of panel)`);
}

export async function enableKiosk(page, base) {
  await page.goto(base + '/kiosk', { waitUntil: 'networkidle' });
}

export async function metrics(page) {
  return page.evaluate(() => {
    const r = (sel) => { const el = document.querySelector(sel); return el ? { s: el.scrollHeight, c: el.clientHeight } : null; };
    const bio = r('.about-bio .card'), photos = r('.about-photos');
    return {
      innerH: window.innerHeight,
      docOverflowPx: document.documentElement.scrollHeight - window.innerHeight,
      bioClippedPx: bio ? Math.max(0, bio.s - bio.c) : null,
      photoScrollablePx: photos ? Math.max(0, photos.s - photos.c) : null,
      bioFont: (() => { const c = document.querySelector('.about-bio .card'); return c ? getComputedStyle(c).fontSize : null; })(),
    };
  });
}

// ── Login via the identity card; waits for the inline swap to the expected view.
//    expect: 'form' (no bet yet) | 'placed' (already submitted).
export async function login(page, base, { name, phone, expect }) {
  await page.goto(base + '/bet', { waitUntil: 'networkidle' });
  await page.waitForSelector('#verify-form');
  await page.fill('#name', name);
  await page.fill('#phone4', phone);
  await page.click('#verify-form button[type=submit]');
  if (expect === 'form') await page.waitForSelector('#bet-form', { timeout: 10000 });
  else                   await page.waitForSelector('a[href*="edit=1"]', { timeout: 10000 });
}

// ── Fill the breed form. breeds = [[name, pct], ...] summing to 100.
async function fillBreedForm(page, breeds) {
  const have = await page.locator('.breed-row').count();
  for (let i = have; i < breeds.length; i++) await page.click('.btn-add-breed');
  for (let i = 0; i < breeds.length; i++) {
    const row   = page.locator('.breed-row').nth(i);
    const combo = row.locator('.breed-combo');
    await combo.click();
    await combo.fill(breeds[i][0]);
    await row.getByRole('option', { name: breeds[i][0], exact: true }).first().click();
    await row.locator('.breed-pct').fill(String(breeds[i][1]));
  }
  await page.waitForSelector('#btn-submit:not([disabled])', { timeout: 5000 });
}

// ── Place a brand-new bet from the form. expect: 'thanks' (kiosk) | 'placed'.
export async function placeBet(page, breeds, { expect }) {
  await fillBreedForm(page, breeds);
  await page.click('#btn-submit');
  if (expect === 'thanks') await page.getByText('Bet locked in', { exact: false }).waitFor({ timeout: 10000 });
  else                     await page.waitForSelector('a[href*="edit=1"]', { timeout: 10000 });
}

// ── Edit an existing bet inline (no navigation): Edit My Bet → change → Update.
export async function editBet(page, breeds) {
  await page.click('a[href*="edit=1"]');
  await page.waitForSelector('#bet-form', { timeout: 10000 });
  // Breeds are pre-filled & valid; just rewrite the percentages.
  for (let i = 0; i < breeds.length; i++) {
    await page.locator('.breed-row').nth(i).locator('.breed-pct').fill(String(breeds[i][1]));
  }
  await page.waitForSelector('#btn-submit:not([disabled])', { timeout: 5000 });
  await page.click('#btn-submit');
  await page.waitForSelector('a[href*="edit=1"]', { timeout: 10000 });
}

// ── Kiosk auto-logout: the gas-pump "I'm done" countdown returns to /about.
export async function waitAutoLogout(page, base) {
  await page.waitForURL('**/about', { timeout: 15000 });
}

// ── Manual logout: the kiosk "Log out" button returns to the identity login.
export async function manualLogout(page) {
  await page.click('a[data-countdown-href*="logout"]');
  await page.waitForSelector('#verify-form', { timeout: 10000 });
}

// ── Photo carousel: open from a thumbnail, advance, confirm filmstrip + close.
export async function testCarousel(page, base, shot, rep) {
  await page.goto(base + '/about', { waitUntil: 'networkidle' });
  await page.waitForSelector('.gallery-thumb');
  await rep.step('carousel opens on thumbnail click', async () => {
    await page.locator('.gallery-thumb').first().click();
    await page.waitForSelector('#lightbox.open', { timeout: 5000 });
    await page.waitForFunction(() => !!document.getElementById('lb-img').getAttribute('src'));
  });
  await shot('carousel-open');
  await rep.step('next arrow advances the photo + filmstrip', async () => {
    const before = await page.getAttribute('#lb-img', 'src');
    await page.click('#lb-next');
    await page.waitForFunction((b) => document.getElementById('lb-img').getAttribute('src') !== b, before, { timeout: 5000 });
    const active = await page.locator('.lb-strip-thumb.active').count();
    if (active !== 1) throw new Error(`expected 1 active filmstrip thumb, got ${active}`);
  });
  await rep.step('prev arrow goes back', async () => {
    const before = await page.getAttribute('#lb-img', 'src');
    await page.click('#lb-prev');
    await page.waitForFunction((b) => document.getElementById('lb-img').getAttribute('src') !== b, before, { timeout: 5000 });
  });
  await rep.step('close button dismisses the carousel', async () => {
    await page.click('#lb-close');
    // Closing removes .open; CSS then makes #lightbox display:none (hidden).
    await page.waitForSelector('#lightbox', { state: 'hidden', timeout: 5000 });
  });
}
