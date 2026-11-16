import { useState } from 'react';
import { Empty, Notice } from '../../components';
import { PerformanceCohort } from './PerformanceCohort';
import type { FactorMiningRun, FactorPerformance } from '../viewModels';
import styles from './PerformancePanel.module.css';

function cohortKey(value: FactorPerformance): string {
  if (value.state === 'unavailable') return `unavailable:${value.metricId ?? 'unknown'}:${value.period?.id ?? 'unknown'}:${value.baselineId ?? 'unknown'}`;
  return [value.metricId, value.estimateUnit, value.period.id, value.period.start, value.period.end, value.baselineId].join(':');
}
function cohortTitle(values: FactorPerformance[]): string {
  const first = values[0];
  if (!first || first.state === 'unavailable') return first?.metricId ? `${first.metricId.replaceAll('_', ' ')} — unavailable records` : 'Unavailable performance records';
  return `${first.metricId.replaceAll('_', ' ')} · ${first.estimateUnit.replaceAll('_', ' ')}`;
}

export function PerformancePanel({ run, selectedFactor = '', onSelectFactor }: { run: FactorMiningRun; selectedFactor?: string; onSelectFactor?: (id: string) => void }) {
  const [view, setView] = useState('all');
  if (run.performanceState === 'withheld_fixture') return <section className={styles.panel} aria-labelledby="factor-performance-heading"><h3 id="factor-performance-heading">Performance evidence</h3><Empty title="Fixture performance is withheld">Synthetic runs verify the interface only. They cannot publish performance observations.</Empty></section>;
  if (run.performanceState === 'legacy_not_recorded') return <section className={styles.panel} aria-labelledby="factor-performance-heading"><h3 id="factor-performance-heading">Performance evidence</h3><Empty title="Structured performance was not recorded">This immutable v1 manifest predates uncertainty, sample, period and baseline records. Legacy scalar metrics are not converted into chart evidence.</Empty></section>;
  if (run.performanceState === 'available' && !run.performanceLoaded) return <section className={styles.panel} aria-labelledby="factor-performance-heading"><h3 id="factor-performance-heading">Performance evidence</h3><Empty title="Performance details are not loaded">The overview confirms structured evidence exists but omits its records. Detail data is still loading or unavailable.</Empty></section>;
  if (run.performanceState === 'not_published' || run.performance.length === 0) return <section className={styles.panel} aria-labelledby="factor-performance-heading"><h3 id="factor-performance-heading">Performance evidence</h3><Empty title="No structured performance published">No point estimate, uncertainty interval or comparison record is available for this run.</Empty></section>;
  const visible = run.performance.filter(observation => {
    const subject = observation.subject;
    const related = !selectedFactor || subject.factorIds.includes(selectedFactor) || subject.omittedFactorId === selectedFactor;
    if (!related) return false;
    if (view === 'all') return true;
    if (view === 'standalone') return subject.kind === 'standalone';
    if (view === 'combination') return subject.kind === 'combination';
    return subject.kind === 'combination' || subject.kind === 'leave_one_out' && (!selectedFactor || subject.omittedFactorId === selectedFactor);
  });
  const grouped = new Map<string, FactorPerformance[]>();
  for (const observation of visible) { const key = cohortKey(observation); const records = grouped.get(key); if (records) records.push(observation); else grouped.set(key, [observation]); }
  return <section className={styles.panel} aria-labelledby="factor-performance-heading"><div className={styles.heading}><div><h3 id="factor-performance-heading">Performance evidence</h3><p>Estimates share an axis only when metric, unit, period and baseline match.</p></div><span>{visible.length} of {run.performance.length} records</span></div>
    <div className={styles.controls}>
      {onSelectFactor ? <label htmlFor="factor-performance-scope">Factor scope<select id="factor-performance-scope" value={selectedFactor} onChange={event => onSelectFactor(event.target.value)}><option value="">All factors</option>{run.factors.map(factor => <option key={factor.id} value={factor.id}>{factor.id}</option>)}</select></label> : null}
      <label htmlFor="factor-performance-view">Performance view<select id="factor-performance-view" value={view} onChange={event => setView(event.target.value)}><option value="all">All observations</option><option value="standalone">Standalone</option><option value="combination">Combinations</option><option value="leave_one_out">Contribution checks</option></select></label>
    </div>
    {view === 'leave_one_out' ? <Notice title="Contribution checks"><p>Full-combination and leave-one-out observations are shown separately. A leave-one-out score is the combination without that factor. A paired marginal estimate and its uncertainty are not published; no difference or confidence interval is inferred.</p></Notice> : null}
    {run.provenanceEvidence === 'unverified' ? <Notice kind="warning" title="Reported, not reproduced"><p>Every value below is externally reported and unverified. It is not local hash-bound evidence.</p></Notice> : null}
    {visible.length ? <div className={styles.cohorts}>{[...grouped.entries()].map(([key, values]) => <PerformanceCohort key={key} title={cohortTitle(values)} values={values} />)}</div> : <Empty title="No matching performance observations">No published records match this factor and performance view. Missing observations are not zero estimates.</Empty>}
  </section>;
}
