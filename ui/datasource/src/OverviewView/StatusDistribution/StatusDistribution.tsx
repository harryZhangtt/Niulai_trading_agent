import { label, number } from '../../format';
import styles from './StatusDistribution.module.css';

export interface StatusGroup {
  id: 'research' | 'collection' | 'comparison';
  label: string;
  counts: Record<string, number>;
}

const tone = (status: string) => status === 'completed' || status === 'ok' ? styles.good
  : status === 'blocked' || status === 'failed' ? styles.bad
    : status === 'partial' ? styles.warn : styles.unknown;

export default function StatusDistribution({ groups, subject }: { groups: StatusGroup[]; subject: string }) {
  return <div className={styles.root}>
    {groups.map(group => {
      const entries = Object.entries(group.counts).filter(([, count]) => count > 0);
      const total = entries.reduce((sum, [, count]) => sum + count, 0);
      return <figure className={styles.group} key={group.id}>
        <figcaption><strong>{group.label}</strong><span>{number(total)} runs</span></figcaption>
        {total ? <div className={styles.bar} role="img" aria-label={`${group.label}: ${entries.map(([status, count]) => `${count} ${label(status)}`).join(', ')}`}>
          {entries.map(([status, count]) => <a className={`${styles.segment} ${tone(status)}`} style={{ width: `${count / total * 100}%` }} key={status} href={`/datasource?subject=${encodeURIComponent(subject)}&view=runs&kind=${group.id}&status=${encodeURIComponent(status)}`} title={`${label(status)}: ${count} of ${total}`} aria-label={`${group.label}, ${label(status)}: ${count} of ${total}`} />)}
        </div> : <p className={styles.empty}>No recorded runs</p>}
        <ul className={styles.legend}>{entries.map(([status, count]) => <li key={status}><span className={`${styles.key} ${tone(status)}`} aria-hidden="true" /><span>{label(status)}</span><strong>{number(count)}</strong><small>{total ? `${number(count / total * 100)}%` : 'Unknown'}</small></li>)}</ul>
      </figure>;
    })}
    <details className={styles.table}><summary>Run-status data table</summary><div className="table-wrap" role="region" aria-label="Run-status data" tabIndex={0}><table className="data-table"><thead><tr><th>Run type</th><th>Status</th><th>Count</th><th>Total</th><th>Share</th></tr></thead><tbody>{groups.flatMap(group => { const total = Object.values(group.counts).reduce((sum, count) => sum + count, 0); return Object.entries(group.counts).filter(([, count]) => count > 0).map(([status, count]) => <tr key={`${group.id}-${status}`}><th scope="row">{group.label}</th><td>{label(status)}</td><td>{number(count)}</td><td>{number(total)}</td><td>{total ? `${number(count / total * 100)}%` : 'Unknown'}</td></tr>); })}</tbody></table></div></details>
  </div>;
}
