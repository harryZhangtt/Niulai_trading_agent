import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const exec = promisify(execFile);
const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const command = path.join(workspace, 'ui/skills/design-md-chrome/scripts/extract.mjs');
const environment = { ...process.env, TMPDIR: path.join(workspace, 'ui/runtime/tmp') };

test('real DOM extraction generates reviewed tokens without page prose or URL query', async () => {
  const canary = 'SYNTHETIC_PAGE_PRIVATE_CANARY';
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/html' });
    response.end(`<!doctype html><html><head><title>${canary}</title><style>
      body{font-family:Georgia,serif;color:#123456;background:#f0ead6;padding:16px}
      button{font-family:Georgia,serif;padding:16px;border-radius:12px;background:#123456;color:white}
      </style></head><body><header>${canary}</header><h1>Reference</h1>
      <main><p>Useful content ${canary}</p><button>Continue</button><input value="${canary}"></main></body></html>`);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let output;
  try {
    const port = server.address().port;
    const result = await exec(process.execPath, [command, '--url', `http://127.0.0.1:${port}/?secret=${canary}#${canary}`],
      { cwd: workspace, env: environment, timeout: 45000 });
    assert.equal(result.stderr, '');
    const receipt = JSON.parse(result.stdout);
    assert.equal(receipt.status, 'DESIGN_MD_OK');
    assert.ok(receipt.sampledElements >= 5);
    assert.ok(receipt.output.startsWith('ui/runtime/design-md/extract-'));
    output = path.join(workspace, receipt.output);
    const files = await Promise.all(['DESIGN.md', 'SKILL.md', 'tokens.json'].map(name => readFile(path.join(output, name), 'utf8')));
    assert.ok(files[0].includes('#123456'));
    assert.ok(files[0].includes('Georgia'));
    for (const file of files) {
      assert.ok(!file.includes(canary));
      assert.ok(!file.includes('?secret='));
    }
  } finally {
    await new Promise(resolve => server.close(resolve));
    if (output) await rm(output, { recursive: true, force: true });
  }
});

test('credentials in URLs are rejected without exposing them', async () => {
  await assert.rejects(exec(process.execPath, [command, '--url', 'https://user:SYNTHETIC_URL_SECRET@example.com/'],
    { cwd: workspace, env: environment, timeout: 5000 }), error => {
      assert.equal(error.stdout, '');
      assert.deepEqual(JSON.parse(error.stderr), { status: 'DESIGN_MD_FAILED', code: 'URL' });
      return true;
    });
});

test('page failure produces a visible sanitized error, never an empty success', async () => {
  const server = http.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  await assert.rejects(exec(process.execPath, [command, '--url', `http://127.0.0.1:${port}/?token=SYNTHETIC_QUERY_SECRET`],
    { cwd: workspace, env: environment, timeout: 45000 }), error => {
      assert.equal(error.stdout, '');
      assert.deepEqual(JSON.parse(error.stderr), { status: 'DESIGN_MD_FAILED', code: 'DEPENDENCY_OR_PAGE' });
      return true;
    });
});
