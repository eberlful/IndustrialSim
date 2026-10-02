import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Graph } from './Graph';
import type { FlowNode, Model, Project, Route } from './types';
import './style.css';

function App() {
  const [project, setProject] = useState<Project>({ project: '', model: null });
  const [path, setPath] = useState('');
  const [yaml, setYaml] = useState('');
  const [name, setName] = useState('Imported YAML');
  const [diagnostics, setDiagnostics] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<FlowNode | Route | null>(null);
  useEffect(() => {
    fetch('/api/project').then(async (response) => {
      if (!response.ok) throw new Error(`Project request failed (${response.status})`);
      return response.json() as Promise<Project>;
    }).then((result) => { setProject(result); setPath(result.models?.[0] ?? ''); })
      .catch((error: Error) => setDiagnostics([error.message]));
  }, []);
  async function load(endpoint: string, body: object) {
    setBusy(true);
    try {
      const response = await fetch(`/api/project/${endpoint}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const result: Project = await response.json();
      if (result.accepted) {
        setProject((previous) => ({ ...previous, ...result }));
        setSelection(null);
        setDiagnostics([]);
      } else {
        setDiagnostics(result.diagnostics ?? [`Request failed (${response.status}). Check the YAML and retry.`]);
      }
    } catch (error) {
      setDiagnostics([error instanceof Error ? error.message : 'Could not reach the local service.']);
    } finally { setBusy(false); }
  }
  const model: Model | null = project.model;
  return <main>
    <header><div><p className="eyebrow">INDUSTRIALSIM / LOCAL PROJECT</p><h1>Plant workspace</h1><p className="project-path">{project.project || 'Connecting to local service…'}</p></div>
      <div className="status" role="status">{busy ? '◷ Validating…' : model ? '✓ Model valid' : '○ No model loaded'}</div></header>
    <section className="toolbar" aria-label="Project controls">
      <label>Project model <select value={path} onChange={(event) => setPath(event.target.value)} disabled={busy}>
        {!project.models?.length && <option value="">No project YAML files</option>}
        {project.models?.map((file) => <option key={file}>{file}</option>)}
      </select></label>
      <button disabled={busy || !path} onClick={() => void load('open', { path })}>Open model</button>
      <span>{model ? `Loaded: ${model.name}` : 'Open a project model or import YAML below'}</span>
    </section>
    {diagnostics.length > 0 && <section role="alert" className="diagnostics"><strong>⚠ Model was not loaded</strong><ul>{diagnostics.map((message, index) => <li key={index}>{message}</li>)}</ul><p>{model ? `Still displaying ${model.name}. Correct the YAML and retry.` : 'Correct the YAML and retry.'}</p></section>}
    <div className="workspace">
      <section className="graph-panel" aria-label="Material Flow Graph">
        <div className="panel-title"><h2>Material Flow Graph</h2><span>{model ? `${model.graph.nodes.length} nodes · ${model.graph.routes.length} routes` : 'No topology yet'}</span></div>
        <div className="graph-canvas">{model ? <Graph key={model.name + model.yaml} model={model} onSelect={setSelection}/> : <div className="empty"><strong>Inspect your Plant</strong><p>Load YAML to see sources, Stations, Buffers, sinks and their typed Ports.</p></div>}</div>
        <p className="hint">Select a node or route to inspect properties. Drag nodes to improve readability; positions are temporary.</p>
      </section>
      <aside>
        <section className="panel"><h2>Properties</h2>{selection ? <><h3>{selection.id}</h3><pre>{JSON.stringify(selection, null, 2)}</pre></> : <p>Select a node or route in the graph.</p>}</section>
        <section className="panel" aria-label="Episode controls"><h2>Episode</h2><p>○ Not started</p><button disabled>Start Episode</button><p className="hint">Execution controls will be available in a subsequent implementation issue.</p>{model && <details><summary>Loaded Episode inputs</summary><pre>{JSON.stringify({ seed: model.configuration.seed, episode: model.configuration.episode }, null, 2)}</pre></details>}</section>
        <section className="panel"><h2>Plant organization</h2><p className="hint">Area and Hall locations are separate from material flow.</p>{model?.plant ? <><h3>{model.plant.name}</h3>{model.plant.areas.map((area) => <details key={area.id}><summary>{area.name}</summary><ul>{area.halls.map((hall) => <li key={hall.id}>{hall.name} <small>({hall.id})</small></li>)}</ul></details>)}</> : <p>No Plant hierarchy declared.</p>}</section>
      </aside>
    </div>
    <details className="import-panel" open><summary>Import simulation YAML</summary>
      <p>Imports are validated in memory. Original files are preserved.</p>
      <label>YAML file <input type="file" accept=".yaml,.yml,text/yaml" disabled={busy} onChange={async (event) => {
        const file = event.target.files?.[0];
        if (file) { try { setYaml(await file.text()); setName(file.name); } catch { setDiagnostics(['Could not read the selected YAML file.']); } }
      }}/></label>
      <label>YAML content <textarea spellCheck={false} value={yaml} disabled={busy} onChange={(event) => { setYaml(event.target.value); setName('Imported YAML'); }}/></label>
      <button disabled={busy || !yaml.trim()} onClick={() => void load('import', { yaml, name })}>Validate and import</button>
    </details>
    {model && <details className="import-panel"><summary>Complete accepted configuration</summary><p>Includes sections outside the graph. Original YAML is retained for subsequent editing.</p><pre>{JSON.stringify(model.configuration, null, 2)}</pre></details>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
