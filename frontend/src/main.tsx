import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Graph } from './Graph';
import { Properties, type ParameterEdit } from './Properties';
import type { Model, Project } from './types';
import './style.css';

function App() {
  const [project, setProject] = useState<Project>({ project: '', model: null });
  const [path, setPath] = useState('');
  const [yaml, setYaml] = useState('');
  const [name, setName] = useState('Imported YAML');
  const [diagnostics, setDiagnostics] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<{ kind: 'node' | 'route'; id: string } | null>(null);
  const [savePath, setSavePath] = useState('plant.yaml');
  const [overwrite, setOverwrite] = useState(false);
  const [saved, setSaved] = useState('');
  useEffect(() => {
    fetch('/api/project').then(async (response) => {
      if (!response.ok) throw new Error(`Project request failed (${response.status})`);
      return response.json() as Promise<Project>;
    }).then((result) => { setProject(result); setPath(result.models?.[0] ?? ''); setDiagnostics(result.diagnostics ?? []); })
      .catch((error: Error) => setDiagnostics([error.message]));
  }, []);
  async function load(endpoint: string, body: object) {
    setBusy(true);
    try {
      const response = await fetch(`/api/project/${endpoint}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const result: Project = await response.json();
      if (result.accepted) {
        setProject((previous) => ({ ...previous, ...result }));
        if (endpoint === 'open' || endpoint === 'import') setSelection(null);
        if (endpoint !== 'save') setSaved('');
        setDiagnostics(result.diagnostics ?? []);
        if (result.saved_path) { setSaved(`Saved: ${result.saved_path}`); setPath(result.saved_path); setOverwrite(false); }
      } else {
        setDiagnostics(result.diagnostics ?? [`Request failed (${response.status}). Check the YAML and retry.`]);
      }
    } catch (error) {
      setDiagnostics([error instanceof Error ? error.message : 'Could not reach the local service.']);
    } finally { setBusy(false); }
  }
  const model: Model | null = project.model;
  const selectedElement = selection?.kind === 'node'
    ? model?.graph.nodes.find(node => node.id === selection.id)
    : model?.graph.routes.find(route => route.id === selection?.id);
  async function download() {
    setBusy(true);
    try {
      const response = await fetch('/api/project/export');
      if (!response.ok) {
        const result: Project = await response.json();
        setDiagnostics(result.diagnostics ?? ['Could not export YAML.']);
        return;
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url; link.download = 'plant.yaml'; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { setDiagnostics(['Could not reach the local service to export YAML.']); }
    finally { setBusy(false); }
  }
  return <main>
    <header><div><p className="eyebrow">INDUSTRIALSIM / LOCAL PROJECT</p><h1>Plant workspace</h1><p className="project-path">{project.project || 'Connecting to local service…'}</p></div>
      <div className="status" role="status">{busy ? '◷ Validating…' : model ? model.valid ? '✓ Model valid' : '⚠ Draft invalid' : '○ No model loaded'}</div></header>
    <section className="toolbar" aria-label="Project controls">
      <label>Project model <select value={path} onChange={(event) => setPath(event.target.value)} disabled={busy}>
        {!project.models?.length && <option value="">No project YAML files</option>}
        {project.models?.map((file) => <option key={file}>{file}</option>)}
      </select></label>
      <button disabled={busy || !path} onClick={() => void load('open', { path })}>Open model</button>
      <span>{model ? `Loaded: ${model.name}` : 'Open a project model or import YAML below'}</span>
      <button disabled={busy || !project.can_undo} onClick={() => void load('undo', {})}>Undo</button>
      <button disabled={busy || !project.can_redo} onClick={() => void load('redo', {})}>Redo</button>
      <button disabled={busy || !model?.valid} onClick={() => void download()}>Download YAML</button>
    </section>
    {diagnostics.length > 0 && <section role="alert" className="diagnostics"><strong>{model && !model.valid ? '⚠ Draft needs correction' : '⚠ Action was not accepted'}</strong><ul>{diagnostics.map((message, index) => <li key={index}>{message}</li>)}</ul><p>{model && !model.valid ? 'Correct the indicated properties or undo the change. Saving and executable export require a valid draft.' : model ? `Still displaying ${model.name}. Correct the input and retry.` : 'Correct the YAML and retry.'}</p></section>}
    <div className="workspace">
      <section className="graph-panel" aria-label="Material Flow Graph">
        <div className="panel-title"><h2>Material Flow Graph</h2><span>{model ? `${model.graph.nodes.length} nodes · ${model.graph.routes.length} routes` : 'No topology yet'}</span></div>
        <div className="graph-canvas">{model ? <Graph key={model.name + model.yaml} model={model} onSelect={element => setSelection({ kind: 'kind' in element ? 'node' : 'route', id: element.id })}/> : <div className="empty"><strong>Inspect your Plant</strong><p>Load YAML to see sources, Stations, Buffers, sinks and their typed Ports.</p></div>}</div>
        <p className="hint">Select a node or route to inspect properties. Drag nodes to improve readability; positions are temporary.</p>
      </section>
      <aside>
        <section className="panel"><h2>Properties</h2>{selectedElement && model && selection ? <Properties key={selection.kind + selection.id + model.yaml} element={selectedElement} kind={selection.kind} model={model} busy={busy} edit={(command: ParameterEdit) => load('edit', command)}/> : <p>Select a node or route in the graph.</p>}</section>
        <section className="panel" aria-label="Episode controls"><h2>Episode</h2><p>○ Not started</p><button disabled>Start Episode</button><p className="hint">Execution controls will be available in a subsequent implementation issue.</p>{model && <details><summary>Loaded Episode inputs</summary><pre>{JSON.stringify({ seed: model.configuration.seed, episode: model.configuration.episode }, null, 2)}</pre></details>}</section>
        <section className="panel"><h2>Plant organization</h2><p className="hint">Area and Hall locations are separate from material flow.</p>{model?.plant ? <><h3>{model.plant.name}</h3>{model.plant.areas.map((area) => <details key={area.id}><summary>{area.name}</summary><ul>{area.halls.map((hall) => <li key={hall.id}>{hall.name} <small>({hall.id})</small></li>)}</ul></details>)}</> : <p>No Plant hierarchy declared.</p>}</section>
      </aside>
    </div>
    {model && <section className="import-panel save-panel" aria-label="Save model">
      <h2>Save validated YAML</h2><p>Save explicitly to a project-local file. Existing files require overwrite to be enabled.</p>
      <label>Save as project path<input value={savePath} disabled={busy} onChange={event => { setSavePath(event.target.value); setOverwrite(false); setSaved(''); }}/></label>
      <label><input type="checkbox" checked={overwrite} disabled={busy} onChange={event => setOverwrite(event.target.checked)}/>Overwrite existing file at this path</label>
      <button disabled={busy || !model.valid || !savePath.trim()} onClick={() => void load('save', { path: savePath, overwrite })}>Save YAML</button>
      {saved && <p>{saved}</p>}
    </section>}
    <details className="import-panel" open><summary>Import simulation YAML</summary>
      <p>Imports are validated in memory. Original files are preserved.</p>
      <label>YAML file <input type="file" accept=".yaml,.yml,text/yaml" disabled={busy} onChange={async (event) => {
        const file = event.target.files?.[0];
        if (file) { try { setYaml(await file.text()); setName(file.name); } catch { setDiagnostics(['Could not read the selected YAML file.']); } }
      }}/></label>
      <label>YAML content <textarea spellCheck={false} value={yaml} disabled={busy} onChange={(event) => { setYaml(event.target.value); setName('Imported YAML'); }}/></label>
      <button disabled={busy || !yaml.trim()} onClick={() => void load('import', { yaml, name })}>Validate and import</button>
    </details>
    {model && <details className="import-panel"><summary>Complete project draft</summary><p>Includes sections outside the graph. Edits and export use this project draft.</p><pre>{JSON.stringify(model.configuration, null, 2)}</pre></details>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
