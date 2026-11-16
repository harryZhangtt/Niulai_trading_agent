import { useEffect, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { Badge, Empty, Field, Icon, Notice, RunDetails } from './components';
import { display, label, metricLabel, number, safeUrl, time } from './format';
import { CollectionDetails } from './AcquisitionComparison';
import RunEvidence from './RunEvidence';
import type { AcquisitionBatch, AcquisitionRequirement, DatasourceResponse, MetricDefinition, RetentionCounts, Run, Source } from './types';

const retentionLabels: Array<[keyof RetentionCounts, string]> = [
  ['manifest_receipts', 'Manifests'], ['configuration_receipts', 'Configurations'],
  ['requirement_receipts', 'Requirement results'], ['attempt_receipts', 'Attempts'],
  ['source_receipts', 'Source receipts'], ['observation_receipts', 'Observations'],
];

type RunKind = 'collection' | 'research' | 'comparison';
type RunDetailTab = 'summary' | 'evidence';
type RunSelection = { kind: RunKind; id: string };
type RunRoute = { selection: RunSelection | null; tab: RunDetailTab; sourceId: string };

function routeFromLocation(): RunRoute {
  const params = new URLSearchParams(window.location.search);
  const kind = params.get('kind');
  const id = params.get('run')?.trim();
  let selection: RunSelection | null = null;
  if (id && (kind === 'collection' || kind === 'research' || kind === 'comparison')) selection = { kind, id };
  return {
    selection,
    tab: params.get('runTab') === 'evidence' ? 'evidence' : 'summary',
    sourceId: params.get('source')?.trim() ?? '',
  };
}

function Retention({ counts }: { counts: RetentionCounts }) {
  return <dl className="retention-counts">{retentionLabels.map(([key, title]) => <div key={key}><dt>{title}</dt><dd>{number(counts[key])}</dd></div>)}</dl>;
}

function Requirement({ item, batch, subject }: { item: AcquisitionRequirement; batch: AcquisitionBatch; subject: string }) {
  const source = item.source_id ? batch.sources.find(candidate => candidate.id === item.source_id || candidate.source_sha256 === item.source_id) : undefined;
  return <details className="acquisition-requirement">
    <summary><span className="requirement-name">{item.id}</span><Badge value={item.status} /><span className="requirement-summary">{item.route ?? 'No selected route'} / Cache hit: {display(item.cache_hit)}</span></summary>
    <div className="requirement-content"><dl className="metadata run-metadata">
      <Field name="Subject">{item.subject}</Field><Field name="Elapsed seconds">{number(item.elapsed_seconds)}</Field>
      <Field name="Selected evidence">{source ? <a href={`/datasource?subject=${encodeURIComponent(subject)}&view=runs&kind=collection&run=${encodeURIComponent(batch.id)}&runTab=evidence&source=${encodeURIComponent(source.id)}`}>{source.title || source.id}<Icon name="chevron" size={13} /></a> : item.source_id ? <><span className="mono">{item.source_id}</span><span className="cell-subtext">Linked evidence is not on this loaded page.</span></> : 'No selected evidence recorded'}</Field><Field name="Result SHA-256" mono>{item.receipt_sha256}</Field>
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
    <details className="json-disclosure"><summary>Configuration JSON</summary><p className="subtle">Exact sanitized configuration projected for this collection run.</p><pre tabIndex={0} aria-label={`Configuration JSON for ${batch.batch_id}`}><code>{JSON.stringify(batch.configuration, null, 2)}</code></pre></details>
  </details>;
}

function BatchDetails({ batch, definitions }: { batch: AcquisitionBatch; definitions?: Record<string, MetricDefinition> }) {
  return <section className="batch-details" aria-labelledby="batch-detail-title">
    <div className="section-heading"><div><h2 id="batch-detail-title">{batch.batch_id}</h2><p className="subtle">{batch.query ?? 'Query unknown'}</p></div><Badge value={batch.status} /></div>
    <dl className="metadata run-metadata batch-identity"><Field name="Execution ID" mono>{batch.execution_id}</Field><Field name="Subjects">{batch.subjects.join(', ')}</Field><Field name="Started">{time(batch.started_at)}</Field><Field name="Finished">{time(batch.finished_at)}</Field><Field name="Manifest SHA-256" mono>{batch.manifest_sha256}</Field><Field name="Collector version">{batch.version}</Field></dl>
    <dl className="run-metrics batch-metrics">{Object.entries(batch.metrics).map(([key, value]) => <div key={key}><dt>{metricLabel(key, definitions)}</dt><dd>{number(value)}<span>{definitions?.[key]?.unit ?? ''}</span></dd></div>)}</dl>
    <p className="batch-counting-note">Metrics cover the whole batch. Provider calls count adapter dispatches. HTTP requests: <strong>Unknown</strong>.</p>
    <Configuration batch={batch} />
    <section className="batch-requirements"><h3>Requirement outcomes</h3><p className="subtle">Showing requirements for the requested subject. Expand a requirement to inspect its selected evidence, cache route, and immutable attempt receipts.</p>{batch.requirements.length ? batch.requirements.map(item => <Requirement item={item} batch={batch} subject={batch.subjects[0] ?? ''} key={item.id} />) : <p className="unknown-note">No requirement outcomes for this subject were projected. This does not establish a successful fetch.</p>}</section>
    <section className="batch-retention"><h3>Durable snapshot references</h3><p className="subtle">Snapshots are retained until explicit garbage collection. The cache is a disposable index.</p><Retention counts={batch.retention} /><p className="subtle">Counts cover hash-checked receipt references in this batch. They do not represent unique stored objects or a global storage inventory.</p></section>
    {batch.limitations.length ? <details className="batch-limitations"><summary>Scope and limitations</summary><ul className="plain-list">{batch.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details> : null}
  </section>;
}

export default function ExecutionsView({ data, loading, page }: { data: DatasourceResponse; loading: boolean; page: (offset: number) => void }) {
  const initialParams = new URLSearchParams(window.location.search);
  const requestedKind = initialParams.get('kind');
  const requestedStatus = initialParams.get('status') ?? '';
  const [route, setRoute] = useState<RunRoute>(routeFromLocation);
  const [filter, setFilter] = useState('');
  const detailRef = useRef<HTMLDivElement | null>(null);
  const selection = route.selection;
  const query = filter.trim().toLowerCase();
  const selectedId = selection?.kind === 'collection' ? selection.id : '';
  const selectedResearchId = selection?.kind === 'research' ? selection.id : '';
  const selectedComparisonId = selection?.kind === 'comparison' ? selection.id : '';
  const allBatches = data.batches ?? [];
  const batches = allBatches.filter(batch => (!requestedStatus || requestedKind !== 'collection' || batch.status === requestedStatus) && (!query || [batch.batch_id, batch.execution_id, batch.query].filter(Boolean).join(' ').toLowerCase().includes(query)));
  const selected = selectedId ? allBatches.find(batch => [batch.id, batch.batch_id, batch.execution_id].includes(selectedId)) : undefined;
  const allResearchRuns = data.runs;
  const researchRuns = allResearchRuns.filter(run => (!requestedStatus || requestedKind !== 'research' || run.status === requestedStatus) && (!query || [run.id, run.execution_id, run.query, run.pipeline_id].filter(Boolean).join(' ').toLowerCase().includes(query)));
  const selectedResearch = selectedResearchId ? allResearchRuns.find(run => run.id === selectedResearchId || run.execution_id === selectedResearchId) : undefined;
  const allComparisonRuns = data.comparisons.flatMap(comparison => comparison.acquisition?.collections.map(collection => ({ comparison, collection })) ?? []);
  const comparisonRuns = allComparisonRuns.filter(({ comparison, collection }) => (!requestedStatus || requestedKind !== 'comparison' || collection.status === requestedStatus) && (!query || [comparison.title, comparison.id, collection.execution_id, collection.query].filter(Boolean).join(' ').toLowerCase().includes(query)));
  const selectedComparison = selectedComparisonId ? allComparisonRuns.find(item => item.collection.execution_id === selectedComparisonId) : undefined;
  const counts = data.aggregates.batch_counts;
  const retention = data.aggregates.retention_counts;
  const total = data.pagination.total_batches;
  const next = data.pagination.next_offset;

  useEffect(() => {
    const syncRoute = () => setRoute(routeFromLocation());
    window.addEventListener('popstate', syncRoute);
    return () => window.removeEventListener('popstate', syncRoute);
  }, []);

  useEffect(() => {
    if (!selection) return;
    const frame = window.requestAnimationFrame(() => {
      const detail = detailRef.current;
      if (!detail) return;
      detail.focus({ preventScroll: true });
      detail.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selection?.kind, selection?.id, route.tab]);

  function selectRun(kind: RunKind, id: string) {
    setRoute({ selection: { kind, id }, tab: 'summary', sourceId: '' });
    const url = new URL(window.location.href);
    url.searchParams.set('view', 'runs');
    url.searchParams.set('kind', kind);
    url.searchParams.set('run', id);
    url.searchParams.delete('runTab');
    url.searchParams.delete('source');
    url.searchParams.delete('status');
    window.history.pushState(null, '', url);
  }

  function selectRunTab(event: MouseEvent<HTMLAnchorElement>, tab: RunDetailTab) {
    event.preventDefault();
    setRoute(current => ({ ...current, tab, sourceId: tab === 'summary' ? '' : current.sourceId }));
    const url = new URL(window.location.href);
    if (tab === 'summary') url.searchParams.delete('runTab');
    else url.searchParams.set('runTab', 'evidence');
    if (tab === 'summary') url.searchParams.delete('source');
    window.history.pushState(null, '', url);
  }

  function selectRunEvidence(event: MouseEvent<HTMLAnchorElement>, sourceId: string) {
    event.preventDefault();
    setRoute(current => ({ ...current, tab: 'evidence', sourceId }));
    const url = new URL(window.location.href);
    url.searchParams.set('runTab', 'evidence');
    url.searchParams.set('source', sourceId);
    window.history.pushState(null, '', url);
  }

  function closeDetails() {
    setRoute({ selection: null, tab: 'summary', sourceId: '' });
    const url = new URL(window.location.href);
    url.searchParams.delete('kind');
    url.searchParams.delete('run');
    url.searchParams.delete('runTab');
    url.searchParams.delete('source');
    window.history.pushState(null, '', url);
  }

  if (selection) {
    const collectionView = selection.kind === 'collection';
    const researchView = selection.kind === 'research';
    const title = collectionView ? 'Data collection details' : researchView ? 'Research run' : 'A/B comparison arm details';
    const description = collectionView
      ? 'Fetched or cached records, provider dispatches, requirements, and immutable receipts for one collection run.'
      : researchView
        ? 'Questions, observations, linked evidence, phases, and script versions for one bounded analysis run.'
        : 'Captured sources and work counts for one controlled comparison arm.';
    const ariaLabel = collectionView ? 'Selected data collection details' : researchView ? 'Selected research analysis details' : 'Selected A/B comparison run details';
    const runExists = collectionView ? Boolean(selected) : researchView ? Boolean(selectedResearch) : Boolean(selectedComparison);
    let evidenceSources: Source[] = [];
    let evidenceRun: Run | undefined;
    let relationshipComplete = true;
    let missingRelationships = 0;
    let runLabel = `run ${selection.id}`;
    if (selected) {
      evidenceSources = selected.sources;
      runLabel = `collection run ${selected.execution_id}`;
    } else if (selectedResearch) {
      const identities = new Set([selectedResearch.id, selectedResearch.execution_id].filter((value): value is string => Boolean(value)));
      evidenceSources = data.sources.filter(source => source.run_ids.some(id => identities.has(id)));
      evidenceRun = selectedResearch;
      const linkedIds = new Set(evidenceSources.flatMap(source => [source.id, source.source_sha256].filter((value): value is string => Boolean(value))));
      missingRelationships = new Set(selectedResearch.source_ids.filter(id => !linkedIds.has(id))).size;
      relationshipComplete = data.pagination.offset === 0 && data.pagination.next_offset === null && missingRelationships === 0;
      runLabel = `research run ${selectedResearch.execution_id ?? selectedResearch.id}`;
    } else if (selectedComparison) {
      evidenceSources = selectedComparison.collection.sources;
      runLabel = `comparison arm ${selectedComparison.collection.execution_id}`;
    }
    const tabHref = (tab: RunDetailTab) => {
      const url = new URL(window.location.href);
      if (tab === 'summary') { url.searchParams.delete('runTab'); url.searchParams.delete('source'); }
      else url.searchParams.set('runTab', 'evidence');
      return `${url.pathname}${url.search}`;
    };
    const evidenceHref = (sourceId: string) => {
      const url = new URL(window.location.href);
      url.searchParams.set('runTab', 'evidence');
      url.searchParams.set('source', sourceId);
      return `${url.pathname}${url.search}`;
    };
    return <div className="executions-view">
      <div className="analysis-intro"><div><button className="button button-secondary button-small" onClick={closeDetails}><Icon name="chevron" size={15} /> Back to runs</button><h2>{title}</h2><p>{description}</p></div></div>
      {runExists ? <nav className="view-nav" aria-label="Run detail views"><a href={tabHref('summary')} aria-current={route.tab === 'summary' ? 'page' : undefined} onClick={event => selectRunTab(event, 'summary')}>Summary</a><a href={tabHref('evidence')} aria-current={route.tab === 'evidence' ? 'page' : undefined} onClick={event => selectRunTab(event, 'evidence')}>Evidence <span className="nav-count">{evidenceSources.length}</span></a></nav> : null}
      <div className="run-detail-anchor" ref={detailRef} tabIndex={-1} aria-label={ariaLabel}>
        {runExists && route.tab === 'evidence' ? <RunEvidence sources={evidenceSources} subject={data.subject} run={evidenceRun} runLabel={runLabel} relationshipComplete={relationshipComplete} missingRelationships={missingRelationships} selectedSourceId={route.sourceId} evidenceHref={evidenceHref} onSelectSource={selectRunEvidence} /> : null}
        {route.tab === 'summary' && collectionView ? selected ? <BatchDetails batch={selected} definitions={data.metric_definitions} /> : <Empty title="Collection run not found">No collection run matches {selection.id} in this loaded snapshot.</Empty> : null}
        {route.tab === 'summary' && researchView ? selectedResearch ? <RunDetails run={selectedResearch} definitions={data.metric_definitions} /> : <Empty title="Research run not found">No research run matches {selection.id} in this loaded snapshot.</Empty> : null}
        {route.tab === 'summary' && selection.kind === 'comparison' ? selectedComparison ? <section className="comparison-run-detail"><div className="section-heading"><div><h3>{selectedComparison.comparison.title} · Arm {selectedComparison.collection.arm}</h3><p className="subtle">This is one comparison arm. Paired interpretation remains in Comparisons.</p></div><a href={`/datasource?subject=${encodeURIComponent(data.subject)}&view=comparisons&comparison=${encodeURIComponent(selectedComparison.comparison.id)}&collection=${encodeURIComponent(selectedComparison.collection.execution_id)}`}>Open full comparison</a></div><CollectionDetails collection={selectedComparison.collection} /></section> : <Empty title="Comparison run not found">No comparison run matches {selection.id} in this loaded snapshot.</Empty> : null}
      </div>
    </div>;
  }

  return <div className="executions-view">
    <div className="analysis-intro"><div><h2>Runs</h2><p>Choose a run to open its inputs, outputs, evidence, and technical receipts.</p></div><div className="execution-filter"><label htmlFor="execution-filter">Filter runs</label><div className="input-with-icon"><Icon name="search" /><input id="execution-filter" type="search" value={filter} onChange={event => setFilter(event.target.value)} placeholder="Name, execution ID, or query…" /></div></div></div>
    <Notice title="Three different stages"><dl className="run-type-guide"><div><dt>Data collection</dt><dd>Fetches or reuses source records and saves provenance. It does not interpret investment meaning.</dd></div><div><dt>Research analysis</dt><dd>Reads a bounded evidence packet and produces questions, observations, or analysis. It does not prove that new data was fetched.</dd></div><div><dt>A/B comparison</dt><dd>Compares two controlled collection executions. The full interpretation remains in Comparisons.</dd></div></dl></Notice>
    <section className="run-group" aria-labelledby="collection-runs-title"><div className="section-heading run-group-heading"><div><h3 id="collection-runs-title">Data collection runs</h3><p className="subtle">Inspect fetched or cached records, provider dispatches, requirements, and immutable receipts.</p></div><span className="record-count">{number(total)} total</span></div>
    {counts ? <div className="execution-totals"><span><strong>{number(counts.total)}</strong> projected runs</span><span><strong>{number(counts.registered)}</strong> registered</span><span><strong>{number(counts.unavailable_batches)}</strong> unavailable manifests</span>{Object.entries(counts.by_status).map(([status, count]) => <span key={status}><Badge value={status} /> {number(count)}</span>)}</div> : null}
    {batches.length ? <section className="execution-ledger"><div className="table-wrap" role="region" aria-label="Collection runs" tabIndex={0}><table className="data-table execution-table"><caption className="sr-only">Collection runs for {data.subject}</caption><thead><tr><th>Run</th><th>Status</th><th>Cache and dispatches</th><th>Started</th></tr></thead><tbody>{batches.map(batch => <tr key={batch.id} className={selected?.id === batch.id ? 'selected-row' : undefined}><td><button className="source-title-button" onClick={() => selectRun('collection', batch.id)} aria-pressed={selected?.id === batch.id}><span>{batch.batch_id}</span><span className="run-action-label">View collection details <Icon name="chevron" size={15} /></span></button><span className="execution-query">{batch.query ?? 'Query unknown'}</span><span className="cell-subtext mono">{batch.execution_id}</span></td><td><Badge value={batch.status} /><span className="cell-subtext">{number(batch.metrics.fulfilled)} / {number(batch.metrics.requirements)} fulfilled</span></td><td><span>{number(batch.metrics.cache_hits)} cache hits</span><span className="cell-subtext">{number(batch.metrics.provider_calls)} adapter dispatches</span><span className="cell-subtext">{number(batch.metrics.fallbacks)} fallbacks / {number(batch.metrics.retries)} retries</span></td><td>{time(batch.started_at)}</td></tr>)}</tbody></table></div></section> : <Empty title={query ? 'No collection runs match this filter' : data.batches ? 'No collection runs on this page' : 'Collection-run records are unavailable'}>{query ? 'Clear the run filter to inspect the loaded records.' : 'A collection run appears after its immutable terminal manifest is registered.'}</Empty>}
    <div className="pagination execution-pagination"><span>{number(total)} collection runs for {data.subject}. Filters apply to this page.</span><div><button className="button button-secondary button-small" disabled={loading || data.pagination.offset === 0} onClick={() => page(Math.max(0, data.pagination.offset - data.pagination.limit))}>Previous runs</button><button className="button button-secondary button-small" disabled={loading || next === null || total == null || next >= total} onClick={() => next !== null && page(next)}>Next runs</button></div></div></section>
    <section className="run-group" aria-labelledby="research-runs-title"><div className="section-heading run-group-heading"><div><h3 id="research-runs-title">Research analysis runs</h3><p className="subtle">Inspect how a bounded evidence packet was interpreted, including linked evidence, extracted observations, phases, and script versions.</p></div><span className="record-count">{number(researchRuns.length)} loaded</span></div>
      {researchRuns.length ? <div className="table-wrap" role="region" aria-label="Research runs" tabIndex={0}><table className="data-table execution-table"><caption className="sr-only">Research runs for {data.subject}</caption><thead><tr><th>Run</th><th>Status</th><th>Evidence</th><th>Started</th></tr></thead><tbody>{researchRuns.map(run => <tr key={run.id} className={selectedResearch?.id === run.id ? 'selected-row' : undefined}><td><button className="source-title-button" onClick={() => selectRun('research', run.id)} aria-pressed={selectedResearch?.id === run.id}><span>{run.query || run.id}</span><span className="run-action-label">View analysis details <Icon name="chevron" size={15} /></span></button><span className="cell-subtext mono">{run.execution_id ?? run.id}</span></td><td><Badge value={run.status} /><span className="cell-subtext">{display(run.pipeline_id)}</span></td><td>{number(run.source_ids.length)} records</td><td>{time(run.started_at)}</td></tr>)}</tbody></table></div> : <Empty title={query ? 'No research runs match this filter' : 'No research runs recorded'}>Clear the filter or choose another subject.</Empty>}
    </section>
    <section className="run-group" aria-labelledby="comparison-runs-title"><div className="section-heading run-group-heading"><div><h3 id="comparison-runs-title">A/B comparison runs</h3><p className="subtle">Inspect one arm's captured sources and work counts. Open Comparisons for the paired interpretation.</p></div><a href={`/datasource?subject=${encodeURIComponent(data.subject)}&view=comparisons`}>Open comparisons</a></div>
      {comparisonRuns.length ? <div className="table-wrap" role="region" aria-label="Comparison runs" tabIndex={0}><table className="data-table execution-table"><caption className="sr-only">Comparison runs for {data.subject}</caption><thead><tr><th>Run</th><th>Status</th><th>Logical work</th><th>Started</th></tr></thead><tbody>{comparisonRuns.map(({ comparison, collection }) => <tr key={collection.execution_id}><td><button className="source-title-button" aria-pressed={selectedComparison?.collection.execution_id === collection.execution_id} onClick={() => selectRun('comparison', collection.execution_id)}><span>{comparison.title} · Arm {collection.arm}</span><span className="run-action-label">View arm details <Icon name="chevron" size={15} /></span></button><span className="cell-subtext mono">{collection.execution_id}</span><a className="cell-subtext" href={`/datasource?subject=${encodeURIComponent(data.subject)}&view=comparisons&comparison=${encodeURIComponent(comparison.id)}&collection=${encodeURIComponent(collection.execution_id)}`}>Open in Comparisons</a></td><td><Badge value={collection.status} /><span className="cell-subtext">Review {label(collection.review_status)}</span></td><td>{number(collection.metrics.search_items)} search + {number(collection.metrics.open_items)} open<span className="cell-subtext">{number(collection.sources.length)} captured sources</span></td><td>{time(collection.started_at)}</td></tr>)}</tbody></table></div> : <Empty title="No comparison runs recorded">Controlled A/B run records appear here when available.</Empty>}
    </section>
    {retention ? <details className="aggregate-retention"><summary>Technical retention totals</summary><Retention counts={retention} /><p className="subtle">These are per-run hash-checked receipt references. Repeated references may identify the same stored object.</p></details> : null}
  </div>;
}
