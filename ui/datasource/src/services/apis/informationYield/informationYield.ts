import type { InformationYieldErrorKind } from '../../../InformationYield/viewModels';

export class InformationYieldRequestError extends Error {
  constructor(public kind: InformationYieldErrorKind) { super(kind); }
}

export async function fetchInformationYield(query: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(`/api/information-yield?${query}`, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) {
    const kind: InformationYieldErrorKind = response.status === 403
      ? 'permission_denied'
      : response.status === 404
        ? 'not_found'
        : response.status === 409
          ? 'conflict'
          : 'unavailable';
    throw new InformationYieldRequestError(kind);
  }
  return await response.json() as unknown;
}
