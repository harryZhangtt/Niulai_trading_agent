import { useEffect, useRef, useState } from 'react';
import { fetchInformationYield, InformationYieldRequestError } from '../../services/apis/informationYield';
import { adaptInformationYield } from '../adaptInformationYield';
import type { InformationYieldErrorKind, InformationYieldViewModel } from '../viewModels';

interface State {
  key: string | null;
  data: InformationYieldViewModel | null;
  loading: boolean;
  error: InformationYieldErrorKind | null;
}

export function useInformationYield(query: string | null) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<State>({ key: query, data: null, loading: query !== null, error: null });
  const identity = useRef(0);

  useEffect(() => {
    if (query === null) return;
    const current = ++identity.current;
    const controller = new AbortController();
    let timeout: number | null = null;
    setState(previous => ({ key: query, data: previous.key === query ? previous.data : null, loading: true, error: null }));

    // Delay transport start by one task so React StrictMode's throwaway effect can clean up
    // without emitting a duplicate read. Identity and abort guards still fence stale work.
    const launch = window.setTimeout(() => {
      timeout = window.setTimeout(() => controller.abort('timeout'), 15000);
      void (async () => {
        try {
          const suffix = revision ? `${query}&refresh=1` : query;
          const wire = await fetchInformationYield(suffix, controller.signal);
          const params = new URLSearchParams(query);
          const rawArm = params.get('arm');
          const arm: 'B0' | 'F' | null = rawArm === 'B0' || rawArm === 'F' ? rawArm : null;
          const expected = {
            evaluation: params.get('evaluation') ?? '',
            caseId: params.get('case'),
            arm,
            run: params.get('run'),
            source: params.get('source'),
          };
          const data = adaptInformationYield(wire, expected);
          if (!data) throw new InformationYieldRequestError('schema_invalid');
          if (current === identity.current && !controller.signal.aborted) {
            setState({ key: query, data, loading: false, error: null });
          }
        } catch (error) {
          if (current !== identity.current || (controller.signal.aborted && controller.signal.reason !== 'timeout')) return;
          const kind: InformationYieldErrorKind = controller.signal.reason === 'timeout'
            ? 'timeout'
            : error instanceof InformationYieldRequestError
              ? error.kind
              : 'unavailable';
          setState(previous => ({ ...previous, loading: false, error: kind }));
        } finally {
          if (timeout !== null) window.clearTimeout(timeout);
        }
      })();
    }, 0);

    return () => {
      window.clearTimeout(launch);
      controller.abort();
      if (timeout !== null) window.clearTimeout(timeout);
    };
  }, [query, revision]);

  const current = state.key === query;
  return {
    data: current ? state.data : null,
    loading: query !== null && (!current || state.loading),
    error: current ? state.error : null,
    refresh: () => setRevision(value => value + 1),
  };
}
