import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Badge, Empty, Icon, Notice } from '../components';
import { MentorJobDetail } from './components/MentorJobDetail';
import { MentorJobRow } from './components/MentorJobRow';
import { StandardJobDetail } from './components/StandardJobDetail';
import { StandardJobRow } from './components/StandardJobRow';
import { displayDate } from './components/shared';
import { attentionReason, isCurrent, isRecurring, visibleJobs, type JobView } from './presentation';
import { useScheduler } from './useScheduler';
import './scheduler.css';
import WorkspaceChrome from '../WorkspaceChrome';

export default function SchedulerPage() {
  const { data, loading, error, refresh } = useScheduler('');
  const requested = new URLSearchParams(location.search).get('job') ?? '';
  const [filter, setFilter] = useState<JobView>(() => requested ? 'all' : 'current');
  const [search, setSearch] = useState('');
  const [zone, setZone] = useState('Asia/Shanghai');
  const [selection, setSelection] = useState(requested);
  const [mobileDetail, setMobileDetail] = useState(Boolean(requested));
  const detailRoot = useRef<HTMLDivElement>(null);
  const focusDetail = useRef(false);
  const focusRow = useRef(false);
  const jobs = data?.jobs ?? [];
  const current = jobs.filter(isCurrent);
  const attention = current.filter(job => attentionReason(job));
  const recurring = jobs.filter(job => job.enabled && isRecurring(job));
  const upcoming = current.filter(job => job.nextRunAt).sort((a, b) => Date.parse(a.nextRunAt!) - Date.parse(b.nextRunAt!));
  const next = upcoming[0];
  const visible = visibleJobs(jobs, filter, search);
  const selected = selection ? visible.find(job => job.id === selection) : visible[0];
  const stale = data?.projectionState === 'stale' || Boolean(error && data);
  const incomplete = data?.status === 'partial';

  useLayoutEffect(() => {
    if (mobileDetail || !focusRow.current) return;
    focusRow.current = false;
    document.getElementById(`job-row-${selected?.id}`)?.focus();
  }, [mobileDetail, selected?.id]);

  useEffect(() => {
    function restoreLocation() {
      const id = new URLSearchParams(location.search).get('job') ?? '';
      setSelection(id); setSearch(''); setFilter(id ? 'all' : 'current'); setMobileDetail(Boolean(id));
    }
    window.addEventListener('popstate', restoreLocation);
    return () => window.removeEventListener('popstate', restoreLocation);
  }, []);

  useEffect(() => {
    if (!focusDetail.current || !mobileDetail) return;
    const root = detailRoot.current;
    if (!root) return;
    const focusHeading = () => {
      const heading = root.querySelector<HTMLHeadingElement>('h2');
      if (!heading) return;
      heading.tabIndex = -1; heading.focus({ preventScroll: true });
      heading.scrollIntoView({ block: 'start', behavior: 'auto' }); focusDetail.current = false;
      observer.disconnect();
    };
    const observer = new MutationObserver(focusHeading);
    observer.observe(root, { childList: true, subtree: true });
    focusHeading();
    return () => observer.disconnect();
  }, [selection, mobileDetail]);

  function select(id: string) {
    setSelection(id);
    if (window.matchMedia('(max-width: 760px)').matches) {
      focusDetail.current = true; setMobileDetail(true);
    }
    const url = new URL(location.href); url.searchParams.set('job', id); history.replaceState(null, '', url);
  }
  function changeView(view: JobView) {
    setFilter(view); setSelection(''); setMobileDetail(false);
    const url = new URL(location.href); url.searchParams.delete('job'); history.replaceState(null, '', url);
  }
  function changeSearch(value: string) {
    setSearch(value); setSelection(''); setMobileDetail(false);
    const url = new URL(location.href); url.searchParams.delete('job'); history.replaceState(null, '', url);
  }
  function backToJobs() {
    focusRow.current = true;
    setMobileDetail(false);
  }

  return <>
    <a className="skip-link" href="#main-content">Skip to scheduler</a>
    <WorkspaceChrome active="scheduler" />
    <main className={`scheduler-page${mobileDetail ? ' scheduler-detail-open' : ''}`} id="main-content">
      <div className="page-heading">
        <div><h1>Scheduler</h1><p>Upcoming work, recorded outcomes and what needs your attention.</p></div>
        <div className="scheduler-refresh">
          <label htmlFor="scheduler-timezone">Display timezone<select id="scheduler-timezone" value={zone} onChange={event => setZone(event.target.value)}><option value="Asia/Shanghai">Shanghai (Asia/Shanghai)</option><option value="America/New_York">New York (America/New_York)</option><option value="UTC">UTC</option></select></label>
          <button className="button button-secondary" onClick={refresh} disabled={loading}><Icon name="refresh" />{loading ? 'Refreshing…' : 'Refresh jobs'}</button>
        </div>
      </div>
      <div className="scheduler-status-line">
        <Badge value={!stale && data?.health.state === 'healthy' ? 'verified' : 'partial'}>{stale ? 'Last recorded health: ' : 'Scheduler '}{data?.health.state ?? 'loading'}</Badge>
        {data ? <><span>{stale ? 'Retained snapshot' : 'Snapshot'} {displayDate(data.generatedAt, zone)}</span><span className="scheduler-heartbeat">Heartbeat {displayDate(data.health.heartbeatAt, zone)}</span></> : <span>Connecting to the local scheduler</span>}
        <span className="scheduler-auto-refresh">Updates every 30 seconds</span>
      </div>
      {error ? <Notice kind="error" title="Scheduler refresh failed"><p>{error}{data ? ' Showing the last successful snapshot.' : ''}</p></Notice> : null}
      {stale || incomplete ? <div role="alert"><Notice kind="warning" title="Some scheduler evidence is unavailable"><p>{stale ? 'Showing a retained stale snapshot.' : 'Service health and evidence availability are separate.'} Refresh to retry; missing evidence is not a successful delivery.</p></Notice></div> : null}
      <section className="scheduler-overview-strip" aria-label="Scheduler overview">
        <div className="scheduler-next-work">
          <span className="scheduler-summary-label">Next scheduled run</span>
          <strong>{data ? next ? displayDate(next.nextRunAt, zone) : 'No upcoming runs' : 'Loading schedule…'}</strong>
          {next ? <button className="scheduler-inline-link" onClick={() => select(next.id)}>{next.title}<Icon name="chevron" size={15} /></button> : <span className="subtle">Future work appears here when scheduled.</span>}
        </div>
        <button className="scheduler-summary-control" onClick={() => { setSearch(''); changeView('attention'); }} aria-pressed={filter === 'attention'}>
          <span className="scheduler-summary-label">Needs attention</span><strong>{data ? attention.length : '—'}</strong><span>{attention.length ? 'Review failures or uncertain evidence' : 'No current job issues recorded'}</span>
        </button>
        <button className="scheduler-summary-control" onClick={() => { setSearch(''); changeView('current'); }} aria-pressed={filter === 'current'}>
          <span className="scheduler-summary-label">Current jobs</span><strong>{data ? current.length : '—'}</strong><span>{recurring.length} recurring; finite work and mentor evidence</span>
        </button>
      </section>
      <div className="scheduler-controls">
        <div className="scheduler-search-field"><label htmlFor="scheduler-search">Find a job</label><div className="scheduler-search-input"><Icon name="search" /><input id="scheduler-search" type="search" value={search} onChange={event => changeSearch(event.target.value)} placeholder="Search name or job ID" /></div></div>
        <div><label htmlFor="scheduler-filter">Show</label><select id="scheduler-filter" value={filter} onChange={event => changeView(event.target.value as JobView)}><option value="current">Current jobs</option><option value="attention">Needs attention</option><option value="recurring">Recurring jobs</option><option value="all">All jobs, including historical tests</option></select></div>
        <p role="status" aria-atomic="true">{loading && !data ? 'Loading jobs…' : `${visible.length} ${visible.length === 1 ? 'job' : 'jobs'} shown`}</p>
      </div>
      <div className={`scheduler-layout${mobileDetail ? ' scheduler-mobile-detail' : ''}`}>
        <section className="scheduler-list" aria-label="Scheduled jobs">
          <div className="scheduler-list-heading"><h2>{filter === 'attention' ? 'Needs attention' : filter === 'all' ? 'All jobs' : filter === 'recurring' ? 'Recurring jobs' : 'Current jobs'}</h2><span>{visible.length}</span></div>
          {visible.length ? <ul>{visible.map(job => <li key={job.id}>{job.jobType === 'mentor' ? <MentorJobRow job={job} zone={zone} selected={selected?.id === job.id} onSelect={() => select(job.id)} /> : <StandardJobRow job={job} zone={zone} selected={selected?.id === job.id} onSelect={() => select(job.id)} />}</li>)}</ul>
            : loading ? <div className="loading-state" role="status">Loading scheduler jobs…</div> : <Empty title={search ? 'No jobs match your search' : filter === 'attention' ? 'No current jobs need attention' : 'No jobs in this view'}>{search ? 'Try another name or job ID.' : 'Choose All jobs to include completed and historical work.'}{search ? <button className="button button-secondary" onClick={() => setSearch('')}>Clear search</button> : <button className="button button-secondary" onClick={() => changeView('all')}>View all jobs</button>}</Empty>}
          <p className="scheduler-list-note">Current jobs include recurring work, upcoming finite tasks and enabled mentor evidence.</p>
        </section>
        <div className="scheduler-detail-panel" ref={detailRoot}>
          <div className="scheduler-mobile-back"><button className="button button-secondary" onClick={backToJobs}><Icon name="chevron" size={16} />Back to jobs</button></div>
          {selected ? selected.jobType === 'mentor' ? <MentorJobDetail key={selected.id} id={selected.id} zone={zone} /> : <StandardJobDetail key={selected.id} id={selected.id} zone={zone} />
            : <section className="scheduler-detail"><Empty title={selection ? 'Requested job not found' : 'Choose a job'}>{selection ? 'The linked job is not in this registry. Choose a listed job to inspect its evidence.' : 'Select a job to review its schedule and recorded outcomes.'}</Empty></section>}
        </div>
      </div>
      <footer className="snapshot-footer"><span>Local Codex jobs. Cloud price alerts are managed separately.</span><span>Read-only: scheduling, replay and delivery remain with their owners.</span></footer>
    </main>
  </>;
}
