// Vertical mobile harness — phone mode (no kiosk). People use the site portrait.
//
// Standard size: iPhone 13/14 — 390 x 844 CSS px portrait, devicePixelRatio 3.
// Unlike the kiosk, mobile pages scroll normally, so overflow is expected; this
// harness captures full-page screenshots and drives the same bet/edit/carousel
// flows to confirm they work at phone width.
import { chromium } from 'playwright';
import { Reporter, shooter, login, placeBet, testCarousel, markPage, assertNoNav } from './lib.mjs';

const BASE  = process.env.BASE_URL || 'http://localhost:9999';
const OUT   = process.env.OUT_DIR  || '/work/shots';
const NAME  = process.env.GUEST_NAME  || 'Harness Tester';
const PHONE = process.env.GUEST_PHONE || '9999';

const WIDTH = 390, HEIGHT = 844;
const IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';

const rep = new Reporter();
const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: WIDTH, height: HEIGHT },
  deviceScaleFactor: 3, userAgent: IPHONE_UA, isMobile: true, hasTouch: true,
});
const page = await ctx.newPage();
const shot = shooter(page, OUT, 'mobile');
const fullShot = (name) => page.screenshot({ path: `${OUT}/mobile_${name}.png`, fullPage: true });

console.log(`MOBILE harness @ ${WIDTH}x${HEIGHT} portrait (iPhone 13/14)`);

// ── 1. Render every page full-length (phone mode scrolls; overflow is fine) ──
for (const p of [['home', '/'], ['about', '/about'], ['bet-login', '/bet'], ['leaderboard', '/leaderboard']]) {
  await page.goto(BASE + p[1], { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  await fullShot(p[0]);
  await rep.step(`${p[0]} renders`, async () => { await page.waitForSelector('nav.nav'); });
}

// ── 2. Photo carousel ──
await testCarousel(page, BASE, shot, rep);

// ── 3. Place a NEW bet (phone mode goes straight to the Bet Placed view) ──
await rep.step('login → betting form', () => login(page, BASE, { name: NAME, phone: PHONE, expect: 'form' }));
await fullShot('bet-form');
await rep.step('place new bet → Bet Placed', () => placeBet(page, [['Boxer', 55], ['Labrador Retriever', 45]], { expect: 'placed' }));
await fullShot('bet-placed');

// ── 4. Returning guest (non-kiosk): view + edit must TAKE OVER the card, not
//      load a new page — this mirrors the desktop "Dan Kouba" repro. ──
await rep.step('returning-guest login takes over the card (no new page)', async () => {
  await page.goto(BASE + '/bet/logout', { waitUntil: 'networkidle' });  // fresh session
  await page.goto(BASE + '/bet', { waitUntil: 'networkidle' });
  await page.waitForSelector('#verify-form');
  await markPage(page);
  await page.fill('#name', NAME);
  await page.fill('#phone4', PHONE);
  await page.click('#verify-form button[type=submit]');
  await page.waitForSelector('a[href*="edit=1"]', { timeout: 10000 });
  await assertNoNav(page, 'non-kiosk returning login → Bet Placed');
});
await rep.step('Edit My Bet takes over the card (no new page)', async () => {
  await markPage(page);
  await page.click('a[href*="edit=1"]');
  await page.waitForSelector('#bet-form', { timeout: 10000 });
  await assertNoNav(page, 'non-kiosk Edit My Bet → form');
});
await rep.step('saving the edit stays in the card (no new page)', async () => {
  await page.locator('.breed-row').nth(0).locator('.breed-pct').fill('80');
  await page.locator('.breed-row').nth(1).locator('.breed-pct').fill('20');
  await page.waitForSelector('#btn-submit:not([disabled])', { timeout: 5000 });
  await markPage(page);
  await page.click('#btn-submit');
  await page.waitForSelector('a[href*="edit=1"]', { timeout: 10000 });
  await assertNoNav(page, 'non-kiosk save edit → Bet Placed');
});
await fullShot('bet-edited');

await browser.close();
process.exit(rep.summary() ? 0 : 1);
