import { useEffect, useRef, useState } from 'react';
import type { FormEvent, MouseEvent } from 'react';
import { AggregateTable, Badge, Empty, Icon, Notice } from './components';
import { label, metricLabel, number, time } from './format';
import type { Comparison, DatasourceResponse, MetricDefinition } from './types';
import { useDatasource } from './useDatasource';
import TextChanges from './TextChanges';
import SourcesView from './SourcesView';
import ExecutionsView from './ExecutionsView';
import AcquisitionComparisonView from './AcquisitionComparison';
import AcquisitionTrace from './AcquisitionTrace';
import OverviewView from './OverviewView';
import WorkspaceChrome from './WorkspaceChrome';

type View = 'overview' | 'runs' | 'evidence' | 'comparisons';
const views: Array<{ id: View; title: string; icon: 'sources' | 'compare' | 'layers' }> = [
  { id: 'overview', title: 'Overview', icon: 'layers' },
  { id: 'runs', title: 'Runs', icon: 'layers' },
  { id: 'evidence', title: 'Evidence', icon: 'sources' },
  { id: 'comparisons', title: 'Comparisons', icon: 'compare' },
];
const viewAliases: Record<string, View> = {
  overview: 'overview', consistency: 'overview', runs: 'runs', executions: 'runs',
  evidence: 'evidence', sources: 'evidence', comparisons: 'comparisons', comparison: 'comparisons',
};

function initialSubject(): string {
  return new URLSearchParams(window.location.search).get('subject')?.trim().slice(0, 80) || 'NOW';
}

function initialView(): View {
  return viewAliases[new URLSearchParams(window.location.search).get('view') ?? ''] ?? 'overview';
}

function Loading() {
  return <div className="loading-state" role="status" aria-label="Loading datasource"><div className="skeleton skeleton-heading" /><div className="skeleton skeleton-line" />{[1, 2, 3, 4, 5].map(id => <div className="skeleton skeleton-row" key={id} />)}<span className="sr-only">Loading datasource records…</span></div>;
}


function Delta({ value }: { value: number | null | undefined }) {
  const direction = value == null ? 'unknown' : value > 0 ? 'increase' : value < 0 ? 'decrease' : 'unchanged';
  return <span className={`delta delta-${direction}`}>{value == null ? null : <Icon name={value > 0 ? 'plus' : value < 0 ? 'minus' : 'check'} size={13} />}<span>{value == null ? 'Unknown' : number(Math.abs(value))}</span><span className="sr-only">{value == null ? '' : ` ${direction}`}</span></span>;
}

function ComparisonDetail({ comparison, definitions }: { comparison: Comparison; definitions?: Record<string, MetricDefinition> }) {
  const keys = [...new Set(comparison.rows.flatMap(row => [...Object.keys(row.A.metrics), ...Object.keys(row.B.metrics), ...Object.keys(row.differences)]))];
  const [metricKey, setMetricKey] = useState('');
  const metric = keys.includes(metricKey) ? metricKey : keys[0];
  const comparable = metric ? comparison.rows.filter(row => typeof row.A.metrics[metric] === 'number' && typeof row.B.metrics[metric] === 'number') : [];
  const allEqual = comparable.length > 0 && comparable.every(row => row.A.metrics[metric] === row.B.metrics[metric]);
  const unit = metric ? definitions?.[metric]?.unit ?? 'Unit not recorded' : '';
  const unitLabel = unit === 'rubric_0_2' ? '0–2 rubric points' : unit === 'currency_unknown' ? 'Currency not recorded' : unit;
  return <section className="comparison-section"><div className="section-heading"><div><h2>{comparison.title}</h2><p className="subtle">{comparison.scope}</p><p className="subtle">Captured review gate: {label(comparison.status)}. This is not the execution verdict.</p></div>{comparison.conclusion?.status === 'limited' ? <Badge value="partial">Limited comparison</Badge> : <Badge value={comparison.status} />}</div>
    {comparison.limitations.length ? <Notice kind="warning" title="Interpretation boundary"><ul className="plain-list">{comparison.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></Notice> : null}
    {comparison.rows.length && comparison.conclusion ? <Notice kind={comparison.conclusion.status === 'limited' ? 'warning' : 'info'} title="Review, execution, and order checks"><p>{number(comparison.conclusion.noncompleted_executions)} of {number(comparison.rows.length * 2)} original executions did not complete. Preference changed across review order in {number(comparison.conclusion.preference_disagreements)} cases; scores changed in {number(comparison.conclusion.score_disagreements)} cases. Order evidence is available for {number(comparison.conclusion.review_order_known)} of {number(comparison.rows.length)} cases. A review pass does not establish execution completion or acquisition quality.</p></Notice> : null}
    <div className="arm-grid">{comparison.arms.map((arm, index) => <section className={`arm arm-${index % 2 === 0 ? 'a' : 'b'}`} key={arm.id}><div className="arm-title"><h3><span className="arm-letter">{index === 0 ? 'A' : index === 1 ? 'B' : index + 1}</span>Arm {arm.id}</h3><Badge value={arm.status}>Review {label(arm.status).toLowerCase()}</Badge></div><p className="subtle">{arm.expected_cases !== undefined ? `Graded ${number(arm.graded_cases)} of ${number(arm.expected_cases)} expected cases. ` : ''}Metric denominator: {number(arm.denominator)} {arm.denominator_scope ? label(arm.denominator_scope).toLowerCase() : 'recorded cases'}.</p>{arm.errors?.length ? <p className="arm-errors">Recorded error: {arm.errors.join(', ')}</p> : null}<AggregateTable metrics={arm.metrics} definitions={definitions} caption={`${arm.id} aggregate evaluation metrics`} />{arm.receipt_sha256 ? <details className="arm-receipt"><summary>Grading receipt SHA-256</summary><code>{arm.receipt_sha256}</code></details> : null}</section>)}</div>
    <div className="case-header"><div><h3>Matched case differences</h3><p className="subtle">Difference is A minus B. An increase is not automatically an improvement.</p></div>{keys.length ? <div className="metric-select"><label htmlFor={`metric-${comparison.id}`}>Metric</label><select id={`metric-${comparison.id}`} value={metric} onChange={event => setMetricKey(event.target.value)}>{keys.map(key => <option key={key} value={key}>{metricLabel(key, definitions)}</option>)}</select></div> : null}</div>
    {metric ? <div className="selected-metric" role="status" aria-live="polite" aria-atomic="true"><p><strong>Showing: {metricLabel(metric, definitions)}</strong><span>Unit: {unitLabel}</span></p><p>{number(comparable.length)} of {number(comparison.rows.length)} pairs have both values.{allEqual ? ' All known paired values are equal; this metric does not distinguish the arms in this captured cohort.' : ''}</p></div> : null}
    {comparison.rows.length && metric ? <div className="table-wrap" role="region" aria-label={`Matched cases for ${metricLabel(metric, definitions)}`} tabIndex={0}><table className="data-table comparison-table"><caption className="sr-only">Matched cases for {metricLabel(metric, definitions)}, raw recorded units</caption><thead><tr><th>Case</th><th className="a-heading">A value</th><th className="b-heading">B value</th><th>A − B</th><th>Review / execution</th><th>Order check</th></tr></thead><tbody>{comparison.rows.map(row => <tr key={row.case_id}><th scope="row">{row.case_id}</th><td className="numeric a-value">{number(row.A.metrics[metric])}</td><td className="numeric b-value">{number(row.B.metrics[metric])}</td><td><Delta value={row.differences[metric]} /></td><td><div className="grading-status">{(['A', 'B'] as const).map(arm => <div className="arm-result" key={arm}><strong>{arm}</strong><span className="arm-review"><Badge value={row[arm].review_status ?? row[arm].status}>Review {(row[arm].review_status ?? row[arm].status).replaceAll('_', ' ')}</Badge></span><span className="arm-runtime"><Badge value={row[arm].runtime_status ?? 'unknown'}>Execution {(row[arm].runtime_status ?? 'unknown').replaceAll('_', ' ')}</Badge></span>{row[arm].pipeline_reason ? <span className="pipeline-reason">{row[arm].pipeline_reason}</span> : null}</div>)}</div></td><td><div className="review-order"><Badge value={row.review_order?.status === 'disagreement' ? 'partial' : row.review_order?.status === 'consistent' ? 'verified' : 'unknown'}>{row.review_order?.status === 'disagreement' ? 'Disagrees' : row.review_order?.status === 'consistent' ? 'Consistent' : 'Unavailable'}</Badge>{row.review_order?.preferences.length ? <span className="cell-subtext">Preference: {row.review_order.preferences.join(' / ')}</span> : null}{row.review_order?.score_disagreements.length ? <span className="cell-subtext">Changed scores: {row.review_order.score_disagreements.map(key => metricLabel(key, definitions)).join(', ')}</span> : null}</div></td></tr>)}</tbody></table></div> : <Empty title="No matched case values recorded">This comparison has no case-level metric data. Failed grading and missing values remain unknown.</Empty>}
    {metric && definitions?.[metric] ? <p className="metric-caveat"><strong>{metricLabel(metric, definitions)}:</strong> {definitions[metric].unit ?? 'Unit unknown'}. {definitions[metric].caveat}</p> : null}
    {comparison.rows.length ? <TextChanges comparison={comparison} /> : null}
  </section>;
}

function ComparisonView({ data }: { data: DatasourceResponse }) {
  const requested = new URLSearchParams(window.location.search).get('comparison') ?? '';
  const [selection, setSelection] = useState(requested);
  const selected = selection ? data.comparisons.find(item => item.id === selection) : data.comparisons.at(-1);
  function selectComparison(id: string) {
    setSelection(id);
    const next = new URL(window.location.href);
    next.searchParams.set('comparison', id);
    next.searchParams.delete('collection');
    window.history.replaceState(null, '', next);
  }
  return <div className="analysis-view"><div className="analysis-intro"><div><h2>Comparisons</h2><p>Side-by-side results from controlled A/B evaluations, with limitations kept next to each outcome.</p></div>{data.comparisons.length > 1 ? <div className="comparison-select"><label htmlFor="comparison-select">Comparison</label><select id="comparison-select" value={selected?.id ?? ''} onChange={event => selectComparison(event.target.value)}>{data.comparisons.map(item => <option key={item.id} value={item.id}>{item.title} — {item.id}</option>)}</select></div> : null}</div>
    <Notice title="Evidence, not a predictive claim"><p>{selected?.acquisition ? 'The current native acquisition pair is separate from the older fixed-packet answer cohort. ' : selected?.rows.length ? `The ${number(selected.rows.length)} matched ${data.subject} questions form one company cohort. ` : ''}Captured regrades and original failed grading are separate evidence. Correlated questions from one company are not independent evidence of investment performance.</p></Notice>
    {selected?.driver_trace ? <AcquisitionTrace key={selected.id} trace={selected.driver_trace} /> : selected?.acquisition ? <AcquisitionComparisonView key={selected.id} comparison={selected} /> : selected ? <ComparisonDetail key={selected.id} comparison={selected} definitions={data.metric_definitions} /> : <Empty title={selection ? 'Comparison not found in this snapshot' : 'No A/B comparison recorded'}>{selection ? `No comparison matches ${selection}. Choose another recorded comparison.` : 'Research runs remain available in Runs. A comparison will appear when matched evaluation evidence is available.'}</Empty>}
  </div>;
}

export default function App() {
  const [startingSubject] = useState(initialSubject);
  const { data, subject, loading, error, loadSubject, refresh, page } = useDatasource(startingSubject);
  const [draftSubject, setDraftSubject] = useState(startingSubject);
  const [subjectError, setSubjectError] = useState('');
  const [view, setView] = useState<View>(initialView);
  const activeViewRef = useRef<HTMLAnchorElement | null>(null);
  const stale = data?.projection_state === 'stale' || Boolean(error && data);

  useEffect(() => {
    const syncView = () => { setView(initialView()); setDraftSubject(initialSubject()); };
    window.addEventListener('popstate', syncView);
    return () => window.removeEventListener('popstate', syncView);
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const active = activeViewRef.current;
      const navigation = active?.parentElement;
      if (!active || !navigation) return;
      const activeBounds = active.getBoundingClientRect();
      const navigationBounds = navigation.getBoundingClientRect();
      if (activeBounds.right > navigationBounds.right) navigation.scrollLeft += activeBounds.right - navigationBounds.right + 8;
      else if (activeBounds.left < navigationBounds.left) navigation.scrollLeft -= navigationBounds.left - activeBounds.left + 8;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [view]);

  function selectView(event: MouseEvent<HTMLAnchorElement>, nextView: View) {
    event.preventDefault();
    if (nextView === view) return;
    const next = new URL(window.location.href);
    next.pathname = '/datasource';
    next.searchParams.set('view', nextView);
    window.history.pushState(null, '', next);
    setView(nextView);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = draftSubject.trim();
    if (!next || next.length > 80) { setSubjectError('Enter a subject using 1–80 characters.'); return; }
    setSubjectError('');
    loadSubject(next);
  }

  return <><a className="skip-link" href="#main-content">Skip to research observability</a><WorkspaceChrome active="research" />
    <main className="research-page" id="main-content"><div className="page-heading"><div><h1>Research observability</h1><p>Trace research to its evidence, inspect source gaps and compare recorded outcomes.</p></div><form className="subject-form" onSubmit={submit}><div><label htmlFor="subject">Subject</label><input id="subject" value={draftSubject} maxLength={80} autoComplete="off" spellCheck={false} aria-invalid={Boolean(subjectError)} aria-describedby={subjectError ? 'subject-error' : undefined} onChange={event => setDraftSubject(event.target.value)} /></div><button type="submit" className="button button-primary">Load subject</button></form>{subjectError ? <p className="field-error" id="subject-error">{subjectError}</p> : null}</div>
      <div className="dataset-bar"><div className="dataset-context"><span className="subject-pill">{subject}</span>{data ? <><span>{number((data.pagination.total_batches ?? 0) + data.pagination.total_runs + (data.pagination.total_native_collections ?? 0))} runs</span><span>{number(data.pagination.total_sources)} evidence records</span><span>{number(data.comparisons.length)} comparisons</span><Badge value={stale ? 'partial' : data.status}>{stale ? 'Retained snapshot' : data.status === 'ok' ? 'Snapshot complete' : data.status === 'partial' ? 'Partial data' : 'Unavailable'}</Badge></> : <span>{loading ? 'Loading records…' : 'No snapshot loaded'}</span>}</div><button className="button button-secondary refresh-button" onClick={refresh} disabled={loading}><Icon name="refresh" />{loading ? 'Loading…' : 'Refresh'}</button></div>
      {error ? <Notice kind="error" title="Refresh failed"><p>{error}{data ? ' The last successfully loaded snapshot is still displayed below.' : ''}</p></Notice> : null}
      {stale && !error ? <div role="status"><Notice kind="warning" title="Research snapshot is stale"><p>Showing retained evidence from {time(data?.generated_at)}. Refresh to verify the current state; completeness and freshness are separate.</p></Notice></div> : null}
      {data?.status === 'partial' || data?.status === 'unavailable' ? <Notice kind="warning" title={data.status === 'partial' ? 'Partial evidence available' : 'Evidence unavailable'}><p>Some requested records or measurements are missing. Inspect the recorded limitations before interpreting results.</p>{data.warnings.length ? <details><summary>Recorded warnings ({data.warnings.length})</summary><ul className="plain-list">{data.warnings.map((warning, index) => <li key={index}>{label(warning.code)}: {number(warning.count)}</li>)}</ul></details> : null}</Notice> : null}
      <nav className="view-nav" aria-label="Research observability views">{views.map(item => { const href = new URL(window.location.href); href.pathname = '/datasource'; href.searchParams.set('view', item.id); return <a key={item.id} ref={view === item.id ? activeViewRef : undefined} href={`${href.pathname}${href.search}`} aria-current={view === item.id ? 'page' : undefined} onClick={event => selectView(event, item.id)}><Icon name={item.icon} />{item.title}{data && item.id === 'comparisons' ? <span className="nav-count">{data.comparisons.length}</span> : null}</a>; })}</nav>
      <div aria-busy={loading} className={loading && data ? 'content-refreshing' : undefined}>{data ? view === 'overview' ? <OverviewView key={data.subject} data={data} /> : view === 'runs' ? <ExecutionsView key={data.subject} data={data} loading={loading} page={page} /> : view === 'evidence' ? <SourcesView key={data.subject} data={data} loading={loading} page={page} /> : <ComparisonView key={data.subject} data={data} /> : loading ? <Loading /> : <Empty title="Research evidence is not available">Refresh to retry the local API, or load a different subject.</Empty>}</div>
      {data ? <footer className="snapshot-footer"><span>Snapshot generated {time(data.generated_at)}</span><details><summary>Snapshot identity</summary><code>{data.snapshot_id}</code></details><span>No evidence is modified by this workspace.</span></footer> : null}
    </main></>;
}
