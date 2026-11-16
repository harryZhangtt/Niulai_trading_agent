import { useState, type ReactNode } from 'react';
import { Badge, Empty, Notice } from '../../components';
import { FactorTable } from '../FactorTable';
import { GateTable } from '../GateTable';
import { PerformancePanel } from '../PerformancePanel';
import { StageProgress } from '../StageProgress';
import { admissionLabel, instant, performanceLabel, provenanceLabel } from '../presentation';
import type { FactorMiningRun } from '../viewModels';
import styles from './RunDetails.module.css';

type RunView = 'overview' | 'performance' | 'factors' | 'evidence';
function bytes(value: number) { return new Intl.NumberFormat('en', { notation: value >= 1_000_000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value) + ' B'; }
function fact(label: string, value: ReactNode) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }

export function RunDetails({ run, loading, stale = false, partial = false, snapshotAt }: {
  run: FactorMiningRun | null; loading: boolean; stale?: boolean; partial?: boolean; snapshotAt?: string;
}) {
  const [view, setView] = useState<RunView>('overview');
  const [factorScope, setFactorScope] = useState('');
  if (!run) return <section className={styles.detail} id="factor-run-detail" aria-label="Selected factor run details" aria-busy={loading}><Empty title={loading ? 'Loading run details' : 'Select a factor-mining run'}>{loading ? 'The immutable run manifest is loading.' : 'Select a run to inspect its outcomes and evidence.'}</Empty></section>;
  const selectedFactor = run.factors.some(factor => factor.id === factorScope) ? factorScope : '';
  const inspectFactor = (id: string) => { setFactorScope(id); setView('performance'); };
  const views: Array<[RunView, string]> = [['overview', 'Overview'], ['performance', 'Performance'], ['factors', 'Factors'], ['evidence', 'Evidence']];
  return <section className={styles.detail} id="factor-run-detail" aria-label="Selected factor run details" aria-busy={loading}>
    {stale ? <Notice kind="warning" title="Run snapshot is stale"><p>The last successful run snapshot remains visible. Registry freshness does not establish current run evidence.</p></Notice> : null}
    {partial ? <Notice kind="warning" title="Run snapshot is incomplete"><p>Some run evidence is unavailable. Available records remain visible without inferring missing results.</p></Notice> : null}
    <div className={styles.heading}>
      <div><h2>{run.id}</h2><p>{instant(run.createdAt)} · revision {run.revision}</p></div>
      <Badge value={run.provenanceOrigin === 'synthetic_fixture' ? 'partial' : run.provenanceEvidence === 'unverified' ? 'partial' : run.status}>{provenanceLabel(run)}</Badge>
    </div>
    {run.provenanceOrigin === 'synthetic_fixture' ? <Notice kind="warning" title="Fixture evidence only"><p>This run verifies plumbing and failure handling. Synthetic performance is withheld and cannot support factor, EV or Kelly claims.</p></Notice> : null}
    {run.provenanceEvidence === 'unverified' ? <Notice kind="warning" title="Reported evidence is unverified"><p>Legacy scalar values and structured observations in this run are externally reported. They have not been reproduced locally.</p></Notice> : null}
    {run.failures.length ? <Notice kind="error" title="Recorded run failure"><ul>{run.failures.map(failure => <li key={`${failure.stageId}-${failure.code}`}>{failure.stageId}: <code>{failure.code}</code></li>)}</ul></Notice> : null}
    <nav className={styles.tabs} aria-label="Factor run views">
      {views.map(([key, title]) => <button key={key} aria-pressed={view === key} onClick={() => setView(key)}>{title}</button>)}
    </nav>
    {view === 'overview' ? <div className={styles.sections}>
      <section aria-labelledby="factor-run-outcome-title">
        <h3 id="factor-run-outcome-title">Recorded outcome</h3>
        <dl className={styles.outcomes}>
          {fact('Run execution', <Badge value={run.status}>{run.status.replaceAll('_', ' ')}</Badge>)}
          {fact('Performance evidence', performanceLabel(run))}
          {fact('Admission evidence', admissionLabel(run))}
          {fact('Factors recorded', run.factors.length)}
        </dl>
        <p className={styles.note}>Run completion is execution evidence. It does not establish factor quality or admission.</p>
      </section>
      <StageProgress stages={run.stages} />
      <GateTable gates={run.gates} />
    </div> : view === 'performance' ? <PerformancePanel run={run} selectedFactor={selectedFactor} onSelectFactor={setFactorScope} />
      : view === 'factors' ? <FactorTable factors={run.factors} selected={selectedFactor} onSelect={inspectFactor} />
        : <div className={styles.sections}>
          <section aria-labelledby="factor-run-evidence-title">
            <h3 id="factor-run-evidence-title">Run evidence and resources</h3>
            <dl className={styles.facts}>
              {fact('Provenance', provenanceLabel(run))}
              {fact('Qlib profile', run.qlibProfile)}
              {fact('Adapter', run.adapterVersion)}
              {fact('Wall time', `${run.wallSeconds.toFixed(3)} s`)}
              {fact('CPU time', `${run.cpuSeconds.toFixed(3)} s`)}
              {fact('Peak RSS', bytes(run.peakRssBytes))}
              {fact('Cache', run.cacheHit ? 'Reused' : 'Executed')}
              {fact('Manifest schema', `v${run.manifestSchemaVersion}`)}
              {fact('Artifact records', `${run.artifacts.length} loaded / ${run.artifactCount} recorded`)}
            </dl>
          </section>
          <StageProgress stages={run.stages} showReceipts />
          <GateTable gates={run.gates} showEvidence />
          <details className={styles.technical}>
            <summary>Immutable identities and artifacts</summary>
            <dl>{fact('Manifest SHA-256', <code>{run.manifestSha256}</code>)}{fact('Protocol SHA-256', <code>{run.protocolSha256 ?? 'Not bound'}</code>)}{fact('Dataset SHA-256', <code>{run.datasetSnapshotSha256 ?? 'Not bound'}</code>)}</dl>
            {run.artifacts.length ? <div className={styles.artifacts}>{run.artifacts.map(artifact => <p key={artifact.id}><strong>{artifact.id}</strong><span>{artifact.kind} · {bytes(artifact.sizeBytes)}</span><code>{artifact.sha256}</code></p>)}</div> : <p>No detail artifact records are available.</p>}
          </details>
          {run.limitations.length ? <section><h3>Limitations</h3><ul className={styles.limitations}>{run.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul></section> : null}
        </div>}
    <p className={styles.stamp}>{snapshotAt ? `Run snapshot ${instant(snapshotAt)}` : 'Run snapshot time unavailable'}{loading ? ' · Refreshing…' : ''}{stale || partial ? ' · Retained or incomplete evidence' : ''}</p>
  </section>;
}
