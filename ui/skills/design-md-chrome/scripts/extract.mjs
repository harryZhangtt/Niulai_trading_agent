import { readFile, realpath, mkdir, mkdtemp, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { normalizeExtractedStyles } from '../lib/normalize.mjs';
import { generateDesignMarkdown } from '../lib/generate-design-md.mjs';
import { generateSkillMarkdown } from '../lib/generate-skill-md.mjs';
import { validateMarkdownOutput } from '../lib/validate.mjs';

const skill = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ui = path.resolve(skill, '../..');
const workspace = path.dirname(ui);
let browser;
let output;
try {
  if (process.argv.length !== 4 || process.argv[2] !== '--url') throw new Error('ARGUMENTS');
  const url = new URL(process.argv[3]);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('URL');
  const runtime = path.join(ui, 'runtime');
  if ((await realpath(ui)) !== ui) throw new Error('PATH');
  await mkdir(runtime, { recursive: true });
  if ((await realpath(runtime)) !== runtime) throw new Error('PATH');
  const home = path.join(runtime, 'design-md');
  await mkdir(home, { recursive: true });
  if ((await realpath(home)) !== home) throw new Error('PATH');
  for (const [key, directory] of Object.entries({ TMPDIR: 'tmp', XDG_CACHE_HOME: 'cache', XDG_CONFIG_HOME: 'config' })) {
    const target = path.join(runtime, directory);
    await mkdir(target, { recursive: true });
    if ((await realpath(target)) !== target) throw new Error('PATH');
    process.env[key] = target;
  }
  process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(runtime, 'browsers');
  const { chromium } = await import(pathToFileURL(path.join(ui, 'verification/node_modules/@playwright/test/index.mjs')));
  browser = await chromium.launch({ headless: true, timeout: 15000 });
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  await page.goto(url.href, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.evaluate(() => {
    // Only the message-registration surface is shimmed; extraction reads a real DOM.
    window.chrome = { runtime: { onMessage: { addListener(callback) { window.__typeuiExtract = callback; } } } };
  });
  await page.addScriptTag({ content: await readFile(path.join(skill, 'content-script.js'), 'utf8') });
  const result = await page.evaluate(() => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('EXTRACTION_TIMEOUT')), 2000);
    window.__typeuiExtract({ type: 'TYPEUI_EXTRACT_STYLES' }, null, result => {
      clearTimeout(timer);
      resolve(result);
    });
  }));
  if (!result?.ok || !result.payload?.sampledElements) throw new Error('EXTRACTION');
  const payload = result.payload;
  // Do not persist page prose, input values, account details or query credentials.
  const safeUrl = new URL(page.url());
  safeUrl.search = ''; safeUrl.hash = ''; safeUrl.username = ''; safeUrl.password = '';
  payload.source = { url: safeUrl.href, title: 'Reference interface' };
  payload.siteSignals = {
    title: 'Reference interface', description: '', keywords: '', ogType: '', ogSiteName: '', appName: '',
    pathname: safeUrl.pathname, hostname: safeUrl.hostname,
    headings: [], navTexts: [], ctaTexts: [], textSample: '',
    elementCounts: payload.siteSignals?.elementCounts ?? {}
  };
  const normalized = normalizeExtractedStyles(payload);
  const contextData = { normalized, metadata: { systemName: 'Reference interface', brand: 'Reference' } };
  const design = generateDesignMarkdown(contextData);
  const generatedSkill = generateSkillMarkdown(contextData);
  if (!validateMarkdownOutput('design', design).isValid || !validateMarkdownOutput('skill', generatedSkill).isValid) throw new Error('VALIDATION');
  await browser.close();
  browser = undefined;
  output = await mkdtemp(path.join(home, 'extract-'));
  await writeFile(path.join(output, 'DESIGN.md'), design, { mode: 0o600 });
  await writeFile(path.join(output, 'SKILL.md'), generatedSkill, { mode: 0o600 });
  await writeFile(path.join(output, 'tokens.json'), JSON.stringify(normalized, null, 2) + '\n', { mode: 0o600 });
  console.log(JSON.stringify({ status: 'DESIGN_MD_OK', output: path.relative(workspace, output), sampledElements: payload.sampledElements }));
} catch (error) {
  if (output) await rm(output, { recursive: true, force: true });
  const code = ['ARGUMENTS', 'URL', 'PATH', 'EXTRACTION', 'VALIDATION'].includes(error.message) ? error.message : 'DEPENDENCY_OR_PAGE';
  console.error(JSON.stringify({ status: 'DESIGN_MD_FAILED', code }));
  process.exitCode = 1;
} finally {
  if (browser) {
    try { await browser.close(); }
    catch {
      console.error(JSON.stringify({ status: 'DESIGN_MD_FAILED', code: 'CLEANUP' }));
      process.exitCode = 1;
    }
  }
}
