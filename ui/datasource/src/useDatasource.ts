import { useEffect, useRef, useState } from 'react';
import type { DatasourceResponse } from './types';

interface Request { subject: string; offset: number; snapshot?: string; revision: number; refresh?: boolean }
interface State { subject: string; data: DatasourceResponse | null; loading: boolean; error: string | null }

function isResponse(value: unknown): value is DatasourceResponse {
  if (!value || typeof value !== 'object') return false;
  const data = value as Partial<DatasourceResponse>;
  return data.schema_version === 1 && typeof data.subject === 'string' && typeof data.snapshot_id === 'string'
    && Array.isArray(data.sources) && Array.isArray(data.runs) && Array.isArray(data.comparisons)
    && Array.isArray(data.aggregates?.cohorts) && typeof data.pagination?.total_sources === 'number';
}

export function useDatasource(initialSubject: string) {
  const [request, setRequest] = useState<Request>({ subject: initialSubject, offset: 0, revision: 0 });
  const [state, setState] = useState<State>({ subject: initialSubject, data: null, loading: true, error: null });
  const identity = useRef(0);

  useEffect(() => {
    const current = ++identity.current;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort('timeout'), 20_000);
    setState(previous => ({ subject: request.subject, data: previous.subject === request.subject ? previous.data : null, loading: true, error: null }));
    void (async () => {
      try {
        const params = new URLSearchParams({ subject: request.subject, limit: '100', offset: String(request.offset) });
        if (request.snapshot) params.set('snapshot_id', request.snapshot);
        if (request.refresh) params.set('refresh', '1');
        const response = await fetch(`/api/datasource?${params}`, { signal: controller.signal, headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error(response.status === 409 ? 'snapshot' : 'request');
        const data: unknown = await response.json();
        if (!isResponse(data) || data.subject.toUpperCase() !== request.subject.toUpperCase()) throw new Error('schema');
        if (identity.current === current && !controller.signal.aborted) setState({ subject: request.subject, data, loading: false, error: null });
      } catch (error) {
        if (identity.current !== current || (controller.signal.aborted && controller.signal.reason !== 'timeout')) return;
        const message = error instanceof Error && error.message === 'snapshot'
          ? 'The source snapshot changed. Refresh to load the current first page.'
          : error instanceof Error && error.message === 'schema'
            ? 'The datasource response could not be read. Refresh to try again.'
            : controller.signal.reason === 'timeout'
              ? 'The datasource request timed out. Refresh to try again.'
              : 'The datasource could not be loaded. Check the local API and refresh.';
        setState(previous => ({ ...previous, loading: false, error: message }));
      } finally { window.clearTimeout(timeout); }
    })();
    return () => { window.clearTimeout(timeout); controller.abort(); };
  }, [request]);

  function loadSubject(subject: string) {
    setRequest(previous => ({ subject, offset: 0, revision: previous.revision + 1 }));
    const next = new URL(window.location.href);
    next.pathname = '/datasource';
    next.searchParams.set('subject', subject);
    window.history.replaceState(null, '', next);
  }
  function refresh() { setRequest(previous => ({ subject: previous.subject, offset: 0, refresh: true, revision: previous.revision + 1 })); }
  function page(offset: number) { setRequest(previous => ({ ...previous, offset, refresh: false, snapshot: state.data?.snapshot_id, revision: previous.revision + 1 })); }

  // Never render another subject's last-good data under the current subject.
  const sameSubject = state.subject === request.subject;
  return { ...state, data: sameSubject ? state.data : null, loading: !sameSubject || state.loading, error: sameSubject ? state.error : null, subject: request.subject, loadSubject, refresh, page };
}
