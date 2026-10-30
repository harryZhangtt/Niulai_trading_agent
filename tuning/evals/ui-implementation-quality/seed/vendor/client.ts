import type { RevisionInput } from './contracts';

export class ServiceError extends Error {
  constructor(public status: number, public kind: 'rejected' | 'unknown', message: string) { super(message); }
}
async function decode(response: Response) {
  const value = await response.json();
  // The supplied transport performs asynchronous decoding after the network read.
  // Cancellation may no longer affect that work once the response has arrived.
  if (typeof value.deliveryLagMs === 'number') await new Promise(resolve => setTimeout(resolve, value.deliveryLagMs));
  if (!response.ok) throw new ServiceError(response.status, value.kind ?? 'rejected', value.message ?? 'Service request failed');
  return value;
}
export async function loadNotice(id: string, signal?: AbortSignal): Promise<unknown> {
  return decode(await fetch(`/api/notices/${encodeURIComponent(id)}`, { signal }));
}
export async function appendRevision(id: string, input: RevisionInput): Promise<unknown> {
  try {
    return await decode(await fetch(`/api/notices/${encodeURIComponent(id)}/revisions`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    }));
  } catch (error) {
    if (error instanceof ServiceError) throw error;
    throw new ServiceError(0, 'unknown', error instanceof Error ? error.message : 'Connection lost');
  }
}
export async function lookupOperation(operationId: string): Promise<unknown> {
  return decode(await fetch(`/api/operations/${encodeURIComponent(operationId)}`));
}
