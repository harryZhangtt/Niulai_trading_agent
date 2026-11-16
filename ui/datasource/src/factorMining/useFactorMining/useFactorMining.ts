import { useEffect, useRef, useState } from 'react';
import { fetchFactorMining } from '../../services/apis/factorMining';
import { adaptFactorMining } from '../adaptFactorMining';
import type { FactorMiningViewModel } from '../viewModels';

interface State { key: string | null; data: FactorMiningViewModel | null; loading: boolean; error: string | null }

export function useFactorMining(query: string | null) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<State>({ key: query, data: null, loading: query !== null, error: null });
  const identity = useRef(0);
  useEffect(() => {
    if (query === null) return;
    const current = ++identity.current;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort('timeout'), 15_000);
    setState(previous => ({ key: query, data: previous.key === query ? previous.data : null,
      loading: true, error: null }));
    void (async () => {
      try {
        const wire = await fetchFactorMining(`${query}${query && revision ? '&' : ''}${revision ? 'refresh=1' : ''}`, controller.signal);
        const data = adaptFactorMining(wire);
        if (!data) throw new Error('shape');
        const expected = new URLSearchParams(query).get('run');
        if (expected && (data.runs.length !== 1 || data.runs[0].id !== expected)) throw new Error('identity');
        if (current === identity.current && !controller.signal.aborted) {
          setState({ key: query, data, loading: false, error: null });
        }
      } catch {
        if (current !== identity.current || (controller.signal.aborted && controller.signal.reason !== 'timeout')) return;
        setState(previous => ({ ...previous, loading: false,
          error: controller.signal.reason === 'timeout'
            ? 'The factor-mining request timed out. Refresh to try again.'
            : 'Factor-mining records could not be loaded. Check the local service and refresh.' }));
      } finally { window.clearTimeout(timer); }
    })();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [query, revision]);
  useEffect(() => {
    if (query === null) return;
    const timer = window.setInterval(() => { if (!document.hidden) setRevision(value => value + 1); }, 30_000);
    return () => window.clearInterval(timer);
  }, [query]);
  const current = state.key === query;
  return { data: current ? state.data : null, loading: query !== null && (!current || state.loading),
    error: current ? state.error : null, refresh: () => setRevision(value => value + 1) };
}
