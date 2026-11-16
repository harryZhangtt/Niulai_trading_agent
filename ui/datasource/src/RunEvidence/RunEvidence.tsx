import type { MouseEvent } from 'react';
import { Empty, Icon, Notice, SourceInspector } from '../components';
import type { Run, Source } from '../types';
import styles from './RunEvidence.module.css';

interface RunEvidenceProps {
  sources: Source[];
  subject: string;
  run?: Run;
  runLabel: string;
  relationshipComplete: boolean;
  missingRelationships: number;
  selectedSourceId: string;
  evidenceHref: (sourceId: string) => string;
  onSelectSource: (event: MouseEvent<HTMLAnchorElement>, sourceId: string) => void;
}

export default function RunEvidence({
  sources,
  subject,
  run,
  runLabel,
  relationshipComplete,
  missingRelationships,
  selectedSourceId,
  evidenceHref,
  onSelectSource,
}: RunEvidenceProps) {
  const selected = selectedSourceId ? sources.find(source => source.id === selectedSourceId) : undefined;
  const invalidSelection = Boolean(selectedSourceId) && !selected;
  const globalHref = `/datasource?subject=${encodeURIComponent(subject)}&view=evidence`;

  return <section className={styles.root} aria-labelledby="run-evidence-title">
    <div className={styles.heading}>
      <div><h3 id="run-evidence-title">Evidence bound to this run</h3><p>Only records explicitly linked to {runLabel} are shown. Evidence from other runs is excluded.</p></div>
      <strong>{sources.length} {sources.length === 1 ? 'record' : 'records'}</strong>
    </div>
    {!relationshipComplete ? <Notice kind="warning" title="Run relationship coverage is incomplete"><p>This snapshot does not contain every evidence page. Missing relationships remain unavailable rather than being treated as no evidence.</p></Notice> : null}
    {missingRelationships > 0 ? <Notice kind="warning" title="Some bound evidence is not on this loaded page"><p>{missingRelationships} recorded {missingRelationships === 1 ? 'relationship is' : 'relationships are'} unavailable in this snapshot.</p></Notice> : null}
    {sources.length ? <div className={styles.layout}>
      <div className={styles.ledger}>
        <ul>{sources.map(source => <li className={selected?.id === source.id ? styles.selected : undefined} key={source.id}>
          <a href={evidenceHref(source.id)} aria-current={selected?.id === source.id ? 'true' : undefined} onClick={event => onSelectSource(event, source.id)}><span>{source.title || 'Untitled source'}</span><Icon name="chevron" size={14} /></a>
          <code>{source.id}</code>
        </li>)}</ul>
        <a className={styles.secondary} href={globalHref}>Open the global evidence index</a>
      </div>
      <div className={styles.detail}>
        {invalidSelection ? <Empty title="Evidence record not found for this run">No evidence bound to this run matches {selectedSourceId}. The first record was not selected automatically.</Empty> : selected ? <SourceInspector source={selected} run={run} /> : <Empty title="Choose run evidence">Select one evidence record to inspect its exact source, timeline, hashes, and run-bound temporal decision.</Empty>}
      </div>
    </div> : <Empty title={relationshipComplete ? 'No evidence bound to this run' : 'Run evidence is not fully available'}>{relationshipComplete ? 'This run records no bound evidence. The global evidence index is not substituted.' : 'Load the complete snapshot before concluding that this run has no evidence.'}</Empty>}
  </section>;
}
