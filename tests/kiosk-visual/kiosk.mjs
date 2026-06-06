// Comprehensive kiosk harness: validates sizing AND drives every kiosk flow.
//
// Target device: iPad Pro 12.9" — 1366 x 1024 CSS px, landscape. Safari's top
// address bar (~SAFARI_TOOLBAR px, no tab bar on the kiosk) eats vertical space,
// and since the kiosk About page disables document scrolling the bar never
// retracts — so the page actually sees ~1366 x (1024 - toolbar).
import { chromium } from 'playwright';
import { Reporter, shooter, enableKiosk, metrics, login, placeBet,
         waitAutoLogout, manualLogout, testCarousel, markPage, assertNoNav,
         tagLeftPanel, assertLeftPanelPersisted, assertTwoColumn } from './lib.mjs';

const BASE    = process.env.BASE_URL || 'http://localhost:9999';
const OUT     = process.env.OUT_DIR  || '/work/shots';
const TOOLBAR = Number(process.env.SAFARI_TOOLBAR || 90);
const NAME    = process.env.GUEST_NAME  || 'Harness Tester';
const PHONE   = process.env.GUEST_PHONE || '9999';

const WIDTH = 1366, HEIGHT = 1024 - TOOLBAR;
const IPAD_UA = 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/604.1';

const rep = new Reporter();
const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: WIDTH, height: HEIGHT },
  deviceScaleFactor: 2, userAgent: IPAD_UA, hasTouch: true,
});
const page = await ctx.newPage();
const shot = shooter(page, OUT, 'kiosk');

console.log(`KIOSK harness @ ${WIDTH}x${HEIGHT} (1024 - ${TOOLBAR}px toolbar)`);
await enableKiosk(page, BASE);

// ── 1. Sizing: every kiosk page must fit one screen (no document overflow) ──
for (const p of [['about', '/about'], ['bet-login', '/bet'], ['leaderboard', '/leaderboard']]) {
  await page.goto(BASE + p[1], { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const m = await metrics(page);
  await shot(p[0]);
  await rep.step(`${p[0]} fits one screen`, async () => {
    if (m.docOverflowPx > 1 || (m.bioClippedPx ?? 0) > 1)
      throw new Error(`overflow ${JSON.stringify(m)}`);
  });
  if (p[0] === 'about') console.log(`    about metrics: ${JSON.stringify(m)}`);
}

// ── 2. Photo carousel ──
await testCarousel(page, BASE, shot, rep);

// ── 3. Place a NEW bet on the right-hand form, then gas-pump auto-logout ──
await rep.step('kiosk login → betting form swaps in', () => login(page, BASE, { name: NAME, phone: PHONE, expect: 'form' }));
await shot('bet-form');
await rep.step('place new bet → gas-pump thank-you', () => placeBet(page, [['Boxer', 60], ['Labrador Retriever', 40]], { expect: 'thanks' }));
await shot('bet-thanks');
await rep.step('gas-pump auto-logout redirects to /about', () => waitAutoLogout(page, BASE));

// ── 4. Returning guest (already placed): view + edit must TAKE OVER the card,
//      never load a new page. Each action is wrapped in a no-navigation assert. ──
await rep.step('returning login swaps ONLY the right panel; rules persist on the left', async () => {
  await page.goto(BASE + '/bet', { waitUntil: 'networkidle' });
  await page.waitForSelector('#verify-form');
  await assertTwoColumn(page, 'login screen');
  await tagLeftPanel(page);
  await markPage(page);
  await page.fill('#name', NAME);
  await page.fill('#phone4', PHONE);
  await page.click('#verify-form button[type=submit]');
  await page.waitForSelector('a[href*="edit=1"]', { timeout: 10000 });
  await assertNoNav(page, 'returning-guest login → Bet Placed');
  await assertLeftPanelPersisted(page, 'returning-guest login → Bet Placed');
  await assertTwoColumn(page, 'Bet Placed view');
});
await shot('bet-placed');
await rep.step('Edit My Bet swaps only the right panel (rules persist)', async () => {
  await markPage(page);
  await page.click('a[href*="edit=1"]');
  await page.waitForSelector('#bet-form', { timeout: 10000 });
  await assertNoNav(page, 'Edit My Bet → edit form');
  await assertLeftPanelPersisted(page, 'Edit My Bet → edit form');
});
await rep.step('saving the edit swaps only the right panel + updates the bet', async () => {
  await page.locator('.breed-row').nth(0).locator('.breed-pct').fill('70');
  await page.locator('.breed-row').nth(1).locator('.breed-pct').fill('30');
  await page.waitForSelector('#btn-submit:not([disabled])', { timeout: 5000 });
  await markPage(page);
  await page.click('#btn-submit');
  await page.waitForSelector('a[href*="edit=1"]', { timeout: 10000 });
  await assertNoNav(page, 'save edit → Bet Placed');
  await assertLeftPanelPersisted(page, 'save edit → Bet Placed');
});
await shot('bet-edited');

// ── 5. Manual logout from the Bet Placed view ──
await rep.step('manual Log out returns to identity login', () => manualLogout(page));
await shot('logged-out');

// ── 6. Idle watchdog: a walked-away session resets to attract + is cleared ──
await rep.step('idle reset hands an abandoned form back to /about and clears the guest', async () => {
  await login(page, BASE, { name: NAME, phone: PHONE, expect: 'placed' });
  await page.goto(BASE + '/bet?edit=1&idle_ms=1500', { waitUntil: 'networkidle' });
  await page.waitForSelector('#bet-form', { timeout: 8000 });
  await page.waitForURL('**/about', { timeout: 6000 });             // idle fired → attract
  await page.goto(BASE + '/bet', { waitUntil: 'networkidle' });
  await page.waitForSelector('#verify-form', { timeout: 5000 });    // session cleared → login again
});

await browser.close();
process.exit(rep.summary() ? 0 : 1);
