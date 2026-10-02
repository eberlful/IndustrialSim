import { useEffect, useState } from 'react';
import type { Episode, LiveSelection } from './types';
import { resourcesAtNode } from './episodeResources';

type EventPage = { records: { record_id: number; simulated_time_ns: string; event_type: string; entity_ids: string[]; details: unknown }[];
  next_cursor: number; has_more: boolean };

export function EpisodeEvents({ episodeId }: { episodeId: string }) {
  const [cursor, setCursor] = useState(0);
  const [page, setPage] = useState<EventPage | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    setPage(null);
    async function read() {
      try {
        const response = await fetch(`/api/episode/events?episode_id=${encodeURIComponent(episodeId)}&cursor=${cursor}&limit=50`, { signal: controller.signal });
        if (!response.ok) throw new Error('Could not read this Episode event page.');
        const result: EventPage = await response.json();
        if (!disposed) { setPage(result); setError(''); }
      } catch (error) { if (!disposed) setError(error instanceof Error ? error.message : 'Could not read events.'); }
      finally { if (!disposed) timer = setTimeout(() => void read(), 1000); }
    }
    void read();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [episodeId, cursor]);
  return <section aria-label="Episode events" className="panel episode-events">
    <h2>Ordered Episode events</h2>
    <p>Records {cursor}–{page?.next_cursor ?? cursor} · Simulated time in ns · 50 records per page</p>
    <button disabled={cursor === 0} onClick={() => setCursor(Math.max(0, cursor - 50))}>Previous event page</button>
    <button disabled={!page?.has_more} onClick={() => setCursor(page!.next_cursor)}>Next event page</button>
    {error && <p role="alert">{error}</p>}
    <div className="event-scroll"><table><thead><tr><th>Order</th><th>Simulated time (ns)</th><th>Event</th><th>Entities and details</th></tr></thead>
      <tbody>{page?.records.map(record => <tr key={record.record_id}><td>{record.record_id}</td><td>{String(record.simulated_time_ns)}</td><td>{record.event_type}</td>
        <td>{record.entity_ids.join(', ')}<details><summary>Event details</summary><pre>{JSON.stringify(record.details, null, 2)}</pre></details></td></tr>)}</tbody></table></div>
  </section>;
}

export function EpisodeInspection({ episode, selection, onSelect }: { episode: Episode; selection: LiveSelection | null; onSelect: (selection: LiveSelection) => void }) {
  const observation = episode.observation;
  if (!observation) return <p>Waiting for the first authoritative snapshot…</p>;
  const entity = selection ? observation[selection.kind][selection.id] : null;
  const node = selection?.kind === 'stations' ? observation.stations[selection.id] : selection?.kind === 'buffers' ? observation.buffers[selection.id] : null;
  const resources = node ? resourcesAtNode(observation, node.id) : [];
  return <section aria-label="Live entity details" className="panel">
    <h2>Episode entity details</h2>
    <label>Live resource<select value={selection && ['machines', 'workers'].includes(selection.kind) ? `${selection.kind}:${selection.id}` : ''}
      onChange={event => { const colon = event.target.value.indexOf(':'); if (colon > 0) onSelect({ kind: event.target.value.slice(0, colon) as 'machines' | 'workers', id: event.target.value.slice(colon + 1) }); }}>
      <option value="">Choose a Machine or Worker…</option>
      {(['machines', 'workers'] as const).map(kind => <optgroup key={kind} label={kind}>{Object.keys(observation[kind]).map(id => <option key={id} value={`${kind}:${id}`}>{id}</option>)}</optgroup>)}
    </select></label>
    {entity ? <div aria-label={selection?.kind === 'production_units' ? 'Production Unit details' : 'Resource state'}>
      <h3>{entity.id}</h3><pre>{JSON.stringify(entity, null, 2)}</pre>
    </div> : <p>Select a Station or Buffer in the Episode graph, or choose a resource.</p>}
    {node && <><h3>Production Units</h3>{node.unit_ids.length === 0 ? <p>No Production Units at this node.</p> : node.unit_ids.map(id =>
      <button key={id} onClick={() => onSelect({ kind: 'production_units', id })}>{id}</button>)}
      <h3>Resources</h3>{resources.map(({ kind, resource }) => <button key={`${kind}:${resource.id}`} onClick={() => onSelect({ kind, id: resource.id })}>{resource.id} · {resource.available_capacity}/{resource.capacity} available</button>)}
    </>}
  </section>;
}

export function EpisodeMetrics({ episode }: { episode: Episode }) {
  return <section className="panel" aria-label="Live raw metrics"><h2>Current raw metrics</h2>
    <dl className="outcome-metrics">{Object.entries(episode.observation?.raw_metrics ?? {}).map(([metric, value]) => <div key={metric}><dt>{metric.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>)}</dl>
  </section>;
}
