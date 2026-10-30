// Three bounded follow-up reads retain quote/trade timestamps omitted by the first summary.
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { withPortal, jsonResult } from './client.mjs';
import { STATE } from './providers.mjs';
import { decodeContract, requireData, summarizeSnapshots, verifySnapshot } from './verification/options.mjs';

const source = path.resolve(process.argv[2] ?? '');
requireData(source.startsWith(path.join(STATE, 'reports') + path.sep) && source.endsWith('.json'), 'invalid_report_path');
const baseline = JSON.parse(await readFile(source, 'utf8'));
requireData(baseline.status === 'pass', 'baseline_did_not_pass');
const report = { startedAt: new Date().toISOString(), baseline: path.basename(source),
  scope: 'Six known contracts, three actual Alpaca reads; retained timestamps and field availability, not an accuracy benchmark',
  productionSourceHashes: {}, observations: [], sourceHashes: {} };
for (const name of ['adapters/alpaca.mjs', 'adapters/massive.mjs']) {
  const hash = createHash('sha256').update(await readFile(new URL('./' + name, import.meta.url))).digest('hex');
  requireData(hash === baseline.sourceHashes[name], 'production_adapter_changed');
  report.productionSourceHashes[name] = hash;
}
for (const name of ['options-freshness.mjs', 'verification/options.mjs']) report.sourceHashes[name] =
  createHash('sha256').update(await readFile(new URL('./' + name, import.meta.url))).digest('hex');
await withPortal('alpaca', async client => {
  for (const underlying of ['AAPL', 'SPY', 'QQQ']) {
    const contracts = baseline.cases.filter(c => c.status === 'pass' && c.name.startsWith(`massive_daily_${underlying}_`)).map(c => c.contract.slice(2));
    requireData(contracts.length === 2, 'missing_baseline_contracts');
    const result = jsonResult(await client.callTool({ name: 'option_snapshots', arguments: { contracts } }, undefined, { timeout: 75000 }));
    for (const symbol of contracts) {
      const snapshot = result.data.snapshots[symbol];
      const observation = verifySnapshot(symbol, snapshot, { underlying });
      report.observations.push({ ...observation, ...decodeContract(symbol),
        quoteAt: snapshot.latestQuote?.t, tradeAt: snapshot.latestTrade?.t,
        feed: result.feed, greekCalculationTimeVerified: result.greeks_timing_verified });
    }
  }
});
report.summary = summarizeSnapshots(report.observations);
report.status = 'pass'; report.processCleanup = 'pass'; report.finishedAt = new Date().toISOString();
const location = source.replace(/\.json$/, '-freshness.json');
await writeFile(location, JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
process.stdout.write(JSON.stringify({ status: report.status, summary: report.summary, report: location }) + '\n');
