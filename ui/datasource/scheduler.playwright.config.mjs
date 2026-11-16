import base from './playwright.config.mjs';

export default {
  ...base, testMatch: 'scheduler.spec.mjs',
  outputDir: '../runtime/scheduler-tests',
  reporter: [['list'], ['json', {outputFile:'../runtime/scheduler-tests/results.json'}]],
  use: {...base.use, baseURL:process.env.SCHEDULER_TEST_BASE_URL || 'http://localhost:7270'},
};
