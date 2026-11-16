import { fileURLToPath } from 'node:url';
import base from './playwright.config.mjs';

const executablePath = fileURLToPath(new URL('../runtime/browsers/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing', import.meta.url));

export default {
  ...base,
  testMatch: 'factor-mining.spec.mjs',
  outputDir: '../runtime/factor-mining-tests',
  reporter: [['list'], ['json', { outputFile: '../runtime/factor-mining-tests/results.json' }]],
  use: { ...base.use, channel: undefined, launchOptions: { executablePath }, baseURL: process.env.FACTOR_MINING_TEST_BASE_URL || 'http://localhost:7270' },
};
