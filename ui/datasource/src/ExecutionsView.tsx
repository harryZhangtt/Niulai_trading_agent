import { useState } from 'react';
import { Badge, Empty, Field, Icon, Notice } from './components';
import { display, label, metricLabel, number, safeUrl, time } from './format';
import SourcesView from './SourcesView';
import { NativeCollectionLedger } from './AcquisitionComparison';
import type { AcquisitionBatch, AcquisitionRequirement, DatasourceResponse, MetricDefinition, RetentionCounts } from './types';

const retentionLabels: Array<[keyof RetentionCounts, string]> = [
  ['manifest_receipts', 'Manifests'], ['configuration_receipts', 'Configurations'],
  ['requirement_receipts', 'Requirement results'], ['attempt_receipts', 'Attempts'],
  ['source_receipts', 'Source receipts'], ['observation_receipts', 'Observations'],
];

function Retention({ counts }: { counts: RetentionCounts }) {
  return <dl className="retention-counts">{retentionLabels.map(([key, title]) => <div key={key}><dt>{title}</dt><dd>{number(counts[key])}</dd></div>)}</dl>;
}

function Requirement({ item }: { item: AcquisitionRequirement }) {
  return <details className="acquisition-requirement">
    <summary><span className="requirement-name">{item.id}</span><Badge value={item.status} /><span className="requirement-summary">{item.route ?? 'No selected route'} / Cache hit: {display(item.cache_hit)}</span></summary>
    <div className="requirement-content"><dl className="metadata run-metadata">
      <Field name="Subject">{item.subject}</Field><Field name="Elapsed seconds">{number(item.elapsed_seconds)}</Field>
      <Field name="Selected source" mono>{display(item.source_id)}</Field><Field name="Result SHA-256" mono>{item.receipt_sha256}</Field>
      <Field name="Reason codes">{item.reasons.length ? item.reasons.join(', ') : 'None recorded'}</Field>
    </dl>
      {item.attempts.length ? <div className="attempt-list">{item.attempts.map(attempt => <section className="attempt" key={attempt.receipt_sha256}>
        <div className="section-heading"><h4>Attempt {number(attempt.ordinal)}: {attempt.capability}</h4><Badge value={attempt.status} /></div>
        <dl className="metadata run-metadata"><Field name="Cache route">{display(attempt.route)}</Field><Field name="Fetch callback entered">{display(attempt.fetch_executed)}</Field>
          <Field name="Cache hit">{display(attempt.cache_hit)}</Field><Field name="Started">{time(attempt.started_at)}</Field><Field name="Finished">{time(attempt.finished_at)}</Field>
          <Field name="Reason codes">{attempt.reasons.length ? attempt.reasons.join(', ') : 'None recorded'}</Field>
          <Field name="Fetch key SHA-256" mono>{display(attempt.fetch_key_sha256)}</Field><Field name="Attempt SHA-256" mono>{attempt.receipt_sha256}</Field>
          <Field name="Action receipt SHA-256" mono>{display(attempt.action_execution_sha256)}</Field>
        </dl>
      </section>)}</div> : <p className="unknown-note">No attempt receipt is recorded. This does not establish a successful fetch.</p>}
    </div>
  </details>;
}

function Configuration({ batch }: { batch: AcquisitionBatch }) {
  const { budget, requirements } = batch.configuration;
  return <details className="batch-configuration"><summary>Configuration, routes, and scripts</summary>
    <dl className="metadata run-metadata"><Field name="Deadline seconds">{number(budget.deadline_seconds)}</Field><Field name="Maximum workers">{number(budget.max_workers)}</Field><Field name="Adapter dispatch budget">{number(budget.max_provider_calls)}</Field><Field name="Config SHA-256" mono>{batch.config_sha256}</Field><Field name="Capability catalog SHA-256" mono>{display(batch.capability_catalog_sha256)}</Field></dl>
    <h4 className="configuration-heading">Configured requirements</h4>
    {requirements.map(item => <section className="configured-requirement" key={item.id}>
      <h4>{item.id} <span>{item.subject}</span></h4><dl className="metadata run-metadata"><Field name="Required access">{item.access}</Field><Field name="Attempts per route">{number(item.max_attempts)}</Field><Field name="Cache maximum age">{number(item.cache_max_age_seconds)} seconds</Field><Field name="Attempt timeout">{number(item.timeout_seconds)} seconds</Field></dl>
      <ol className="configured-routes">{item.routes.map((route, index) => <li key={`${route.capability}-${index}`}><strong>{route.capability}</strong><dl className="metadata">{Object.entries(route.parameters).map(([key, value]) => <Field name={label(key)} key={key}>{key === 'url' && safeUrl(value) ? <a href={safeUrl(value)!} target="_blank" rel="noreferrer">{value}<Icon name="external" size={13} /></a> : display(value)}</Field>)}</dl></li>)}</ol>
    </section>)}
    <h4 className="configuration-heading">Script versions</h4>{batch.script_versions.length ? <dl className="metadata">{batch.script_versions.map(script => <Field name={script.id} key={script.id} mono>{display(script.sha256)}</Field>)}</dl> : <p className="subtle">No script versions were recorded.</p>}
  </details>;
}

function BatchDetails({ batch, definitions }: { batch: AcquisitionBatch; definitions?: Record<string, MetricDefinition> }) {
  return <section className="batch-details" aria-labelledby="batch-detail-title">
    <div className="section-heading"><div><h2 id="batch-detail-title">{batch.batch_id}</h2><p className="subtle">{batch.query ?? 'Query unknown'}</p></div><Badge value={batch.status} /></div>
    <dl className="metadata run-metadata batch-identity"><Field name="Execution ID" mono>{batch.execution_id}</Field><Field name="Subjects">{batch.subjects.join(', ')}</Field><Field name="Started">{time(batch.started_at)}</Field><Field name="Finished">{time(batch.finished_at)}</Field><Field name="Manifest SHA-256" mono>{batch.manifest_sha256}</Field><Field name="Collector version">{batch.version}</Field></dl>
    <dl className="run-metrics batch-metrics">{Object.entries(batch.metrics).map(([key, value]) => <div key={key}><dt>{metricLabel(key, definitions)}</dt><dd>{number(value)}<span>{definitions?.[key]?.unit ?? ''}</span></dd></div>)}</dl>
    <p className="batch-counting-note">Metrics cover the whole batch. Provider calls count adapter dispatches. HTTP requests: <strong>Unknown</strong>.</p>
    <Configuration batch={batch} />
    <section className="batch-requirements"><h3>Requirement outcomes</h3><p className="subtle">Showing requirements for the requested subject. Expand a requirement to inspect its cache route and immutable attempt receipts.</p>{batch.requirements.length ? batch.requirements.map(item => <Requirement item={item} key={item.id} />) : <p className="unknown-note">No requirement outcomes for this subject were projected. This does not establish a successful fetch.</p>}</section>
    <section className="batch-retention"><h3>Durable snapshot references</h3><p className="subtle">Snapshots are retained until explicit garbage collection. The cache is a disposable index.</p><Retention counts={batch.retention} /><p className="subtle">Counts cover hash-checked receipt references in this batch. They do not represent unique stored objects or a global storage inventory.</p></section>
    {batch.limitations.length ? <details className="batch-limitations"><summary>Scope and limitations</summary><ul className="plain-list">{batch.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details> : null}
  </section>;
}

export default function ExecutionsView({ data, loading, page }: { data: DatasourceResponse; loading: boolean; page: (offset: number) => void }) {
  const [selectedId, setSelectedId] = useState('');
  const [filter, setFilter] = useState('');
  const query = filter.trim().toLowerCase();
  const batches = (data.batches ?? []).filter(batch => !query || [batch.batch_id, batch.execution_id, batch.query].filter(Boolean).join(' ').toLowerCase().includes(query));
  const selected = batches.find(batch => batch.id === selectedId) ?? batches[0];
  const counts = data.aggregates.batch_counts;
  const retention = data.aggregates.retention_counts;
  const total = data.pagination.total_batches;
  const next = data.pagination.next_offset;
  return <div className="executions-view">
    <div className="analysis-intro"><div><h2>Datasource executions</h2><p>Each configurable collection batch has its own execution ID and immutable manifest.</p></div><div className="execution-filter"><label htmlFor="execution-filter">Filter loaded executions</label><div className="input-with-icon"><Icon name="search" /><input id="execution-filter" type="search" value={filter} onChange={event => setFilter(event.target.value)} placeholder="Batch, execution ID, query…" /></div></div></div>
    <Notice title="Acquisition evidence"><p>Collection and cache outcomes describe the infrastructure path. Source labels remain provisional; this view does not establish semantic admission or investment quality.</p></Notice>
    {data.comparisons.filter(item => item.acquisition).map(comparison => <NativeCollectionLedger key={comparison.id} comparison={comparison} />)}
    {counts ? <div className="execution-totals"><span><strong>{number(counts.total)}</strong> projected batches</span><span><strong>{number(counts.registered)}</strong> registered</span><span><strong>{number(counts.unavailable_batches)}</strong> unavailable manifests</span>{Object.entries(counts.by_status).map(([status, count]) => <span key={status}><Badge value={status} /> {number(count)}</span>)}</div> : null}
    {batches.length ? <section className="execution-ledger"><div className="table-wrap"><table className="data-table execution-table"><caption className="sr-only">Datasource acquisition executions for {data.subject}</caption><thead><tr><th>Execution</th><th>Outcome</th><th>Cache and dispatches</th><th>Started</th></tr></thead><tbody>{batches.map(batch => <tr key={batch.id} className={selected?.id === batch.id ? 'selected-row' : undefined}><td><button className="source-title-button" onClick={() => setSelectedId(batch.id)} aria-pressed={selected?.id === batch.id}>{batch.batch_id}<Icon name="chevron" size={15} /></button><span className="execution-query">{batch.query ?? 'Query unknown'}</span><span className="cell-subtext mono">{batch.execution_id}</span></td><td><Badge value={batch.status} /><span className="cell-subtext">{number(batch.metrics.fulfilled)} / {number(batch.metrics.requirements)} fulfilled</span></td><td><span>{number(batch.metrics.cache_hits)} cache hits</span><span className="cell-subtext">{number(batch.metrics.provider_calls)} adapter dispatches</span><span className="cell-subtext">{number(batch.metrics.fallbacks)} fallbacks / {number(batch.metrics.retries)} retries</span></td><td>{time(batch.started_at)}</td></tr>)}</tbody></table></div></section> : <Empty title={query ? 'No executions match this filter' : data.batches ? 'No acquisition executions on this page' : 'Execution records are unavailable in this snapshot'}>{query ? 'Clear the execution filter to inspect the loaded batches.' : 'An execution appears after its immutable terminal manifest is registered. Research pipeline history remains available in the source ledger.'}</Empty>}
    <div className="pagination execution-pagination"><span>{number(total)} acquisition executions for {data.subject}. Filters apply to this page.</span><div><button className="button button-secondary button-small" disabled={loading || data.pagination.offset === 0} onClick={() => page(Math.max(0, data.pagination.offset - data.pagination.limit))}>Previous executions</button><button className="button button-secondary button-small" disabled={loading || next === null || total == null || next >= total} onClick={() => next !== null && page(next)}>Next executions</button></div></div>
    {selected ? <><BatchDetails batch={selected} definitions={data.metric_definitions} /><SourcesView key={selected.id} data={data} loading={loading} page={page} context={{ title: 'Execution sources', description: 'Source receipts selected by this batch, with recorded labels and reviewer diagnostics.', sources: selected.sources }} /></> : null}
    {retention ? <details className="aggregate-retention"><summary>Registered batch retention totals</summary><Retention counts={retention} /><p className="subtle">These are per-batch hash-checked receipt references for this subject. Repeated references may identify the same stored object. Snapshots remain until explicit garbage collection; the cache can be rebuilt.</p></details> : null}
  </div>;
}
