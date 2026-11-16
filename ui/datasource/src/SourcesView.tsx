import { useEffect, useRef, useState } from 'react';
import { Badge, Empty, Icon, SourceClassification, SourceCutoff, SourceInspector } from './components';
import { host, label, number, time } from './format';
import type { DatasourceResponse, Source } from './types';
import styles from './SourcesView.module.css';

interface EvidenceRoute { runId: string; filter: string; selectedId: string }
function readRoute(): EvidenceRoute {
  const params = new URLSearchParams(window.location.search);
  return { runId: params.get('run') ?? 'all', filter: params.get('q') ?? '', selectedId: params.get('source') ?? '' };
}
const matchesIdentity = (source: Source, id: string) => source.id === id || source.source_sha256 === id;

export default function SourcesView({ data, loading, page, context }: { data: DatasourceResponse; loading: boolean; page: (offset: number) => void; context?: { title: string; description: string; sources: Source[] } }) {
  const [route, setRoute] = useState<EvidenceRoute>(readRoute);
  const rowRefs = useRef(new Map<string, HTMLButtonElement>());
  const inspectorRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<number | null>(null);
  useEffect(() => {
    const restore = () => setRoute(readRoute());
    window.addEventListener('popstate', restore);
    return () => { window.removeEventListener('popstate', restore); if (frameRef.current !== null) cancelAnimationFrame(frameRef.current); };
  }, []);

  const { runId, filter, selectedId } = route;
  const activeRun = context ? undefined : data.runs.find(run => run.id === runId || run.execution_id === runId);
  const missingRun = !context && runId !== 'all' && !activeRun;
  const effectiveRun = context ? 'all' : activeRun?.id ?? runId;
  const runIdentities = activeRun ? new Set([activeRun.id, activeRun.execution_id].filter(Boolean)) : null;
  const query = filter.trim().toLowerCase();
  const baseSources = context?.sources ?? data.sources;
  const scopedSources = missingRun ? [] : baseSources.filter(source => !runIdentities || source.run_ids.some(id => runIdentities.has(id)));
  const sources = scopedSources.filter(source => !query || [source.title, source.url, source.labels.publisher_kind, source.labels.document_type, ...source.labels.topics, ...source.labels.perspectives].filter(Boolean).join(' ').toLowerCase().includes(query));
  const selected = selectedId ? sources.find(source => matchesIdentity(source, selectedId)) : sources[0];
  const selectedOutsideView = Boolean(selectedId && baseSources.some(source => matchesIdentity(source, selectedId)) && !selected);
  const { pagination } = data;
  const availabilityUnknown = scopedSources.filter(source => !source.timestamps.available_at).length;
  const linked = scopedSources.filter(source => source.run_ids.length || source.batch_ids?.length || source.collection_ids?.length).length;

  function writeRoute(nextRoute: EvidenceRoute, kind: 'push' | 'replace') {
    setRoute(nextRoute);
    const next = new URL(window.location.href);
    if (!context) { if (nextRoute.runId === 'all') next.searchParams.delete('run'); else next.searchParams.set('run', nextRoute.runId); }
    if (nextRoute.filter.trim()) next.searchParams.set('q', nextRoute.filter); else next.searchParams.delete('q');
    if (nextRoute.selectedId) next.searchParams.set('source', nextRoute.selectedId); else next.searchParams.delete('source');
    if (kind === 'push') window.history.pushState(null, '', next); else window.history.replaceState(null, '', next);
  }
  function selectSource(id: string) {
    writeRoute({ ...route, selectedId: id }, 'push');
    if (window.matchMedia('(max-width: 930px)').matches) {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = requestAnimationFrame(() => {
        const heading = inspectorRef.current?.querySelector<HTMLHeadingElement>('.inspector-title');
        heading?.focus({ preventScroll: true });
        heading?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
        frameRef.current = null;
      });
    }
  }
  function selectRun(id: string) { writeRoute({ ...route, runId: id, selectedId: '' }, 'push'); }
  function changeFilter(value: string) { writeRoute({ ...route, filter: value }, 'replace'); }
  function backToEvidence() {
    const row = selected ? rowRefs.current.get(selected.id) : undefined;
    row?.focus({ preventScroll: true });
    (row ?? document.getElementById('ledger-heading'))?.scrollIntoView({ block: 'center', behavior: 'instant' });
  }

  return <div className={`sources-layout ${styles.layout}`}>
    <div className="ledger-column">
      <section className={`ledger ${styles.ledger}`} aria-labelledby="ledger-heading">
        <div className={`section-heading ledger-heading ${styles.heading}`}>
          <div><h2 id="ledger-heading">{context?.title ?? 'Evidence records'}</h2><p className="subtle">{context?.description ?? 'Inspect source identity, availability, and the executions linked to each record.'}</p></div>
          <span className="record-count" role="status" aria-atomic="true">{number(sources.length)} of {number(scopedSources.length)} loaded records shown</span>
        </div>
        <dl className={styles.summary} aria-label="Loaded evidence scope">
          <div><dt>Loaded records</dt><dd>{number(scopedSources.length)}</dd></div>
          <div><dt>Availability unknown</dt><dd>{number(availabilityUnknown)}</dd></div>
          <div><dt>With linked executions</dt><dd>{number(linked)}</dd></div>
        </dl>
        <div className={`ledger-toolbar ${styles.toolbar}`}>
          <div className="search-field"><label htmlFor="source-filter">{context ? 'Filter execution sources' : 'Filter this page'}</label><div className="input-with-icon"><Icon name="search" /><input id="source-filter" type="search" value={filter} onChange={event => changeFilter(event.target.value)} placeholder="Title, publisher, topic…" /></div></div>
          {context ? <p className="source-context-note">Sources are linked to the selected immutable batch. Labels remain provisional unless their recorded annotation says otherwise.</p> : <div className="run-field"><label htmlFor="run-select">Used by research run</label><select id="run-select" value={effectiveRun} onChange={event => selectRun(event.target.value)}>
            <option value="all">All research runs ({data.runs.length})</option>
            {missingRun ? <option value={runId}>Run unavailable in this snapshot</option> : null}
            {data.runs.map(run => <option value={run.id} key={run.id}>{run.query || run.id} — {label(run.status)}</option>)}
          </select></div>}
        </div>
        {activeRun ? <div className={styles.scope}><span>Evidence linked to <strong>{activeRun.query || activeRun.id}</strong></span><button className="text-button" onClick={() => selectRun('all')}>Show all research runs</button></div> : null}
        {sources.length ? <div className={`table-wrap source-table-wrap ${styles.tableWrap}`} role="region" aria-label="Evidence records" tabIndex={0}>
          <table className={`data-table source-table ${styles.table}`}>
            <caption className="sr-only">Source records for {data.subject}. Select a title to inspect its provenance.</caption>
            <thead><tr><th scope="col">Source</th><th scope="col">Classification</th><th scope="col">Availability</th></tr></thead>
            <tbody>{sources.map(source => <tr key={source.id} className={selected?.id === source.id ? 'selected-row' : undefined}>
              <td><button className="source-title-button" ref={element => { if (element) rowRefs.current.set(source.id, element); else rowRefs.current.delete(source.id); }} aria-pressed={selected?.id === source.id} onClick={() => selectSource(source.id)}>{source.title || 'Untitled source'}<Icon name="chevron" size={15} /></button>
                <span className="cell-subtext source-host">{host(source.url)}</span>
                <div className={`source-tags ${styles.relationships}`}><span>{source.subject}</span><span>{source.run_ids.length} linked {source.run_ids.length === 1 ? 'run' : 'runs'}</span>{source.collection_ids?.length ? <span>{source.collection_ids.length} native {source.collection_ids.length === 1 ? 'collection' : 'collections'}</span> : null}{source.batch_ids?.length ? <span>{source.batch_ids.length} acquisition {source.batch_ids.length === 1 ? 'batch' : 'batches'}</span> : null}</div>
              </td>
              <td><SourceClassification source={source} /></td>
              <td><Badge value={source.content_access} /><span className="cell-subtext">Published {source.timestamps.published_at ? time(source.timestamps.published_at) : 'Unknown'}</span><span className="cell-subtext">Available {source.timestamps.available_at ? time(source.timestamps.available_at) : 'Unknown'}</span><details className={styles.temporal}><summary>Temporal eligibility</summary><SourceCutoff source={source} run={activeRun} /></details></td>
            </tr>)}</tbody>
          </table>
        </div> : <div className={styles.empty}>
          <Empty title={missingRun ? 'Research run not found' : query || effectiveRun !== 'all' ? 'No sources match this filter' : 'No source records available'}>
            {missingRun ? `No research run matches ${runId} in this loaded snapshot. Evidence from other runs is not substituted.` : query || effectiveRun !== 'all' ? 'Clear the page filter or choose another research run to inspect its sources.' : 'Load another subject, or refresh after a research run records source evidence.'}
          </Empty>
          {query || effectiveRun !== 'all' ? <button className="button button-secondary" onClick={() => writeRoute({ runId: 'all', filter: '', selectedId: '' }, 'push')}>Clear evidence filters</button> : null}
        </div>}
        {context ? <div className={`pagination ${styles.pagination}`}><span>{number(context.sources.length)} source receipts in this execution. Filters apply to these records.</span></div> : <div className={`pagination ${styles.pagination}`}>
          <span>{pagination.total_sources ? `${number(pagination.offset + 1)}–${number(pagination.offset + data.sources.length)} of ${number(pagination.total_sources)} source records` : '0 source records'}<small>Filters apply to the loaded page.</small></span>
          <div><button className="button button-secondary button-small" disabled={loading || pagination.offset === 0} onClick={() => page(Math.max(0, pagination.offset - pagination.limit))}>Previous</button><button className="button button-secondary button-small" disabled={loading || pagination.next_offset === null} onClick={() => pagination.next_offset !== null && page(pagination.next_offset)}>Next</button></div>
        </div>}
      </section>
    </div>
    <div className={styles.detail} ref={inspectorRef}>
      {selected ? <SourceInspector source={selected} run={activeRun} onSelectRun={context ? undefined : selectRun} onBack={backToEvidence} /> : <aside className={`inspector inspector-empty ${styles.missing}`}>
        <h2>{selectedId ? selectedOutsideView ? 'Evidence record not in this view' : 'Evidence record not found' : 'Source inspector'}</h2>
        <p>{selectedId ? selectedOutsideView ? 'The selected record is outside the active run or page filter. Clear the filter or select a visible record.' : `No evidence record matches ${selectedId} in this loaded snapshot.` : 'Select a source to inspect its timestamps, labels, and provenance.'}</p>
      </aside>}
    </div>
  </div>;
}
