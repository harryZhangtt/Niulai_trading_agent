import { useState } from 'react';
import type { FormEvent } from 'react';
import { AggregateTable, Badge, DetailsTree, Empty, Icon, Notice, RunDetails } from './components';
import { display, label, metricLabel, number, time } from './format';
import type { Comparison, DatasourceResponse, MetricDefinition } from './types';
import { useDatasource } from './useDatasource';
import TextChanges from './TextChanges';
import SourcesView from './SourcesView';
import ExecutionsView from './ExecutionsView';
import AcquisitionComparisonView from './AcquisitionComparison';

type View = 'executions' | 'sources' | 'comparison' | 'consistency';
const views: Array<{ id: View; title: string; icon: 'sources' | 'compare' | 'layers' }> = [
  { id: 'executions', title: 'Executions', icon: 'layers' },
  { id: 'sources', title: 'Source ledger', icon: 'sources' },
  { id: 'comparison', title: 'A/B evaluation', icon: 'compare' },
  { id: 'consistency', title: 'Consistency', icon: 'layers' },
];

function initialSubject(): string {
  return new URLSearchParams(window.location.search).get('subject')?.trim().slice(0, 80) || 'NOW';
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
    {comparison.rows.length && metric ? <div className="table-wrap"><table className="data-table comparison-table"><caption className="sr-only">Matched cases for {metricLabel(metric, definitions)}, raw recorded units</caption><thead><tr><th>Case</th><th className="a-heading">A value</th><th className="b-heading">B value</th><th>A − B</th><th>Review / execution</th><th>Order check</th></tr></thead><tbody>{comparison.rows.map(row => <tr key={row.case_id}><th scope="row">{row.case_id}</th><td className="numeric a-value">{number(row.A.metrics[metric])}</td><td className="numeric b-value">{number(row.B.metrics[metric])}</td><td><Delta value={row.differences[metric]} /></td><td><div className="grading-status">{(['A', 'B'] as const).map(arm => <div className="arm-result" key={arm}><strong>{arm}</strong><span className="arm-review"><Badge value={row[arm].review_status ?? row[arm].status}>Review {(row[arm].review_status ?? row[arm].status).replaceAll('_', ' ')}</Badge></span><span className="arm-runtime"><Badge value={row[arm].runtime_status ?? 'unknown'}>Execution {(row[arm].runtime_status ?? 'unknown').replaceAll('_', ' ')}</Badge></span>{row[arm].pipeline_reason ? <span className="pipeline-reason">{row[arm].pipeline_reason}</span> : null}</div>)}</div></td><td><div className="review-order"><Badge value={row.review_order?.status === 'disagreement' ? 'partial' : row.review_order?.status === 'consistent' ? 'verified' : 'unknown'}>{row.review_order?.status === 'disagreement' ? 'Disagrees' : row.review_order?.status === 'consistent' ? 'Consistent' : 'Unavailable'}</Badge>{row.review_order?.preferences.length ? <span className="cell-subtext">Preference: {row.review_order.preferences.join(' / ')}</span> : null}{row.review_order?.score_disagreements.length ? <span className="cell-subtext">Changed scores: {row.review_order.score_disagreements.map(key => metricLabel(key, definitions)).join(', ')}</span> : null}</div></td></tr>)}</tbody></table></div> : <Empty title="No matched case values recorded">This comparison has no case-level metric data. Failed grading and missing values remain unknown.</Empty>}
    {metric && definitions?.[metric] ? <p className="metric-caveat"><strong>{metricLabel(metric, definitions)}:</strong> {definitions[metric].unit ?? 'Unit unknown'}. {definitions[metric].caveat}</p> : null}
    {comparison.rows.length ? <TextChanges comparison={comparison} /> : null}
  </section>;
}

function ComparisonView({ data }: { data: DatasourceResponse }) {
  const [selection, setSelection] = useState('');
  const selected = data.comparisons.find(item => item.id === selection) ?? data.comparisons.at(-1);
  return <div className="analysis-view"><div className="analysis-intro"><div><h2>A/B evaluation</h2><p>Read matched outcomes alongside grader status and the limits of each captured cohort.</p></div>{data.comparisons.length > 1 ? <div className="comparison-select"><label htmlFor="comparison-select">Comparison</label><select id="comparison-select" value={selected?.id ?? ''} onChange={event => setSelection(event.target.value)}>{data.comparisons.map(item => <option key={item.id} value={item.id}>{item.title} — {item.id}</option>)}</select></div> : null}</div>
    <Notice title="Evidence, not a predictive claim"><p>{selected?.acquisition ? 'The current native acquisition pair is separate from the older fixed-packet answer cohort. ' : selected?.rows.length ? `The ${number(selected.rows.length)} matched ${data.subject} questions form one company cohort. ` : ''}Captured regrades and original failed grading are separate evidence. Correlated questions from one company are not independent evidence of investment performance.</p></Notice>
    {selected?.acquisition ? <AcquisitionComparisonView key={selected.id} comparison={selected} /> : selected ? <ComparisonDetail key={selected.id} comparison={selected} definitions={data.metric_definitions} /> : <Empty title="No A/B comparison recorded">Research runs can still be inspected in the source ledger. A comparison will appear when matched evaluation evidence is available.</Empty>}
  </div>;
}

function ConsistencyView({ data }: { data: DatasourceResponse }) {
  const [runId, setRunId] = useState('');
  const [cohortId, setCohortId] = useState('');
  const selected = data.runs.find(run => run.id === runId) ?? data.runs[0];
  const cohort = data.aggregates.cohorts.find(item => item.id === cohortId) ?? data.aggregates.cohorts.find(item => item.id.startsWith('acquisition_batches:')) ?? data.aggregates.cohorts.find(item => item.id.startsWith('pipeline_runs:')) ?? data.aggregates.cohorts[0];
  return <div className="analysis-view"><div className="analysis-intro"><div><h2>Consistency across executions</h2><p>Compare recorded coverage and resource use within explicit cohort boundaries.</p></div><Badge value={data.status} /></div>
    <Notice title="Known values keep their denominator"><p>Missing measurements remain unknown. Cohort means use recorded values and do not establish throughput or predictive improvement beyond the captured runs.</p></Notice>
    {cohort ? <section className="cohort-section"><div className="cohort-selector"><label htmlFor="cohort-select">Aggregate cohort ({data.aggregates.cohorts.length} available)</label><select id="cohort-select" value={cohort.id} onChange={event => setCohortId(event.target.value)}>{data.aggregates.cohorts.map(item => <option key={item.id} value={item.id}>{label(item.id)} — denominator {number(item.denominator)}</option>)}</select></div><div className="section-heading"><div><h3>{label(cohort.id)}</h3><p className="subtle">{cohort.scope}</p></div><span className="record-count">Denominator: {number(cohort.denominator)}</span></div><AggregateTable metrics={cohort.metrics} definitions={data.metric_definitions} caption={`Aggregate metrics for ${cohort.id}`} />{cohort.unknowns != null ? <details className="unknown-details"><summary>Unknowns and missing evidence</summary>{typeof cohort.unknowns === 'object' && !Array.isArray(cohort.unknowns) ? <DetailsTree value={cohort.unknowns as Record<string, unknown>} /> : <p>{display(cohort.unknowns)}</p>}</details> : null}</section> : <Empty title="No aggregate cohorts recorded">Single executions remain available below when run records exist.</Empty>}
    <section className="single-run-section"><div className="section-heading"><div><h3>Single execution</h3><p className="subtle">Inspect the measured path behind an aggregate.</p></div>{data.runs.length ? <div className="single-run-select"><label htmlFor="consistency-run">Execution</label><select id="consistency-run" value={selected.id} onChange={event => setRunId(event.target.value)}>{data.runs.map(run => <option key={run.id} value={run.id}>{run.query || run.id}</option>)}</select></div> : null}</div>{selected ? <RunDetails run={selected} definitions={data.metric_definitions} /> : <p className="unknown-note">No execution records are available for this subject.</p>}</section>
    {data.aggregates.unknowns != null ? <details className="unknown-details"><summary>Dataset-level unknowns</summary>{typeof data.aggregates.unknowns === 'object' && !Array.isArray(data.aggregates.unknowns) ? <DetailsTree value={data.aggregates.unknowns as Record<string, unknown>} /> : <p>{display(data.aggregates.unknowns)}</p>}</details> : null}
  </div>;
}

export default function App() {
  const [startingSubject] = useState(initialSubject);
  const { data, subject, loading, error, loadSubject, refresh, page } = useDatasource(startingSubject);
  const [draftSubject, setDraftSubject] = useState(startingSubject);
  const [subjectError, setSubjectError] = useState('');
  const [view, setView] = useState<View>('executions');

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = draftSubject.trim();
    if (!next || next.length > 80) { setSubjectError('Enter a subject using 1–80 characters.'); return; }
    setSubjectError('');
    loadSubject(next);
  }

  return <><a className="skip-link" href="#main-content">Skip to datasource</a><header className="app-header"><a className="app-identity" href="/datasource"><span className="identity-symbol"><Icon name="layers" size={23} /></span><span>Research operations</span></a><span className="read-only"><span aria-hidden="true" />Read-only workspace</span></header>
    <main id="main-content"><div className="page-heading"><div><h1>Datasource</h1><p>Trace the evidence behind a research result.</p></div><form className="subject-form" onSubmit={submit}><div><label htmlFor="subject">Subject</label><input id="subject" value={draftSubject} maxLength={80} autoComplete="off" spellCheck={false} aria-invalid={Boolean(subjectError)} aria-describedby={subjectError ? 'subject-error' : undefined} onChange={event => setDraftSubject(event.target.value)} /></div><button type="submit" className="button button-primary">Load subject</button></form>{subjectError ? <p className="field-error" id="subject-error">{subjectError}</p> : null}</div>
      <div className="dataset-bar"><div className="dataset-context"><span className="subject-pill">{subject}</span>{data ? <><span>{number(data.pagination.total_batches)} acquisition batches</span>{data.pagination.total_native_collections ? <span>{number(data.pagination.total_native_collections)} native collections</span> : null}<span>{number(data.pagination.total_runs)} research pipelines</span><span>{number(data.pagination.total_sources)} source records</span><Badge value={data.status} /></> : <span>{loading ? 'Loading records…' : 'No snapshot loaded'}</span>}</div><button className="button button-secondary refresh-button" onClick={refresh} disabled={loading}><Icon name="refresh" />{loading ? 'Loading…' : 'Refresh'}</button></div>
      {error ? <Notice kind="error" title="Refresh failed"><p>{error}{data ? ' The last successfully loaded snapshot is still displayed below.' : ''}</p></Notice> : null}
      {data?.status === 'partial' || data?.status === 'unavailable' ? <Notice kind="warning" title={data.status === 'partial' ? 'Partial evidence available' : 'Evidence unavailable'}><p>Some requested records or measurements are missing. Inspect the recorded limitations before interpreting results.</p>{data.warnings.length ? <details><summary>Recorded warnings ({data.warnings.length})</summary><ul className="plain-list">{data.warnings.map((warning, index) => <li key={index}>{label(warning.code)}: {number(warning.count)}</li>)}</ul></details> : null}</Notice> : null}
      <nav className="view-nav" aria-label="Datasource views">{views.map(item => <button key={item.id} aria-pressed={view === item.id} onClick={() => setView(item.id)}><Icon name={item.icon} />{item.title}{data && item.id === 'comparison' ? <span className="nav-count">{data.comparisons.length}</span> : null}</button>)}</nav>
      <div aria-busy={loading} className={loading && data ? 'content-refreshing' : undefined}>{data ? view === 'executions' ? <ExecutionsView key={data.subject} data={data} loading={loading} page={page} /> : view === 'sources' ? <SourcesView key={data.subject} data={data} loading={loading} page={page} /> : view === 'comparison' ? <ComparisonView key={data.subject} data={data} /> : <ConsistencyView key={data.subject} data={data} /> : loading ? <Loading /> : <Empty title="Datasource is not available">Refresh to retry the local API, or load a different subject.</Empty>}</div>
      {data ? <footer className="snapshot-footer"><span>Snapshot generated {time(data.generated_at)}</span><details><summary>Snapshot identity</summary><code>{data.snapshot_id}</code></details><span>No evidence is modified by this workspace.</span></footer> : null}
    </main></>;
}
