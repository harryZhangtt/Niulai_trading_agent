import { useState } from 'react';
import { AggregateTable, Badge, DetailsTree, Empty } from '../components';
import { display, label, number } from '../format';
import type { DatasourceResponse } from '../types';
import ActivityStrip from './ActivityStrip';
import EvidenceReadiness from './EvidenceReadiness';
import StatusDistribution from './StatusDistribution';
import type { ActivityEvent } from './ActivityStrip';
import type { StatusGroup } from './StatusDistribution';
import styles from './OverviewView.module.css';
import { InformationYieldBoundary, InformationYieldPanel } from '../InformationYield';

export default function OverviewView({ data }: { data: DatasourceResponse }) {
  const [cohortId, setCohortId] = useState('');
  const cohort = data.aggregates.cohorts.find(item => item.id === cohortId)
    ?? data.aggregates.cohorts.find(item => item.id.startsWith('acquisition_batches:'))
    ?? data.aggregates.cohorts.find(item => item.id.startsWith('pipeline_runs:'))
    ?? data.aggregates.cohorts[0];
  const batchCounts = data.aggregates.batch_counts;
  const totalRuns = (data.pagination.total_batches ?? 0) + data.pagination.total_runs + (data.pagination.total_native_collections ?? 0);
  const nativeCollections = data.comparisons.flatMap(comparison => comparison.acquisition?.collections ?? []);
  const countStatuses = (rows: Array<{ status: string }>) => rows.reduce<Record<string, number>>((counts, row) => ({ ...counts, [row.status || 'unknown']: (counts[row.status || 'unknown'] ?? 0) + 1 }), {});
  const statusGroups: StatusGroup[] = [
    { id: 'research', label: 'Research runs', counts: countStatuses(data.runs) },
    { id: 'collection', label: 'Collection runs', counts: countStatuses(data.batches ?? []) },
    { id: 'comparison', label: 'Comparison runs', counts: countStatuses(nativeCollections) },
  ];
  const activity: ActivityEvent[] = [
    ...data.runs.map(run => ({ kind: 'research' as const, startedAt: run.started_at })),
    ...(data.batches ?? []).map(batch => ({ kind: 'collection' as const, startedAt: batch.started_at })),
    ...nativeCollections.map(collection => ({ kind: 'comparison' as const, startedAt: collection.started_at })),
  ];

  return <div className={styles.overview}>
    <div className="analysis-intro"><div><h2>Overview</h2><p>Health, coverage, and known gaps across the selected subject.</p></div><Badge value={data.projection_state === 'stale' ? 'partial' : data.status}>{data.projection_state === 'stale' ? 'Retained snapshot' : data.status === 'ok' ? 'Snapshot complete' : data.status === 'partial' ? 'Partial data' : 'Unavailable'}</Badge></div>
    <InformationYieldBoundary><InformationYieldPanel /></InformationYieldBoundary>
    <nav className={styles.summary} aria-label="Snapshot summary">
      <a href={`/datasource?subject=${encodeURIComponent(data.subject)}&view=evidence`}><span>Evidence records</span><strong>{number(data.pagination.total_sources)}</strong><small>Subject total; {number(data.sources.length)} records on this loaded page</small></a>
      <a href={`/datasource?subject=${encodeURIComponent(data.subject)}&view=runs`}><span>Runs</span><strong>{number(totalRuns)}</strong><small>Recorded totals across collection, research, and comparison runs</small></a>
      <a href={`/datasource?subject=${encodeURIComponent(data.subject)}&view=comparisons`}><span>Comparisons</span><strong>{number(data.comparisons.length)}</strong><small>Controlled A/B evaluations loaded in this snapshot</small></a>
      <a href="#known-gaps"><span>Known gaps</span><strong>{number(data.warnings.length)}</strong><small>Recorded warning categories</small></a>
    </nav>

    <div className={styles.grid}>
      <EvidenceReadiness counts={data.aggregates.source_counts} sources={data.sources} subject={data.subject} fullSnapshot={data.pagination.next_offset === null && data.pagination.offset === 0} />
      <section className={styles.panel} aria-labelledby="run-health-title">
        <div className="section-heading"><div><h3 id="run-health-title">Run health</h3><p className="subtle">Status distribution on the loaded page. Each run type keeps its own denominator.</p></div></div>
        <StatusDistribution groups={statusGroups} subject={data.subject} />
        {batchCounts ? <p className="subtle">Recorded collection totals: {number(batchCounts.registered)} of {number(batchCounts.total)} runs are registered; {number(batchCounts.unavailable_batches)} manifests are unavailable.</p> : null}
      </section>
    </div>
    <div className={styles.activity}><ActivityStrip events={activity} /></div>

    {cohort ? <section className="cohort-section" aria-labelledby="aggregate-title">
      <div className="case-header"><div><h3 id="aggregate-title">Aggregate metrics</h3><p className="subtle">Compare recorded coverage and resource use inside one explicit cohort.</p></div><div className="cohort-selector"><label htmlFor="overview-cohort">Cohort</label><select id="overview-cohort" value={cohort.id} onChange={event => setCohortId(event.target.value)}>{data.aggregates.cohorts.map(item => <option key={item.id} value={item.id}>{label(item.id)} — {number(item.denominator)} records</option>)}</select></div></div>
      <div className="section-heading"><div><h3>{label(cohort.id)}</h3><p className="subtle">{cohort.scope}</p></div><span className="record-count">Measured group: {number(cohort.denominator)}</span></div>
      <AggregateTable metrics={cohort.metrics} definitions={data.metric_definitions} caption={`Aggregate metrics for ${cohort.id}`} />
      {cohort.unknowns != null ? <details className="unknown-details"><summary>Unknown and missing measurements</summary>{typeof cohort.unknowns === 'object' && !Array.isArray(cohort.unknowns) ? <DetailsTree value={cohort.unknowns as Record<string, unknown>} /> : <p>{display(cohort.unknowns)}</p>}</details> : null}
    </section> : <Empty title="No aggregate metrics recorded">Runs and evidence remain available in their dedicated views.</Empty>}

    {data.warnings.length || data.aggregates.unknowns != null ? <details className={styles.gaps} id="known-gaps"><summary>Known gaps and dataset-level unknowns</summary>{data.warnings.length ? <ul className="plain-list">{data.warnings.map((warning, index) => <li key={`${warning.code}-${index}`}>{label(warning.code)}: {number(warning.count)}</li>)}</ul> : null}{data.aggregates.unknowns != null ? typeof data.aggregates.unknowns === 'object' && !Array.isArray(data.aggregates.unknowns) ? <DetailsTree value={data.aggregates.unknowns as Record<string, unknown>} /> : <p>{display(data.aggregates.unknowns)}</p> : null}</details> : null}
  </div>;
}
