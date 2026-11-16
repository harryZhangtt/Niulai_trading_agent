import { fileURLToPath } from 'node:url';
import base from './playwright.config.mjs';

const executablePath = fileURLToPath(new URL('../runtime/browsers/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing', import.meta.url));

export default {
  ...base,
  testMatch: 'acquisition-trace.spec.mjs',
  outputDir: '../runtime/acquisition-trace-tests',
  reporter: [['list'], ['json', { outputFile: '../runtime/acquisition-trace-tests/results.json' }]],
  use: { ...base.use, channel: undefined, launchOptions: { executablePath } },
};
