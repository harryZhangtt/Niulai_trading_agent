import type { InformationYieldErrorKind } from '../../../InformationYield/viewModels';

export class InformationYieldV5RequestError extends Error {
  constructor(public kind: InformationYieldErrorKind) { super(kind); }
}

export async function fetchInformationYieldV5(query: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(`/api/information-yield/v5?${query}`, {
    signal,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    const kind: InformationYieldErrorKind = response.status === 403
      ? 'permission_denied'
      : response.status === 404
        ? 'not_found'
        : response.status === 409
          ? 'conflict'
          : 'unavailable';
    throw new InformationYieldV5RequestError(kind);
  }
  return await response.json() as unknown;
}
