import { useEffect, useRef, useState } from 'react';
import { Badge, Empty, Icon, Notice } from '../../components';
import { RunDetails } from '../RunDetails';
import { RunList } from '../RunList';
import { instant } from '../presentation';
import { useFactorMining } from '../useFactorMining';
import styles from './FactorMiningPage.module.css';
import WorkspaceChrome from '../../WorkspaceChrome';

function locationSelection() {
  const params = new URLSearchParams(location.search);
  return { run: params.get('run') ?? '', manifest: params.get('manifest') ?? '' };
}

const workflow = [
  ['Proposal and code', 'Define a factor and its financial mechanism.'],
  ['Qlib evaluation', 'Evaluate against a bound dataset and frozen protocol.'],
  ['Predictive evidence', 'Inspect held-out predictive estimates and uncertainty.'],
  ['Economic comparison', 'Compare standalone and combined results against a matched baseline.'],
  ['Admission and publication', 'Review the recorded gates before publishing evidence.'],
];

function EmptyRegistry({ partial }: { partial: boolean }) {
  return <section className={styles.emptyRegistry} aria-labelledby="factor-empty-title">
    <div className={styles.emptyIntro}>
      <h2 id="factor-empty-title">No factor-mining runs available</h2>
      <p>{partial ? 'Some registry evidence is unavailable. ' : ''}No immutable experiment records are available in this snapshot. Source checkouts and synthetic checks do not establish real-run readiness or factor performance.</p>
      <a className="button button-secondary" href="/datasource">Review research evidence<Icon name="external" size={16} /></a>
    </div>
    <section className={styles.workflow} aria-labelledby="factor-workflow-title">
      <h3 id="factor-workflow-title">How factor evidence progresses</h3>
      <p>This workflow explains the evidence path. It does not report installed runtime readiness.</p>
      <ol>{workflow.map(([title, description]) => <li key={title}>
        <div><strong>{title}</strong><p>{description}</p></div><Badge value="neutral">No run evidence</Badge>
      </li>)}</ol>
    </section>
    <p className={styles.emptyBoundary}>No published estimates or admission decisions are available. EV and Kelly stay withheld unless protected economic gates pass.</p>
  </section>;
}

export default function FactorMiningPage() {
  const overview = useFactorMining('');
  const [selection, setSelection] = useState(locationSelection);
  const [mobileDetail, setMobileDetail] = useState(Boolean(selection.run));
  const detailRoot = useRef<HTMLDivElement>(null);
  const focusDetail = useRef(false);
  const focusList = useRef(false);
  const runs = overview.data?.runs ?? [];
  const selected = selection.run || (!selection.manifest ? runs[0]?.id : '') || '';
  const detailParams = selected ? new URLSearchParams({ run: selected }) : null;
  if (detailParams && selection.manifest) detailParams.set('manifest', selection.manifest);
  const detail = useFactorMining(detailParams?.toString() ?? null);
  const detailRun = detail.data?.runs[0];
  const manifestMismatch = Boolean(detailRun && selection.manifest && detailRun.manifestSha256 !== selection.manifest);
  const validatedDetail = detailRun?.id === selected && !manifestMismatch ? detailRun : null;
  const overviewRun = !selection.manifest ? runs.find(item => item.id === selected) ?? null : null;
  const run = validatedDetail ?? overviewRun;
  const registryStale = Boolean(overview.error && overview.data) || overview.data?.stale === true;
  const registryPartial = overview.data?.status === 'partial';
  const detailStale = Boolean(detail.error && detail.data) || detail.data?.stale === true;
  const detailPartial = detail.data?.status === 'partial';
  const empty = Boolean(overview.data && !runs.length && !selection.run && !selection.manifest);

  useEffect(() => {
    function restoreLocation() { const next = locationSelection(); setSelection(next); setMobileDetail(Boolean(next.run)); }
    window.addEventListener('popstate', restoreLocation);
    return () => window.removeEventListener('popstate', restoreLocation);
  }, []);

  useEffect(() => {
    if (!focusDetail.current || !mobileDetail) return;
    const root = detailRoot.current;
    if (!root) return;
    const focusHeading = () => {
      const heading = root.querySelector<HTMLHeadingElement>('h2');
      if (!heading || heading.textContent !== selected) return;
      heading.tabIndex = -1; heading.focus(); focusDetail.current = false; observer.disconnect();
    };
    const observer = new MutationObserver(focusHeading);
    observer.observe(root, { childList: true, subtree: true });
    focusHeading();
    return () => observer.disconnect();
  }, [selected, selection.manifest, mobileDetail]);

  useEffect(() => {
    if (!focusList.current || mobileDetail) return;
    const frame = requestAnimationFrame(() => {
      const row = document.getElementById(`factor-run-row-${selected}`);
      (row ?? document.getElementById('factor-run-search'))?.focus(); focusList.current = false;
    });
    return () => cancelAnimationFrame(frame);
  }, [mobileDetail, selected]);

  function select(id: string) {
    setSelection({ run: id, manifest: '' });
    if (window.matchMedia('(max-width: 760px)').matches) { focusDetail.current = true; setMobileDetail(true); }
    const url = new URL(location.href); url.searchParams.set('run', id); url.searchParams.delete('manifest'); history.replaceState(null, '', url);
  }
  function backToRuns() { focusList.current = true; setMobileDetail(false); }
  function refresh() { overview.refresh(); if (selected) detail.refresh(); }

  return <>
    <a className="skip-link" href="#main-content">Skip to factor mining</a>
    <WorkspaceChrome active="factor" />
    <main className={styles.page} id="main-content">
      <div className={`page-heading ${styles.pageHeading}`}>
        <div><h1>Factor mining</h1><p>Inspect experiment outcomes, admission gates and comparative evidence.</p></div>
        <button className="button button-secondary" onClick={refresh} disabled={overview.loading || detail.loading}><Icon name="refresh" />{overview.loading || detail.loading ? 'Refreshing…' : 'Refresh runs'}</button>
      </div>
      <div className={styles.statusLine}>
        <Badge value={overview.data?.status === 'partial' ? 'partial' : 'neutral'}>{overview.data?.status === 'empty' ? 'Empty registry' : overview.data?.status === 'partial' ? 'Partial registry' : overview.data ? 'Registry available' : 'Loading registry'}</Badge>
        <span>{runs.length} immutable {runs.length === 1 ? 'run' : 'runs'} in this snapshot</span>
        <span>{overview.data ? `${registryStale ? 'Retained snapshot' : 'Snapshot'} ${instant(overview.data.generatedAt)}` : 'Connecting to the local registry'}</span>
        <span className={styles.autoRefresh}>Updates every 30 seconds</span>
      </div>
      {overview.error ? <Notice kind="error" title="Factor registry unavailable"><p>{overview.error}{overview.data ? ' The last successful snapshot remains visible.' : ''}</p></Notice> : null}
      {registryStale || registryPartial ? <Notice kind="warning" title="Some factor evidence is stale or unavailable"><p>{registryStale ? 'Showing a retained stale registry snapshot. ' : ''}Recorded immutable data remains visible. Missing evidence is not a passing gate.</p></Notice> : null}
      {empty ? <EmptyRegistry partial={registryPartial} /> : !overview.data && !selection.run ? overview.loading ? <section className={styles.loading} role="status">Loading the immutable run registry…</section> : <section className={styles.emptyRegistry}><Empty title="Factor registry unavailable">Refresh the registry to inspect experiments. No empty or successful result is inferred from an unavailable response.</Empty></section> : <>
        <p className={styles.boundary}>Run completion and admission are separate. Synthetic and reported evidence remain labelled; EV and Kelly stay withheld unless protected economic gates pass.</p>
        <div className={`${styles.layout}${mobileDetail ? ` ${styles.detailOpen}` : ''}`} aria-busy={overview.loading || detail.loading}>
          <div className={styles.listPanel}><RunList runs={runs} selected={selected} onSelect={select} /></div>
          <div className={styles.detailPanel} ref={detailRoot}>
            <div className={styles.mobileBack}><button className="button button-secondary" onClick={backToRuns}><Icon name="chevron" size={16} />Back to runs</button></div>
            {detail.error ? <Notice kind="error" title="Run details unavailable"><p>{detail.error}{overviewRun ? ' The overview record remains visible; structured detail evidence is not available.' : ''}</p><button className="button button-secondary" onClick={detail.refresh} disabled={detail.loading}>Refresh details</button></Notice> : null}
            {manifestMismatch ? <Notice kind="error" title="Requested manifest unavailable"><p>The response did not match the linked immutable manifest. A different revision is not substituted.</p></Notice> : null}
            {!run && !detail.loading && (selection.run || selection.manifest) ? <section className={styles.missing}><Empty title={selection.manifest ? 'Requested manifest unavailable' : 'Requested run not found'}>The linked immutable evidence is unavailable. Select a listed run to inspect its current manifest.</Empty></section>
              : <RunDetails key={`${selected}:${run?.manifestSha256 ?? selection.manifest}`} run={run} loading={detail.loading} stale={detailStale || Boolean(!validatedDetail && overviewRun && registryStale)} partial={detailPartial || Boolean(!validatedDetail && overviewRun && registryPartial)} snapshotAt={detail.data?.generatedAt ?? (overviewRun ? overview.data?.generatedAt : undefined)} />}
          </div>
        </div>
      </>}
      <footer className="snapshot-footer"><span>Immutable local evidence; registry and run snapshots are distinct.</span><span>Read-only; this page cannot run, retry or promote experiments.</span></footer>
    </main>
  </>;
}
