// Browser-based verification of every `found` offer from a provider_eval.py
// run, per .claude/rules/post-tuning-browser-verification.md: after every
// live tuning round, open every found offer's source_url with a real
// browser (curl/WebFetch get 403'd by Allegro and other bot-gated stores —
// see ~/.claude/rules/playwright-mcp-chrome-missing.md) and dump what's
// actually on the page, so a human/agent can check product match, price
// match, and (for marketplace/aggregator pages) whether a lower price is
// visible elsewhere on the same page.
//
// This script does NOT judge correctness itself — it fetches ground truth.
// Judging (does the text actually match the claimed price/product) is a
// manual step done by reading text_excerpt, exactly like
// .claude/rules/groq-firecrawl-offer-validity-audit.md's dated updates do.
//
// Usage (from backend/):
//   node scripts/verify_offers_browser.mjs <found_offers.json> <out.json>
//
// <found_offers.json> is an array of {sku, name, price, currency, seller, url}
// — extract it from a provider_eval.py --keep-raw result file's `found`
// entries first (offer.price/currency/seller/source_url).

import { chromium } from '/home/antek/Documents/Workspace/ME/panel/node_modules/playwright/index.mjs';
import { readFileSync, writeFileSync } from 'fs';

const [, , inPath, outPath] = process.argv;
if (!inPath || !outPath) {
  console.error('Usage: node verify_offers_browser.mjs <found_offers.json> <out.json>');
  process.exit(1);
}

const offers = JSON.parse(readFileSync(inPath, 'utf8'));

const REJECT_SELECTORS = [
  'button:has-text("Odrzuć")', 'button:has-text("Odrzucam")',
  'button:has-text("Reject")', 'button:has-text("Nie zgadzam")',
  'button:has-text("Tylko niezbędne")', 'button:has-text("Only necessary")',
  '#onetrust-reject-all-handler', 'button[aria-label*="reject" i]',
];

async function tryRejectCookies(page) {
  for (const sel of REJECT_SELECTORS) {
    try {
      const btn = page.locator(sel).first();
      if (await btn.isVisible({ timeout: 1000 })) {
        await btn.click({ timeout: 2000 });
        await page.waitForTimeout(300);
        return true;
      }
    } catch {}
  }
  return false;
}

const browser = await chromium.launch({ headless: true, executablePath: '/opt/google/chrome/chrome' });
const results = [];

for (const offer of offers) {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    viewport: { width: 1400, height: 1000 },
  });
  const page = await context.newPage();
  const record = {
    sku: offer.sku, name: offer.name, extracted_price: offer.price,
    currency: offer.currency, seller: offer.seller, url: offer.url,
  };
  try {
    const resp = await page.goto(offer.url, { waitUntil: 'networkidle', timeout: 25000 });
    record.http_status = resp ? resp.status() : null;
    await tryRejectCookies(page);
    await page.waitForTimeout(1000);
    const bodyText = await page.evaluate(() => document.body.innerText).catch(() => '');
    record.title = await page.title().catch(() => '');
    record.text_length = bodyText.length;
    // Full text, not truncated — a wrong/fabricated price needs the whole
    // page searched, not just the first screen's worth (see the Synology
    // HAT5300 case in groq-firecrawl-offer-validity-audit.md, where the
    // fabricated price wasn't in the first 4000 chars either).
    record.text = bodyText;
    const lower = bodyText.toLowerCase();
    record.likely_blocked = /captcha|access denied|are you a human|attention required|cloudflare|robot or human/.test(lower) && bodyText.length < 2000;
  } catch (err) {
    record.error = String(err.message || err);
  }
  await context.close();
  results.push(record);
  console.log(`done: ${record.sku} status=${record.http_status ?? 'ERR'} len=${record.text_length ?? 0} blocked=${record.likely_blocked ?? 'n/a'}`);
  writeFileSync(outPath, JSON.stringify(results, null, 2), 'utf8');
}

await browser.close();
console.log('ALL DONE');
