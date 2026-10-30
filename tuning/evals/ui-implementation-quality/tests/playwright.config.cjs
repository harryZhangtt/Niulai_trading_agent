const path = require('node:path');
const { defineConfig } = require(path.join(process.env.UI_TOOL_ROOT, 'node_modules/@playwright/test'));
const output = process.env.BENCH_OUTPUT;
const port = process.env.BENCH_PORT ?? '5193';
if (!output || !process.env.BENCH_APP) throw new Error('Absolute BENCH_APP and BENCH_OUTPUT required');
module.exports = defineConfig({
  testDir: __dirname, testMatch: 'quality.spec.cjs', timeout: 12000,
  expect: { timeout: 2500 }, workers: 1, retries: 0, fullyParallel: false,
  outputDir: path.join(output, 'test-results'),
  reporter: [['line'], ['json', { outputFile: path.join(output, 'results.json') }]],
  use: { baseURL: `http://127.0.0.1:${port}`, channel: 'chromium', headless: true, trace: 'retain-on-failure', screenshot: 'on', viewport: { width: 1100, height: 900 } },
  webServer: {
    command: `${JSON.stringify(process.execPath)} ${JSON.stringify(path.join(process.env.UI_TOOL_ROOT, 'node_modules/vite/bin/vite.js'))} --config ${JSON.stringify(path.join(__dirname, 'vite.config.mjs'))}`,
    url: `http://127.0.0.1:${port}`, timeout: 20000, reuseExistingServer: false,
  },
});
