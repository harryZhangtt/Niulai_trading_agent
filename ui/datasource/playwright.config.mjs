import { defineConfig } from '../verification/node_modules/@playwright/test/index.mjs';
export default defineConfig({
  testDir: './tests', testMatch: '*.spec.mjs', timeout: 20000, retries: 0, workers: 1,
  outputDir: '../runtime/datasource-tests',
  reporter: [['list'], ['json', { outputFile: '../runtime/datasource-tests/results.json' }]],
  use: { baseURL: 'http://localhost:7270', channel: 'chromium', headless: true, trace: 'retain-on-failure' },
});
