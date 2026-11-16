import { useState } from 'react';
import { Badge, Empty, Icon } from '../../components';
import type { FactorMiningRun } from '../viewModels';
import { admissionLabel, instant, needsAttention, provenanceLabel } from '../presentation';
import styles from './RunList.module.css';

export function RunList({ runs, selected, onSelect }: { runs: FactorMiningRun[]; selected: string; onSelect: (id: string) => void }) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const query = search.trim().toLocaleLowerCase();
  const visible = runs.filter(run => `${run.id} ${provenanceLabel(run)}`.toLocaleLowerCase().includes(query)
    && (filter === 'all' || filter === 'current' && ['planned', 'running'].includes(run.status)
      || filter === 'attention' && needsAttention(run)
      || filter === 'reproduced' && run.provenanceEvidence === 'hash_bound'
      || filter === 'reported' && run.provenanceOrigin === 'reported_external'
      || filter === 'fixtures' && run.provenanceOrigin === 'synthetic_fixture'));
  return <section className={styles.list} aria-label="Factor-mining runs">
    <div className={styles.heading}><h2>Experiments</h2><span>{runs.length}</span></div>
    <div className={styles.controls}>
      <label htmlFor="factor-run-search">Find a run<input id="factor-run-search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Run ID or provenance" /></label>
      <label htmlFor="factor-run-filter">Show runs<select id="factor-run-filter" value={filter} onChange={event => setFilter(event.target.value)}>
        <option value="all">All runs</option><option value="current">Active runs</option><option value="attention">Needs attention</option>
        <option value="reproduced">Reproduced evidence</option><option value="reported">Reported evidence</option><option value="fixtures">Fixtures</option>
      </select></label>
      <p role="status" aria-atomic="true">{visible.length} {visible.length === 1 ? 'run' : 'runs'} shown</p>
    </div>
    {visible.length ? <ul>{visible.map(run => <li key={run.id}>
      <button id={`factor-run-row-${run.id}`} type="button" aria-pressed={selected === run.id} aria-controls="factor-run-detail" onClick={() => onSelect(run.id)}>
        <span className={styles.meta}><span>{provenanceLabel(run)}</span><Badge value={run.status}>{run.status.replaceAll('_', ' ')}</Badge></span>
        <span className={styles.title}>{run.id}<Icon name="chevron" size={16} /></span>
        <time dateTime={run.createdAt}>{instant(run.createdAt)} · revision {run.revision}</time>
        <span className={styles.gate}>{admissionLabel(run)}</span>
      </button>
    </li>)}</ul> : <Empty title="No runs match this view">Choose another view or clear the search to inspect recorded experiments.
      <button className="button button-secondary" onClick={() => { setSearch(''); setFilter('all'); }}>Show all runs</button>
    </Empty>}
  </section>;
}
