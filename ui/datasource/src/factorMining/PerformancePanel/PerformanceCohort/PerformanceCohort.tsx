import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, Notice } from '../../../components';
import type { FactorPerformance } from '../../viewModels';
import styles from './PerformanceCohort.module.css';

const PAGE_SIZE = 50;
const number = new Intl.NumberFormat('en', { maximumSignificantDigits: 6 });
function subjectLabel(value: FactorPerformance): string {
  if (value.subject.kind === 'standalone') return value.subject.factorIds[0];
  if (value.subject.kind === 'leave_one_out') return `Combination without ${value.subject.omittedFactorId}`;
  return `Combination: ${value.subject.factorIds.join(' + ')}`;
}
function provenanceLabel(value: FactorPerformance): string {
  if (value.provenance.evidence === 'hash_bound') return 'Reproduced · hash bound';
  if (value.provenance.evidence === 'unverified') return 'Reported · unverified';
  return value.provenance.evidence.replaceAll('_', ' ');
}
function intervalLabel(value: Extract<FactorPerformance, { state: 'available' }>): string {
  const level = value.uncertainty.level == null ? '' : ` ${(value.uncertainty.level * 100).toLocaleString('en', { maximumFractionDigits: 2 })}%`;
  return `${value.uncertainty.kind.replaceAll('_', ' ')}${level}: ${number.format(value.uncertainty.lower)} to ${number.format(value.uncertainty.upper)}`;
}

export function PerformanceCohort({ title, values }: { title: string; values: FactorPerformance[] }) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(values.length / PAGE_SIZE));
  useEffect(() => { setPage(current => Math.min(current, pageCount - 1)); }, [pageCount]);
  const previous = useCallback(() => setPage(current => Math.max(0, current - 1)), []);
  const next = useCallback(() => setPage(current => Math.min(pageCount - 1, current + 1)), [pageCount]);
  const visible = useMemo(() => values.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE), [page, values]);
  const available = visible.filter((value): value is Extract<FactorPerformance, { state: 'available' }> => value.state === 'available');
  const cohortAvailable = useMemo(() => values.filter((value): value is Extract<FactorPerformance, { state: 'available' }> => value.state === 'available'), [values]);
  const domain = useMemo(() => {
    if (!cohortAvailable.length) return null;
    const low = Math.min(0, ...cohortAvailable.flatMap(value => [value.pointEstimate, value.uncertainty.lower]));
    const high = Math.max(0, ...cohortAvailable.flatMap(value => [value.pointEstimate, value.uncertainty.upper]));
    const span = high - low;
    if (!Number.isFinite(low) || !Number.isFinite(high) || !Number.isFinite(span)) return null;
    const padding = span === 0 ? Math.max(Math.abs(high) * 0.1, 1) : span * 0.08;
    return { low: low - padding, high: high + padding };
  }, [cohortAvailable]);
  const width = 640; const left = 170; const right = 20; const rowHeight = 40; const top = 24;
  const height = top + Math.max(1, available.length) * rowHeight + 34;
  const x = (value: number) => domain ? left + ((value - domain.low) / (domain.high - domain.low)) * (width - left - right) : left;
  return <section className={styles.cohort}><div className={styles.heading}><div><h4>{title}</h4><p>{values.length} observation{values.length === 1 ? '' : 's'} · page {page + 1} of {pageCount}</p></div>{pageCount > 1 ? <div className={styles.pagination} aria-label={`${title} pages`}><button type="button" onClick={previous} disabled={page === 0}>Previous</button><button type="button" onClick={next} disabled={page === pageCount - 1}>Next</button></div> : null}</div>
    {available.length && domain ? <><p className={styles.scrollHint}>Scroll the chart horizontally to inspect its full scale. Exact records follow below.</p><div className={styles.plotWrap} role="region" aria-label={`${title} performance chart`} tabIndex={0}><svg className={styles.plot} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title} point estimates and uncertainty intervals`}><title>{title} point estimates and uncertainty intervals</title><desc>The vertical reference line is zero. Exact values and provenance appear in the table below.</desc><line className={styles.reference} x1={x(0)} x2={x(0)} y1="8" y2={height - 22} />{available.map((value, index) => { const y = top + index * rowHeight; return <g key={value.id}><title>{`${subjectLabel(value)}: ${number.format(value.pointEstimate)}; ${intervalLabel(value)}`}</title><text className={styles.label} x={left - 12} y={y + 4} textAnchor="end">{subjectLabel(value).slice(0, 24)}</text><line className={styles.interval} x1={x(value.uncertainty.lower)} x2={x(value.uncertainty.upper)} y1={y} y2={y} /><circle className={styles.point} cx={x(value.pointEstimate)} cy={y} r="5" /></g>; })}<text className={styles.axisLabel} x={left} y={height - 5}>{number.format(domain.low)}</text><text className={styles.axisLabel} x={x(0)} y={height - 5} textAnchor="middle">0 reference</text><text className={styles.axisLabel} x={width - right} y={height - 5} textAnchor="end">{number.format(domain.high)}</text></svg></div></> : available.length ? <Notice kind="warning" title="Plot unavailable"><p>The numeric range cannot be represented safely. Exact values remain available in the table.</p></Notice> : null}
    <div className={styles.tableWrap} role="region" aria-label={`${title} exact performance table`} tabIndex={0}><table className={styles.table} role="table" aria-label={`${title} exact performance records`}><thead role="rowgroup"><tr role="row"><th scope="col">Subject</th><th scope="col">Estimate</th><th scope="col">Uncertainty</th><th scope="col">Sample</th><th scope="col">Period</th><th scope="col">Baseline</th><th scope="col">Evidence</th></tr></thead><tbody role="rowgroup">{visible.map(value => <tr key={value.id} role="row"><th scope="row" role="rowheader">{subjectLabel(value)}</th>{value.state === 'available' ? <><td role="cell" data-label="Estimate" className={styles.numeric}>{number.format(value.pointEstimate)} {value.estimateUnit.replaceAll('_', ' ')}</td><td role="cell" data-label="Uncertainty">{intervalLabel(value)}</td><td role="cell" data-label="Sample" className={styles.numeric}>{value.sample.size.toLocaleString('en')} {value.sample.unit.replaceAll('_', ' ')}</td><td role="cell" data-label="Period">{value.period.id.replaceAll('_', ' ')}<small>{value.period.start} – {value.period.end}</small></td><td role="cell" data-label="Baseline">{value.baselineId.replaceAll('_', ' ')}</td><td role="cell" data-label="Evidence"><Badge value={provenanceLabel(value)} /><code>{value.provenance.evidenceSha256}</code></td></> : <td role="cell" data-label="Availability" colSpan={6}><Badge value="unavailable" /> <span>{value.reasonCode.replaceAll('_', ' ')}</span>{value.metricId ? <small>{value.metricId.replaceAll('_', ' ')}</small> : null}</td>}</tr>)}</tbody></table></div>
  </section>;
}
