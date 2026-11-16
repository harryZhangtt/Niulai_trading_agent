import { adaptScheduler } from './adaptScheduler';

export async function fetchScheduler(query: string, signal: AbortSignal) {
  const response = await fetch(`/api/scheduler?${query}`, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw Error('request');
  return adaptScheduler(await response.json() as unknown);
}
