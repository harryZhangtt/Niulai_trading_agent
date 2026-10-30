// Public candidate verification, through the existing bounded QueryPortal.
import { QueryPortal } from '../market_data_mcp/core/portal.mjs';
import { arxivResearchTransport, materializeArxivPaper } from '../market_data_mcp/adapters/research-stdio.mjs';
import { writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const STATE = path.join(ROOT, '.niulai-state/reports/research-sources/runtime');
const allowed = ['search_papers', 'download_paper', 'list_papers', 'read_paper', 'get_paper_outline',
  'read_paper_section', 'list_paper_latex_sections', 'read_paper_latex_section'];
let transport;
const portal = new QueryPortal({ provider: 'arxiv-candidate', allowedTools: allowed,
  transportFactory: () => { transport = arxivResearchTransport(); return transport; },
  policy: { maxAttempts: 1, timeoutMs: 55000, totalTimeoutMs: 60000, maxPending: 1 } });
let report = {};
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 90000);
const unwrap = result => {
  if (result.isError) throw new Error('candidate_query_failed');
  if (result.structuredContent) return result.structuredContent;
  const values = result.content.filter(x => x.type === 'text').map(x => {
    try { return JSON.parse(x.text); } catch { return x.text; }
  });
  const value = values.length === 1 ? values[0] : values;
  if (value?.status === 'error' || value?.error) throw new Error('candidate_query_failed');
  return value;
};
try {
  const tools = (await portal.listTools(controller.signal)).tools;
  const manifest = tools.map(t => ({ name: t.name, inputSchema: t.inputSchema, annotations: t.annotations }));
  const state = STATE;
  await mkdir(state, { recursive: true, mode: 0o700 });
  await writeFile(path.join(state, 'arxiv-tools.json'), JSON.stringify(manifest, null, 2), { mode: 0o600 });
  report = { provider: 'arxiv-mcp-server', version: '0.8.2', host_registered: false,
    allowed_tools: tools.map(t => t.name), queried: false };
  if (process.argv[2] === 'inspect') {
    report.schemas = manifest.filter(t => ['download_paper', 'get_paper_outline', 'read_paper_section'].includes(t.name));
  } else {
    const call = async (name, args) => unwrap(await portal.callTool(name, args, controller.signal));
    report.download = unwrap(await materializeArxivPaper('2407.08608v2', controller.signal));
    report.outline = await call('get_paper_outline', { paper_id: '2407.08608v2' });
    const sections = report.outline.sections ?? report.outline.outline ?? [];
    const chosen = sections.find(x => /experiment|evaluation|result/i.test(x.title)) ?? sections[1];
    if (!chosen) throw new Error('section_not_found');
    report.section = await call('read_paper_section', { paper_id: '2407.08608v2', section_id: chosen.id, max_chars: 1200 });
    report.selected_section = chosen;
    if (report.outline.versioned_id !== '2407.08608v2') throw new Error('version_not_confirmed');
    report.queried = true;
  }
} catch {
  report = { ...report, status: 'failed', error: 'CANDIDATE_QUERY_FAILED', automatic_retry: false };
  process.exitCode = 2;
} finally {
  clearTimeout(timer);
  const pid = transport?.pid;
  await portal.close();
  report.process_id = pid;
  report.connection_closed = true;
  report.process_cleanup_verified = false;
  for (let i = 0; i < 40 && pid; i++) {
    try { process.kill(pid, 0); }
    catch (e) { if (e.code === 'ESRCH') { report.process_cleanup_verified = true; break; } throw e; }
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  if (pid && !report.process_cleanup_verified) { process.exitCode = 2; report.status = 'cleanup_failed'; }
}
await writeFile(path.join(STATE, 'arxiv-mcp-probe.json'), JSON.stringify(report, null, 2), { mode: 0o600 });
process.stdout.write(JSON.stringify(process.argv[2] === 'inspect' ? report : {
  provider: report.provider, version: report.version, status: report.status ?? 'ok',
  queried: report.queried, outline_sections: report.outline?.sections?.length,
  selected_section: report.selected_section?.title, section_keys: Object.keys(report.section ?? {}),
  connection_closed: report.connection_closed, process_cleanup_verified: report.process_cleanup_verified,
  host_registered: false }) + '\n');
