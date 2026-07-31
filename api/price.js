// Relay: fetches StubHub OSL Saturday prices via Browserbase and returns JSON.
// Exists because the Claude cloud sandbox's egress proxy blocks api.browserbase.com,
// so the scheduled routine curls this endpoint instead of scraping directly.
const { chromium } = require('playwright-core');

const EVENT_URL =
  'https://www.stubhub.com/outside-lands-music-festival-san-francisco-tickets-8-8-2026/event/159253857/?quantity=1';

const CLASS_NAMES = {
  'General Admission': 'GA',
  VIP: 'VIP',
  'GA+': 'GA+',
  'Golden Gate Pass': 'Golden Gate',
};

// Same rule as check_price.py: first $ amount within 8 lines of a class heading,
// validated by "incl. fees" within 2 lines after it.
function parsePrices(text) {
  const lines = text.split('\n').map((l) => l.trim());
  const prices = {};
  for (let i = 0; i < lines.length; i++) {
    const key = CLASS_NAMES[lines[i]];
    if (!key || prices[key] !== undefined) continue;
    for (let j = i + 1; j < Math.min(i + 9, lines.length); j++) {
      const m = lines[j].match(/^\$([\d,]+)(?:\.\d{2})?$/);
      if (!m) continue;
      const feesNear = lines
        .slice(j + 1, Math.min(j + 3, lines.length))
        .some((l) => l.includes('incl. fees'));
      if (feesNear) {
        prices[key] = parseInt(m[1].replace(/,/g, ''), 10);
        break;
      }
    }
  }
  return prices;
}

module.exports = async (req, res) => {
  // Stateless: the caller supplies Browserbase creds, nothing is stored here.
  // Possessing a valid key IS the auth; without one the request fails in <1s.
  const bbKey = req.headers['x-bb-key'];
  const bbProject = req.headers['x-bb-project'];
  if (!bbKey || !bbProject) {
    res.status(401).json({ ok: false, error: 'missing x-bb-key / x-bb-project headers' });
    return;
  }
  try {
    const sessRes = await fetch('https://api.browserbase.com/v1/sessions', {
      method: 'POST',
      headers: {
        'X-BB-API-Key': bbKey,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ projectId: bbProject }),
    });
    if (!sessRes.ok) {
      res.status(502).json({
        ok: false,
        error: `browserbase session failed: HTTP ${sessRes.status} ${await sessRes.text()}`,
      });
      return;
    }
    const session = await sessRes.json();

    let text;
    const browser = await chromium.connectOverCDP(session.connectUrl);
    try {
      const ctx = browser.contexts()[0];
      const page = ctx.pages()[0] || (await ctx.newPage());
      await page.goto(EVENT_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(12000);
      text = await page.evaluate(() => document.body.innerText);
    } finally {
      await browser.close();
    }

    const prices = parsePrices(text);
    if (prices.GA === undefined) {
      res.status(200).json({
        ok: false,
        error: 'GA price not found; page layout may have changed or listings sold out',
        ts: new Date().toISOString(),
        partial_prices: prices,
        text_sample: text.slice(0, 600),
      });
      return;
    }
    res.status(200).json({ ok: true, ts: new Date().toISOString(), prices });
  } catch (e) {
    res.status(500).json({ ok: false, error: `${e.name}: ${e.message}` });
  }
};
