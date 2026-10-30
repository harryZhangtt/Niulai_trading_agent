import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', timeout: 15000, retries: 0, workers: 1,
  outputDir: '../runtime/test-results',
  reporter: [['list'], ['json', { outputFile: '../runtime/playwright-results.json' }]],
  use: { baseURL: 'http://127.0.0.1:4178', channel: 'chromium', headless: true, trace: 'retain-on-failure' },
  webServer: { command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4178 --strictPort', url: 'http://127.0.0.1:4178', reuseExistingServer: false, timeout: 15000 },
});
