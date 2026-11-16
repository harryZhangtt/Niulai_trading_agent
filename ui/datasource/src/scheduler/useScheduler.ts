import { useEffect, useRef, useState } from 'react';
import { fetchScheduler } from '../services/apis/scheduler';
import type { SchedulerData } from './types';

export function useScheduler(query: string | null) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ key: string | null; data: SchedulerData | null; loading: boolean; error: string | null }>({ key: query, data: null, loading: query !== null, error: null });
  const identity = useRef(0);
  useEffect(() => {
    if (query === null) return;
    const current = ++identity.current;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort('timeout'), 15_000);
    setState(previous => ({ key: query, data: previous.key === query ? previous.data : null, loading: true, error: previous.key === query ? previous.error : null }));
    const requestQuery = `${query}${revision ? `${query ? '&' : ''}refresh=1` : ''}`;
    void (async () => {
      try {
        const data = await fetchScheduler(requestQuery, controller.signal);
        const parameters = new URLSearchParams(query);
        const expected = parameters.get('job');
        const output = parameters.get('output');
        if (expected && (data.jobs.length !== 1 || data.jobs[0].id !== expected)) throw Error('identity');
        const selected = data.jobs[0];
        if (output && (selected?.jobType !== 'standard' || selected.output?.id !== output)) throw Error('identity');
        if (current === identity.current && !controller.signal.aborted) setState({ key: query, data, loading: false, error: null });
      } catch {
        if (current !== identity.current || (controller.signal.aborted && controller.signal.reason !== 'timeout')) return;
        setState(previous => ({ ...previous, loading: false, error: controller.signal.reason === 'timeout'
          ? 'The scheduler request timed out. Refresh to try again.'
          : 'Scheduler details could not be loaded. Check the local service and refresh.' }));
      } finally { window.clearTimeout(timer); }
    })();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [query, revision]);
  useEffect(() => {
    if (query === null) return;
    const timer = window.setInterval(() => { if (!document.hidden) setRevision(value => value + 1); }, 30_000);
    return () => window.clearInterval(timer);
  }, [query]);
  const current = query === state.key;
  return { data: current ? state.data : null, loading: query !== null && (!current || state.loading), error: current ? state.error : null, refresh: () => setRevision(value => value + 1) };
}
