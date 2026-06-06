// Desktop harness — NON-kiosk wide screen (1280x900). Verifies the persistent
// two-column bet shell works for regular desktop visitors too: rules stay in the
// left column and only #bet-panel swaps across login → form → placed → edit → save.
import { chromium } from 'playwright';
import { Reporter, shooter, placeBet, markPage, assertNoNav,
         tagLeftPanel, assertLeftPanelPersisted, assertTwoColumn } from './lib.mjs';

const BASE  = process.env.BASE_URL || 'http://localhost:9999';
const OUT   = process.env.OUT_DIR  || '/work/shots';
const NAME  = process.env.GUEST_NAME  || 'Harness Tester';
const PHONE = process.env.GUEST_PHONE || '9999';

const rep = new Reporter();
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
const shot = shooter(page, OUT, 'desktop');

console.log('DESKTOP harness @ 1280x900 (non-kiosk)');

await page.goto(BASE + '/bet', { waitUntil: 'networkidle' });
await page.waitForSelector('#verify-form');
await rep.step('desktop bet page is two-column (rules left of panel)', () => assertTwoColumn(page, 'desktop login'));
await tagLeftPanel(page);
await shot('login');

await rep.step('login swaps only the right panel → bet form (rules persist)', async () => {
  await markPage(page);
  await page.fill('#name', NAME);
  await page.fill('#phone4', PHONE);
  await page.click('#verify-form button[type=submit]');
  await page.waitForSelector('#bet-form', { timeout: 10000 });
  await assertNoNav(page, 'desktop login → form');
  await assertLeftPanelPersisted(page, 'desktop login → form');
  await assertTwoColumn(page, 'desktop bet form');
});
await shot('bet-form');

await rep.step('placing a bet swaps only the right panel → Bet Placed', async () => {
  await markPage(page);
  await placeBet(page, [['Boxer', 60], ['Labrador Retriever', 40]], { expect: 'placed' });
  await assertNoNav(page, 'desktop place → Bet Placed');
  await assertLeftPanelPersisted(page, 'desktop place → Bet Placed');
  await assertTwoColumn(page, 'desktop Bet Placed');
});
await shot('bet-placed');

await rep.step('Edit My Bet swaps only the right panel (rules persist)', async () => {
  await markPage(page);
  await page.click('a[href*="edit=1"]');
  await page.waitForSelector('#bet-form', { timeout: 10000 });
  await assertNoNav(page, 'desktop Edit → form');
  await assertLeftPanelPersisted(page, 'desktop Edit → form');
});
await rep.step('saving the edit swaps only the right panel', async () => {
  await page.locator('.breed-row').nth(0).locator('.breed-pct').fill('75');
  await page.locator('.breed-row').nth(1).locator('.breed-pct').fill('25');
  await page.waitForSelector('#btn-submit:not([disabled])', { timeout: 5000 });
  await markPage(page);
  await page.click('#btn-submit');
  await page.waitForSelector('a[href*="edit=1"]', { timeout: 10000 });
  await assertNoNav(page, 'desktop save → Bet Placed');
  await assertLeftPanelPersisted(page, 'desktop save → Bet Placed');
});
await shot('bet-edited');

await browser.close();
process.exit(rep.summary() ? 0 : 1);
