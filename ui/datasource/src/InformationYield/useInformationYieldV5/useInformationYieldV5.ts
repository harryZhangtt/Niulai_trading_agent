import { useEffect, useRef, useState } from 'react';
import { fetchInformationYieldV5, InformationYieldV5RequestError } from '../../services/apis/informationYieldV5';
import { adaptInformationYieldV5 } from '../adaptInformationYieldV5';
import type { InformationYieldErrorKind, InformationYieldViewModel } from '../viewModels';

interface State {
  key: string | null;
  data: InformationYieldViewModel | null;
  loading: boolean;
  error: InformationYieldErrorKind | null;
}

export function useInformationYieldV5(query: string | null) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<State>({ key: query, data: null, loading: query !== null, error: null });
  const identity = useRef(0);
  useEffect(() => {
    if (query === null) return;
    const current = ++identity.current;
    const controller = new AbortController();
    let timeout: number | null = null;
    setState(previous => ({ key: query, data: previous.key === query ? previous.data : null, loading: true, error: null }));
    const launch = window.setTimeout(() => {
      timeout = window.setTimeout(() => controller.abort('timeout'), 15000);
      void (async () => {
        try {
          const suffix = revision ? `${query}&refresh=1` : query;
          const wire = await fetchInformationYieldV5(suffix, controller.signal);
          const params = new URLSearchParams(query);
          const rawArm = params.get('arm');
          const arm: 'B0' | 'F' | null = rawArm === 'B0' || rawArm === 'F' ? rawArm : null;
          const data = adaptInformationYieldV5(wire, { evaluation: params.get('evaluation') ?? '', caseId: params.get('case'), arm });
          if (!data) throw new InformationYieldV5RequestError('schema_invalid');
          if (current === identity.current && !controller.signal.aborted) setState({ key: query, data, loading: false, error: null });
        } catch (error) {
          if (current !== identity.current || (controller.signal.aborted && controller.signal.reason !== 'timeout')) return;
          const kind: InformationYieldErrorKind = controller.signal.reason === 'timeout' ? 'timeout'
            : error instanceof InformationYieldV5RequestError ? error.kind : 'unavailable';
          const retain = kind === 'timeout' || kind === 'unavailable';
          setState(previous => ({ ...previous, data: retain ? previous.data : null, loading: false, error: kind }));
        } finally {
          if (timeout !== null) window.clearTimeout(timeout);
        }
      })();
    }, 0);
    return () => { window.clearTimeout(launch); controller.abort(); if (timeout !== null) window.clearTimeout(timeout); };
  }, [query, revision]);
  const current = state.key === query;
  return { data: current ? state.data : null, loading: query !== null && (!current || state.loading),
    error: current ? state.error : null, refresh: () => setRevision(value => value + 1) };
}
