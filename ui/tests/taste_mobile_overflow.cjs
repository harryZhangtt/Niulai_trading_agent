/* Regression for shrink-to-fit mobile layouts hiding overflow from innerWidth checks. */
const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const ui = path.resolve(__dirname, '..');
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(ui, 'runtime/browsers');
process.env.TMPDIR = path.join(ui, 'runtime/tmp/taste-overflow-tests');
fs.mkdirSync(process.env.TMPDIR, { recursive: true });
const { chromium } = require('../verification/node_modules/@playwright/test');

test('Taste overflow probe measures the CSS viewport on mobile', async (t) => {
  const { probe } = await import(pathToFileURL(path.join(ui, 'skills/design-taste-frontend/scripts/lib/probe.mjs')).href);
  const browser = await chromium.launch({ executablePath: chromium.executablePath() });
  const fixtures = [
    { name: 'responsive control', width: 390, mobile: true, css: 'main{max-width:100%;padding:16px}', content: 'A short account label', overflow: false },
    { name: 'fixed-width mobile panel', width: 390, mobile: true, css: 'main{width:1200px}', content: 'A short account label', overflow: true },
    { name: 'wide child contained by a clipped section', width: 390, mobile: true, css: 'main{width:100%;overflow:clip}main p{width:1200px}', content: 'A short account label', overflow: false },
    { name: 'unbroken long label', width: 390, mobile: true, css: 'main{width:100%}p{white-space:nowrap}', content: 'AccountIdentifier'.repeat(20), overflow: true },
    { name: 'wide panel fits desktop', width: 1440, mobile: false, css: 'main{width:1200px}', content: 'A short account label', overflow: false },
  ];
  try {
    for (const fixture of fixtures) {
      await t.test(fixture.name, async () => {
        const page = await browser.newPage({ viewport: { width: fixture.width, height: 844 }, isMobile: fixture.mobile });
        try {
          await page.setContent(`<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1"><style>*{box-sizing:border-box}body{margin:0}p{font:18px sans-serif}${fixture.css}</style><main><h1>Account settings</h1><p>${fixture.content}</p></main></html>`);
          const measured = await page.evaluate(() => ({ inner: innerWidth, client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
          const actual = await page.evaluate(probe);
          assert.equal(measured.client, fixture.width);
          assert.equal(actual.page.horizontalOverflow > 0, fixture.overflow, JSON.stringify({ measured, reported: actual.page.horizontalOverflow }));
          if (fixture.overflow) {
            assert.ok(measured.inner > measured.client, 'fixture must reproduce mobile viewport expansion');
            assert.equal(actual.page.horizontalOverflow, measured.scroll - measured.client);
          }
        } finally { await page.close(); }
      });
    }
  } finally { await browser.close(); }
});
