import { useEffect, useState } from 'react';
import { Graph } from './Graph';
import type { Model, FlowNode } from './types';

type Result = { path: string; status: string; diagnostics: string[]; configuration: Record<string, unknown> | null;
  summary: { raw_metrics?: Record<string, unknown>; decision_diagnostics?: unknown[]; deadlock_diagnosis?: { reason: string; involved_entities: string[]; [key: string]: unknown }; [key: string]: unknown } | null;
  inspection: Record<string, unknown> };
const statusLabel = (status: string) => `${status === 'completed' ? '✓' : '⚠'} ${status}`;

export function SavedResults() {
  const [results, setResults] = useState<Pick<Result, 'path' | 'status'>[]>([]);
  const [path, setPath] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function refresh() {
    try {
      const response = await fetch('/api/results');
      if (!response.ok) throw new Error('Could not list saved Episode outputs.');
      setResults((await response.json()).results);
      setError('');
    } catch (e) { setError(String(e)); }
  }
  useEffect(() => { void refresh(); }, []);
  async function open() {
    setBusy(true); setResult(null); setSelected(null); setError('');
    try {
      const response = await fetch(`/api/results/open?path=${encodeURIComponent(path)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? 'Saved result unavailable.');
      setResult(data);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  const config = result?.configuration;
  const flow = config?.material_flow as Model['graph'] | null;
  const nodes = flow?.nodes ?? ((config?.stations ?? []) as FlowNode[]).map(station => ({ ...station, kind: 'station' as const, input_ports: [], output_ports: [] }));
  const model: Model | null = config ? { name: result!.path, yaml: '', configuration: config,
    graph: { nodes, routes: flow?.routes ?? [] }, plant: (config.plant ?? null) as Model['plant'],
    layout: { positions: {}, grouping: 'none' }, valid: true, graph_available: true, diagnostics: [] } : null;
  const diagnosis = result?.summary?.deadlock_diagnosis;
  const entity = selected && config ? [...nodes, ...(flow?.routes ?? []), ...((config.vehicles ?? []) as { id: string }[]), ...((config.machines ?? []) as { id: string }[]), ...((config.workers ?? []) as { id: string }[]), ...((config.production_units ?? []) as { id: string }[])].find(item => item.id === selected) : null;
  return <section className="import-panel" aria-label="Saved Episode results">
    <h2>Saved Episode results</h2>
    <label>Saved Episode output<select aria-label="Saved Episode output" value={path} disabled={busy} onChange={event => setPath(event.target.value)}>
      <option value="">Choose saved results…</option>{results.map(item => <option key={item.path} value={item.path}>{item.path} · {statusLabel(item.status)}</option>)}
    </select></label>
    <button onClick={() => void refresh()}>Refresh saved results</button>
    <button disabled={!path || busy} onClick={() => void open()}>Open saved results</button>
    {error && <p role="alert">{error}</p>}
    {result && <>
      <h3 aria-label="Saved result status">{statusLabel(result.status)} · {result.path}</h3>
      {result.diagnostics.map((text, index) => <p key={index}>{text}</p>)}
      <h3>Final raw metrics</h3>
      {result.summary?.raw_metrics ? <dl>{Object.entries(result.summary.raw_metrics).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{JSON.stringify(value)}</dd></div>)}</dl> : <p>Final metrics unavailable.</p>}
      <details><summary>Decision diagnostics</summary>{result.summary?.decision_diagnostics ? <pre>{JSON.stringify(result.summary.decision_diagnostics, null, 2)}</pre> : <p>Decision diagnostics unavailable in saved summary.</p>}</details>
      <section aria-label="Deadlock diagnosis"><h3>Deadlock diagnosis</h3>
        {diagnosis ? <><p>{diagnosis.reason}</p><p>Affected entities:</p>{diagnosis.involved_entities.map(id => <button key={id} onClick={() => setSelected(id)}>{id}</button>)}
          <details><summary>Wait relationships, capacities and ownership</summary><pre>{JSON.stringify(diagnosis, null, 2)}</pre></details></> : <p>{result.status === 'completed' ? 'Normal completion; no Deadlock recorded.' : 'Deadlock diagnosis unavailable in saved summary.'}</p>}
      </section>
      <h3>Original Episode configuration</h3>
      <p>This graph shows the saved resolved configuration. Final dynamic occupancy is unavailable in this view.</p>
      {model ? <><div className="graph-canvas"><Graph key={result.path} model={model} busy onMove={() => {}} onSelect={item => setSelected(item.id)}/></div>
        {selected && <section aria-label="Saved entity details"><h4>{selected}</h4>{entity ? <pre>{JSON.stringify(entity, null, 2)}</pre> : <p>Entity configuration unavailable for this identifier.</p>}</section>}
        <details><summary>Saved resolved configuration</summary><pre>{JSON.stringify(config, null, 2)}</pre></details></> : <p>Original configuration unavailable; graph unavailable.</p>}
      <details><summary>Saved summary and artifact metadata</summary><pre>{JSON.stringify({ summary: result.summary, inspection: result.inspection }, null, 2)}</pre></details>
    </>}
  </section>;
}
