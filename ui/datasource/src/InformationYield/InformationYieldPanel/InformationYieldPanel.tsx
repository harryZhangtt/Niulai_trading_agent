import { type CSSProperties } from 'react';
import { Badge, Empty, Notice } from '../../components';
import { useInformationYield } from '../useInformationYield';
import { useInformationYieldV5 } from '../useInformationYieldV5';
import type { InformationYieldCase, InformationYieldErrorKind, InformationYieldObservation } from '../viewModels';
import styles from './InformationYieldPanel.module.css';

function selection() {
  const params = new URLSearchParams(location.search);
  return {
    evaluation: params.get('evaluation'),
    caseId: params.get('case'),
    arm: params.get('arm'),
    run: params.get('run'),
    source: params.get('source'),
    version: params.get('information_yield_version') === '5' ? 5 : 4,
  };
}

function query(value: ReturnType<typeof selection>, detail = false) {
  if (!value.evaluation || detail && !value.caseId) return null;
  const params = new URLSearchParams({ evaluation: value.evaluation });
  if (detail) {
    params.set('case', value.caseId!);
    if (value.arm) params.set('arm', value.arm);
    if (value.run) params.set('run', value.run);
    if (value.source) params.set('source', value.source);
  }
  return params.toString();
}

function displayValue(value: InformationYieldObservation) {
  return value.state === 'known'
    ? `${value.value.toLocaleString()} ${value.unit.replaceAll('_', ' ')}`
    : `${value.state.replace('_', ' ')} — ${value.reasonCode.replaceAll('_', ' ')}`;
}

function numeric(value: InformationYieldObservation) {
  return value.state === 'known' ? value.value : null;
}

function errorText(kind: InformationYieldErrorKind) {
  if (kind === 'permission_denied') return 'You do not have permission to view this information-yield evaluation. No empty or alternate result was substituted.';
  if (kind === 'not_found') return 'The exact evaluation or drilldown identity was not found. No alternate record was substituted.';
  if (kind === 'conflict') return 'The immutable identity conflicted with the requested snapshot.';
  if (kind === 'timeout') return 'The information-yield request timed out. The last exact-identity snapshot remains visible when available.';
  if (kind === 'schema_invalid') return 'The information-yield response failed its local schema boundary.';
  return 'Information-yield evidence is unavailable from the local read-only service.';
}

function errorTitle(kind: InformationYieldErrorKind, detail = false) {
  if (kind === 'permission_denied') return detail ? 'Drilldown access denied' : 'Information-yield access denied';
  return detail ? 'Requested drilldown unavailable' : 'Information-yield evidence unavailable';
}

function href(value: ReturnType<typeof selection>, caseId: string, arm?: 'B0' | 'F') {
  const url = new URL(location.href);
  url.searchParams.set('evaluation', value.evaluation!);
  url.searchParams.set('case', caseId);
  if (arm) url.searchParams.set('arm', arm);
  else url.searchParams.delete('arm');
  url.searchParams.delete('run');
  url.searchParams.delete('source');
  return `${url.pathname}${url.search}`;
}

function PairPlot({ label, unit, cases, select }: { label: string; unit: string; cases: InformationYieldCase[]; select: ReturnType<typeof selection> }) {
  const values = cases.map(item => numeric(label === 'Richness' ? item.deltaRichness : item.deltaDepth));
  const maximum = Math.max(1, ...values.map(value => Math.abs(value ?? 0)));
  const id = `information-yield-${label.toLowerCase()}`;
  return <section className={styles.plot} aria-labelledby={`${id}-title`}>
    <h4 id={`${id}-title`}>{label} paired delta</h4>
    <p className={styles.plotSummary} id={`${id}-summary`}>Centered bars show each case&apos;s signed delta in {unit}. Exact values and drilldown links follow.</p>
    <div className={styles.marks} role="img" aria-labelledby={`${id}-title ${id}-summary`}>
      {cases.map((row, index) => {
        const value = values[index];
        const size = value === null ? 0 : Math.min(50, Math.abs(value) / maximum * 50);
        return <div className={styles.mark} aria-hidden="true" key={row.id}>
          <span className={styles.markLabel}>{row.id}</span>
          <span className={styles.track}><span className={`${styles.bar}${value !== null && value < 0 ? ` ${styles.negative}` : ''}`} style={{ '--bar-size': String(size) } as CSSProperties} /></span>
          <strong>{value === null ? '—' : value > 0 ? `+${value}` : value}</strong>
        </div>;
      })}
    </div>
    <ul className={styles.plotLinks} aria-label={`${label} case drilldowns`}>
      {cases.map(row => <li key={row.id}><a href={href(select, row.id)}>Open {row.id} detail</a></li>)}
    </ul>
  </section>;
}

export default function InformationYieldPanel() {
  const select = selection();
  const summaryV4 = useInformationYield(select.version === 4 ? query(select) : null);
  const detailV4 = useInformationYield(select.version === 4 ? query(select, true) : null);
  const summaryV5 = useInformationYieldV5(select.version === 5 ? query(select) : null);
  const detailV5 = useInformationYieldV5(select.version === 5 ? query(select, true) : null);
  const summary = select.version === 5 ? summaryV5 : summaryV4;
  const detail = select.version === 5 ? detailV5 : detailV4;

  if (!select.evaluation) return <section className={styles.panel} aria-labelledby="information-yield-title">
    <div className={styles.header}><div><h3 id="information-yield-title">Information yield</h3><p className="subtle">Paired acquisition quality remains unavailable until an exact evaluation identity is selected.</p></div></div>
    <Empty title="No information-yield evaluation selected">Add an exact evaluation link to inspect a frozen provider-free result. No latest result is selected automatically.</Empty>
  </section>;

  const data = summary.data;
  const chosen = select.caseId ? detail.data : null;
  const failureCount = data?.hardFailures.length ?? 0;
  const lineage = data?.gates.find(gate => gate.name.includes('lineage'));
  const cases = data?.cases ?? [];
  const refresh = () => {
    summary.refresh();
    if (select.caseId) detail.refresh();
  };

  return <section className={styles.panel} aria-labelledby="information-yield-title" aria-busy={summary.loading || detail.loading}>
    <div className={styles.header}>
      <div><h3 id="information-yield-title">Information yield</h3><p className="subtle">Provider-free paired evidence. Richness and depth remain separate co-primary outcomes.</p></div>
      <button className="button button-secondary" onClick={refresh} disabled={summary.loading || detail.loading}>{summary.loading || detail.loading ? 'Refreshing…' : 'Refresh'}</button>
    </div>
    {summary.error ? <Notice kind="error" title={errorTitle(summary.error)}><p>{errorText(summary.error)}{data ? ' The last exact-identity snapshot remains visible.' : ''}</p></Notice> : null}
    {detail.error && select.caseId ? <Notice kind="error" title={errorTitle(detail.error, true)}><p>{errorText(detail.error)}</p></Notice> : null}
    {!data
      ? summary.loading
        ? <div className={styles.loading} role="status">Loading the exact immutable evaluation…</div>
        : summary.error === 'permission_denied'
          ? null
          : <Empty title="Evaluation unavailable">No quality conclusion is inferred from missing evidence.</Empty>
      : <>
        {failureCount || data.verdict === 'reject' ? <div><Notice kind="error" title={`Evaluation rejected${failureCount ? ` — ${failureCount} hard ${failureCount === 1 ? 'failure' : 'failures'}` : ''}`}><p>Hard failures and decisive safeguards override favorable outcome deltas. Recorded codes: {data.hardFailures.map(failure => failure.code).join(', ') || 'policy safeguard failure'}.</p></Notice></div> : null}
        {data.stale ? <Notice kind="warning" title="Retained exact-identity snapshot"><p>The refresh failed. This retained result is never substituted across evaluation identities.</p></Notice> : null}
        <div className={styles.banner} aria-label="Evaluation evidence banner">
          <div><span>Verdict</span><strong><Badge value={data.verdict}>{data.verdict}</Badge></strong></div>
          <div><span>Planned cases</span><strong>{data.counts.planned}</strong></div>
          <div><span>Confirmation / development</span><strong>{data.counts.confirmation} / {data.counts.development}</strong></div>
          <div><span>Evidence boundary</span><strong>{select.version === 5 ? 'Custody-backed v5' : 'Provider-free v4'}</strong></div>
        </div>
        <div className={styles.hashes}><span>Context {data.evidence.contextSha256}</span><span>Policy {data.evidence.policySha256}</span><span>Source closure {data.evidence.sourceClosureSha256}</span></div>
        <div className={styles.cards}>
          <article className={styles.card}><span>Richness mean paired delta</span><strong>{displayValue(data.outcomes.richness.mean)}</strong><small>{data.outcomes.richness.denominator} evaluable cases · {data.outcomes.richness.wins} wins, {data.outcomes.richness.ties} ties, {data.outcomes.richness.losses} losses</small></article>
          <article className={styles.card}><span>Depth mean paired delta</span><strong>{displayValue(data.outcomes.depth.mean)}</strong><small>{data.outcomes.depth.denominator} evaluable cases · {data.outcomes.depth.wins} wins, {data.outcomes.depth.ties} ties, {data.outcomes.depth.losses} losses</small></article>
        </div>
        <article className={styles.lineage}><span>Lineage safeguard</span><strong>{lineage ? `${lineage.status} — ${lineage.observed}` : 'Unavailable — no lineage gate'}</strong></article>
        {cases.length >= 2 ? <div className={styles.plots}><PairPlot label="Richness" unit="canonical units" cases={cases} select={select} /><PairPlot label="Depth" unit="field-state steps" cases={cases} select={select} /></div> : <p className="subtle">The paired plot requires at least two evaluable cases. The semantic table remains available.</p>}
        <div className={styles.tableWrap} role="region" aria-label="Paired information-yield outcomes" tabIndex={0}>
          <table className={styles.table}>
            <caption className="sr-only">Raw B0 and F outcomes and paired deltas</caption>
            <thead><tr><th>Case</th><th>Issuer / window</th><th>B0 richness</th><th>F richness</th><th>Δ richness</th><th>B0 depth</th><th>F depth</th><th>Δ depth</th></tr></thead>
            <tbody>{cases.map(row => <tr key={row.id}><td><a href={href(select, row.id)}>{row.id}</a></td><td>{row.issuerId} / {row.windowId}</td><td>{displayValue(row.arms.B0.richness)}</td><td>{displayValue(row.arms.F.richness)}</td><td>{displayValue(row.deltaRichness)}</td><td>{displayValue(row.arms.B0.depth)}</td><td>{displayValue(row.arms.F.depth)}</td><td>{displayValue(row.deltaDepth)}</td></tr>)}</tbody>
          </table>
        </div>
        <div className={styles.diagnostics}>
          <details><summary>Policy safeguards and diagnostics</summary><div className={styles.tableWrap} role="region" aria-label="Policy safeguards" tabIndex={0}><table className={`${styles.table} ${styles.gateTable}`}><caption className="sr-only">Policy safeguard status, observed value, and threshold</caption><thead><tr><th scope="col">Gate</th><th scope="col">Status</th><th scope="col">Observed</th><th scope="col">Threshold</th></tr></thead><tbody>{data.gates.map(gate => <tr key={gate.name}><th scope="row">{gate.name.replaceAll('_', ' ')}</th><td><Badge value={gate.status}>{gate.status}</Badge></td><td>{gate.observed}</td><td>{gate.threshold}</td></tr>)}</tbody></table></div></details>
          <details><summary>Claim limits</summary><ul>{data.evidence.claimLimits.map(limit => <li key={limit}>{limit.replaceAll('_', ' ')}</li>)}</ul></details>
        </div>
        {select.caseId ? <article className={styles.detail} aria-labelledby="information-yield-detail-title">
          <h4 id="information-yield-detail-title">Exact case drilldown</h4>
          {chosen?.selectedCase ? <>
            <p><strong>{chosen.selectedCase.id}</strong> · {chosen.selectedCase.issuerId} · {chosen.selectedCase.windowId}</p>
            <p>Richness Δ {displayValue(chosen.selectedCase.deltaRichness)} · Depth Δ {displayValue(chosen.selectedCase.deltaDepth)}</p>
            <div className={styles.detailActions}><a className="button button-secondary" href={href(select, chosen.selectedCase.id, 'B0')}>Inspect B0 arm</a><a className="button button-secondary" href={href(select, chosen.selectedCase.id, 'F')}>Inspect F arm</a></div>
            {chosen.selectedArm ? <p>Selected arm: richness {displayValue(chosen.selectedArm.richness)}; depth {displayValue(chosen.selectedArm.depth)}; precision {displayValue(chosen.selectedArm.precision)}.</p> : null}
            <p className="subtle">Run and source links remain withheld because the bounded {select.version === 5 ? 'v5 custody' : 'v4 result'} does not prove global lookup identities.</p>
          </> : detail.loading ? <p role="status">Loading exact case evidence…</p> : <p>No alternate case was substituted.</p>}
        </article> : null}
      </>}
  </section>;
}
