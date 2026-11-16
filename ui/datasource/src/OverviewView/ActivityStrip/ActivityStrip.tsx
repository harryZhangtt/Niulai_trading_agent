import { number } from '../../format';
import styles from './ActivityStrip.module.css';

export interface ActivityEvent { kind: 'research' | 'collection' | 'comparison'; startedAt: string | null }
const kinds = [
  { id: 'research' as const, label: 'Research', className: styles.research },
  { id: 'collection' as const, label: 'Collection', className: styles.collection },
  { id: 'comparison' as const, label: 'Comparison', className: styles.comparison },
];

export default function ActivityStrip({ events }: { events: ActivityEvent[] }) {
  const days = new Map<string, Record<ActivityEvent['kind'], number>>();
  let unknown = 0;
  for (const event of events) {
    if (!event.startedAt) { unknown++; continue; }
    const date = new Date(event.startedAt);
    if (!Number.isFinite(date.getTime())) { unknown++; continue; }
    const day = date.toISOString().slice(0, 10);
    const row = days.get(day) ?? { research: 0, collection: 0, comparison: 0 };
    row[event.kind]++;
    days.set(day, row);
  }
  const rows = [...days.entries()].sort(([a], [b]) => a.localeCompare(b));
  const maximum = Math.max(1, ...rows.flatMap(([, counts]) => Object.values(counts)));
  return <figure className={styles.root}>
    <figcaption><strong>Recorded run starts (UTC)</strong><span>Events by date · not a throughput trend</span></figcaption>
    {rows.length ? <div className={styles.plot} role="img" aria-label={rows.map(([day, counts]) => `${day}: ${counts.research} research, ${counts.collection} collection, ${counts.comparison} comparison`).join('; ')}>
      {rows.map(([day, counts]) => <div className={styles.day} key={day}><div className={styles.bars}>{kinds.map(kind => <span className={`${styles.bar} ${kind.className}`} style={{ height: `${Math.max(counts[kind.id] ? 10 : 0, counts[kind.id] / maximum * 72)}px` }} key={kind.id} tabIndex={counts[kind.id] ? 0 : -1} title={`${day} · ${kind.label}: ${counts[kind.id]}`} aria-label={`${day}, ${kind.label}: ${counts[kind.id]} starts`}><b>{counts[kind.id] || ''}</b></span>)}</div><time dateTime={day}>{day.slice(5)}</time></div>)}
    </div> : <p className={styles.empty}>No valid run start times are recorded.</p>}
    <ul className={styles.legend}>{kinds.map(kind => <li key={kind.id}><span className={`${styles.key} ${kind.className}`} aria-hidden="true" />{kind.label}</li>)}{unknown ? <li>Time unknown: {number(unknown)}</li> : null}</ul>
    <details><summary>Recorded-start data table</summary><div className="table-wrap" role="region" aria-label="Recorded run starts by UTC date" tabIndex={0}><table className="data-table"><thead><tr><th>Date (UTC)</th>{kinds.map(kind => <th key={kind.id}>{kind.label}</th>)}</tr></thead><tbody>{rows.map(([day, counts]) => <tr key={day}><th scope="row">{day}</th>{kinds.map(kind => <td key={kind.id}>{number(counts[kind.id])}</td>)}</tr>)}</tbody></table></div></details>
  </figure>;
}
