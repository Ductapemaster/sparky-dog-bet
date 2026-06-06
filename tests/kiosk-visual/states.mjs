// State-transition harness: drives the real ADMIN UI to lock/unlock betting and
// reveal/hide results, and verifies what the KIOSK shows in each state.
//
// Run against an ISOLATED instance (fresh DB) — never the live game — because
// lock/reveal are global config. See the run recipe in this folder's notes.
import { chromium } from 'playwright';
import { Reporter, shooter, enableKiosk } from './lib.mjs';

const BASE     = process.env.BASE_URL || 'http://localhost:9998';
const OUT      = process.env.OUT_DIR  || '/work/shots';
const ADMIN_PW = process.env.ADMIN_PW || 'sparky';
const TOOLBAR  = Number(process.env.SAFARI_TOOLBAR || 90);
const IPAD_UA  = 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/604.1';

const rep = new Reporter();
const browser = await chromium.launch();

// ── Admin context (desktop) ──
const admin = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
const ap = await admin.newPage();
const ashot = shooter(ap, OUT, 'admin');
await ap.goto(BASE + '/admin', { waitUntil: 'networkidle' });
await ap.fill('input[name=password]', ADMIN_PW);
// NB: the nav renders a "Sign Out" submit button on every page, so target the
// login form's button specifically rather than the first button[type=submit].
await ap.getByRole('button', { name: /Sign In/ }).click();
await ap.getByText('Game Controls').waitFor({ timeout: 8000 });
await ashot('overview');

// Reload the admin page fresh (avoids depending on in-place panel refresh), click
// the toggle, and confirm the toggle request actually reached the server.
async function toggle(now, after) {
  await ap.goto(BASE + '/admin', { waitUntil: 'networkidle' });
  const [resp] = await Promise.all([
    ap.waitForResponse((r) => r.url().includes('/admin/toggle'), { timeout: 8000 }),
    ap.getByRole('button', { name: now, exact: true }).click(),
  ]);
  if (resp.status() >= 400) throw new Error(`toggle ${now} → HTTP ${resp.status()}`);
  await ap.goto(BASE + '/admin', { waitUntil: 'networkidle' });
  await ap.getByRole('button', { name: after, exact: true }).waitFor({ timeout: 8000 });
}

// ── Kiosk context (iPad) ──
const kiosk = await browser.newContext({
  viewport: { width: 1366, height: 1024 - TOOLBAR },
  deviceScaleFactor: 2, userAgent: IPAD_UA, hasTouch: true,
});
const kp = await kiosk.newPage();
const kshot = shooter(kp, OUT, 'state');
await enableKiosk(kp, BASE);

async function kioskLogin(name, phone) {
  // Clear any prior guest (the kiosk context persists the session) so the
  // identity login form is present; /bet/logout keeps the kiosk flag.
  await kp.goto(BASE + '/bet/logout', { waitUntil: 'networkidle' });
  await kp.goto(BASE + '/bet', { waitUntil: 'networkidle' });
  await kp.waitForSelector('#verify-form', { timeout: 8000 });
  await kp.fill('#name', name);
  await kp.fill('#phone4', phone);
  await kp.click('#verify-form button[type=submit]');
  await kp.waitForSelector('#verify-form', { state: 'detached', timeout: 10000 });
  await kp.waitForTimeout(300);
}
const docOverflow = () => kp.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
const hasText = (t) => kp.getByText(t, { exact: false }).first().isVisible();

// ── 0. Baseline: results hidden → leaderboard placeholder ──
await kp.goto(BASE + '/leaderboard', { waitUntil: 'networkidle' });
await kshot('leaderboard-hidden');

// ── 1. LOCK betting (admin UI) ──
await rep.step('admin: Lock Betting toggles', () => toggle('Lock Betting', 'Unlock Betting'));
await rep.step('kiosk nav shows 🔒 when locked', async () => {
  await kp.goto(BASE + '/bet', { waitUntil: 'networkidle' });
  const nav = await kp.locator('nav').innerText();
  if (!nav.includes('🔒')) throw new Error('no lock glyph in nav');
});
await kshot('locked-login');
await rep.step('locked + submitted guest → submission shown, no Edit button', async () => {
  await kioskLogin('Test Alice', '1111');
  if (!(await hasText('Your Submission')) && !(await hasText("You're in"))) throw new Error('submission not shown');
  if (await kp.locator('a[href*="edit=1"]').count()) throw new Error('Edit button should be hidden when locked');
});
await kshot('locked-submitted');
await rep.step('locked + un-submitted guest → "Betting is Closed" card', async () => {
  await kioskLogin('Test Carol', '3333');
  if (!(await hasText('Betting is Closed'))) throw new Error('closed card not shown');
});
await kshot('locked-unsubmitted');

// ── 2. UNLOCK betting (admin UI) ──
await rep.step('admin: Unlock Betting toggles back', () => toggle('Unlock Betting', 'Lock Betting'));
await rep.step('unlocked → un-submitted guest sees the form again', async () => {
  await kioskLogin('Test Carol', '3333');
  await kp.waitForSelector('#bet-form', { timeout: 8000 });
});

// ── 3. REVEAL results (admin UI) ──
await rep.step('admin: Reveal Results toggles', () => toggle('Reveal Results', 'Hide Results'));
await rep.step('kiosk leaderboard shows ranked results', async () => {
  await kp.goto(BASE + '/leaderboard', { waitUntil: 'networkidle' });
  if (!(await hasText('Test Alice')) && !(await hasText('Alice'))) throw new Error('no ranked guests on leaderboard');
});
console.log(`    revealed leaderboard docOverflowPx: ${await docOverflow()}`);
await kshot('leaderboard-revealed');
await rep.step('revealed + submitted guest → "How You Did" + score', async () => {
  await kioskLogin('Test Alice', '1111');
  if (!(await hasText('How You Did'))) throw new Error('How You Did not shown');
  if (!(await hasText('pts off')) && !(await hasText('Score'))) throw new Error('score not shown');
});
await kshot('how-you-did');

// ── 4. HIDE results (admin UI) — confirm reversible ──
await rep.step('admin: Hide Results toggles back', () => toggle('Hide Results', 'Reveal Results'));

await browser.close();
process.exit(rep.summary() ? 0 : 1);
