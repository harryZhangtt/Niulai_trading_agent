import { label, number } from '../../format';
import type { Source, SourceCounts } from '../../types';
import styles from './EvidenceReadiness.module.css';

export default function EvidenceReadiness({ counts, sources, subject, fullSnapshot }: { counts?: SourceCounts; sources: Source[]; subject: string; fullSnapshot: boolean }) {
  const total = counts?.total ?? sources.length;
  const linked = sources.filter(source => source.run_ids.length || source.batch_ids?.length || source.collection_ids?.length).length;
  const unlinked = Math.max(0, sources.length - linked);
  const classes = Object.entries(counts?.by_document_type ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 4);
  const maximum = Math.max(1, ...classes.map(([, value]) => value));
  const evidenceHref = (query = '') => `/datasource?subject=${encodeURIComponent(subject)}&view=evidence${query ? `&q=${encodeURIComponent(query)}` : ''}`;
  return <section className={styles.root} aria-labelledby="evidence-readiness-title">
    <div className="section-heading"><div><h3 id="evidence-readiness-title">Evidence readiness</h3><p className="subtle">Snapshot coverage and provenance completeness—not a quality score.</p></div><a href={evidenceHref()}>Open evidence</a></div>
    <dl className={styles.stats}>
      <div><dt>Retained records</dt><dd>{number(total)}</dd></div>
      <div><dt>Persisted labels</dt><dd>{number(counts?.persisted_labels)}</dd></div>
      <div><dt>Availability unknown</dt><dd>{number(counts?.unknown_available_at)}</dd></div>
    </dl>
    {fullSnapshot ? <div className={styles.coverage}><div className={styles.coverageBar} role="img" aria-label={`${linked} evidence records linked to a run; ${unlinked} not linked in this snapshot`}><span style={{ width: `${sources.length ? linked / sources.length * 100 : 0}%` }} /><span style={{ width: `${sources.length ? unlinked / sources.length * 100 : 0}%` }} /></div><p><strong>{number(linked)}</strong> linked to a run · <strong>{number(unlinked)}</strong> unlinked in this snapshot</p></div> : <p className="unknown-note">Relationship coverage is page-only because more evidence pages exist.</p>}
    {classes.length ? <div className={styles.classes}><h4>Leading document classes</h4>{classes.map(([name, value]) => <a href={evidenceHref(name === 'unknown' ? '' : name)} key={name}><span>{label(name)}</span><span className={styles.track}><i style={{ width: `${value / maximum * 100}%` }} /></span><strong>{number(value)}</strong></a>)}</div> : <p className="unknown-note">Document-class counts are unavailable.</p>}
    <details><summary>Evidence-readiness data table</summary><div className="table-wrap" role="region" aria-label="Evidence readiness data" tabIndex={0}><table className="data-table"><thead><tr><th>Measure</th><th>Count</th><th>Denominator</th></tr></thead><tbody><tr><th scope="row">Persisted labels</th><td>{number(counts?.persisted_labels)}</td><td>{number(total)}</td></tr><tr><th scope="row">Availability unknown</th><td>{number(counts?.unknown_available_at)}</td><td>{number(total)}</td></tr>{classes.map(([name, value]) => <tr key={`class-${name}`}><th scope="row">Document class: {label(name)}</th><td>{number(value)}</td><td>{number(total)}</td></tr>)}{fullSnapshot ? <><tr><th scope="row">Linked evidence</th><td>{number(linked)}</td><td>{number(sources.length)}</td></tr><tr><th scope="row">Unlinked evidence</th><td>{number(unlinked)}</td><td>{number(sources.length)}</td></tr></> : null}</tbody></table></div></details>
  </section>;
}
