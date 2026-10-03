import type { LiveResource, Observation } from './types';

export function resourcesAtNode(observation: Observation | null | undefined, nodeId: string): { kind: 'machines' | 'workers'; resource: LiveResource }[] {
  if (!observation) return [];
  const node = observation.stations[nodeId] ?? observation.buffers[nodeId];
  return (['machines', 'workers'] as const).flatMap(kind => Object.values(observation[kind])
    .filter(resource => resource.allocations?.some(allocation => allocation.station_id === nodeId)
      || (kind === 'machines' && node?.machine_ids?.includes(resource.id)))
    .map(resource => ({ kind, resource })));
}
