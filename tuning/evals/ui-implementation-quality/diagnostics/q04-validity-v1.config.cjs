const path = require('node:path');
const { defineConfig } = require(path.join(process.env.UI_TOOL_ROOT, 'node_modules/@playwright/test'));
const workspace = process.env.DQ_WORKSPACE;
const output = process.env.DQ_OUTPUT;
if (!workspace || !output) throw new Error('DQ_WORKSPACE and DQ_OUTPUT are required absolute local paths');
const roots = {
  seed: path.join(workspace, 'tuning/evals/ui-implementation-quality/seed'),
  reference: path.join(workspace, 'tuning/runtime/ui-implementation-quality-v1/author/reference'),
  'patch-X': path.join(workspace, 'tuning/runtime/ui-implementation-quality-v1/audit/apps/patch-X'),
  'patch-Y': path.join(workspace, 'tuning/runtime/ui-implementation-quality-v1/audit/apps/patch-Y'),
};
const entries = Object.entries(roots).map(([name, app], index) => ({ name, app, port: 5291 + index }));
module.exports = defineConfig({
  testDir: __dirname, testMatch: 'q04-validity-v1.spec.cjs', timeout: 12000,
  expect: { timeout: 2500 }, workers: 1, retries: 0, fullyParallel: false,
  outputDir: path.join(output, 'test-results'),
  reporter: [['line'], ['json', { outputFile: path.join(output, 'results.json') }]],
  use: { channel: 'chromium', headless: true, trace: 'on', screenshot: 'on', viewport: { width: 1100, height: 900 } },
  projects: entries.map(({ name, port }) => ({ name, use: { baseURL: `http://127.0.0.1:${port}` } })),
  webServer: entries.map(({ name, app, port }) => ({
    command: `${JSON.stringify(process.execPath)} ${JSON.stringify(path.join(process.env.UI_TOOL_ROOT, 'node_modules/vite/bin/vite.js'))} --config ${JSON.stringify(path.join(__dirname, '../tests/vite.config.mjs'))}`,
    env: { ...process.env, BENCH_APP: app, BENCH_OUTPUT: path.join(output, 'servers', name), BENCH_PORT: String(port) },
    url: `http://127.0.0.1:${port}`, timeout: 20000, reuseExistingServer: false,
  })),
});
