import type { FactorMiningWireResponse } from '../../../types/factorMiningApi';

export async function fetchFactorMining(query: string, signal: AbortSignal): Promise<FactorMiningWireResponse> {
  const response = await fetch(`/api/factor-mining?${query}`, {
    signal,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error('request');
  return await response.json() as FactorMiningWireResponse;
}
