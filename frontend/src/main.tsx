import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Graph, arrangedPositions } from './Graph';
import { GraphTools, PortEditor, RouteConnections } from './GraphEditing';
import { Properties } from './Properties';
import { ResourceProperties, resourceDefinitions } from './Resources';
import type { ParameterEdit } from './parameterEditing';
import type { FlowNode, Model, Project, Route } from './types';
import './style.css';

function App() {
  const [project, setProject] = useState<Project>({ project: '', model: null });
  const [path, setPath] = useState('');
  const [yaml, setYaml] = useState('');
  const [name, setName] = useState('Imported YAML');
  const [diagnostics, setDiagnostics] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<{ kind: 'node' | 'route' | 'machine' | 'worker'; id: string } | null>(null);
  const [savePath, setSavePath] = useState('plant.yaml');
  const [overwrite, setOverwrite] = useState(false);
  const [saved, setSaved] = useState('');
  const [draftName, setDraftName] = useState('work.json');
  const [draftPath, setDraftPath] = useState('');
  const [draftOverwrite, setDraftOverwrite] = useState(false);
  const [draftSaved, setDraftSaved] = useState('');
  useEffect(() => {
    fetch('/api/project').then(async (response) => {
      if (!response.ok) throw new Error(`Project request failed (${response.status})`);
      return response.json() as Promise<Project>;
    }).then((result) => { setProject(result); setPath(result.models?.[0] ?? ''); setDraftPath(result.drafts?.[0] ?? ''); setDiagnostics(result.diagnostics ?? []); })
      .catch((error: Error) => setDiagnostics([error.message]));
  }, []);
  async function load(endpoint: string, body: object) {
    setBusy(true);
    try {
      const response = await fetch(`/api/project/${endpoint}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const result: Project = await response.json();
      if (result.accepted) {
        setProject((previous) => ({ ...previous, ...result }));
        if (endpoint === 'open' || endpoint === 'import' || endpoint === 'draft/open') setSelection(null);
        if (endpoint !== 'save') setSaved('');
        setDiagnostics(result.diagnostics ?? []);
        if (result.saved_draft) { setDraftSaved(`Draft saved: ${result.saved_draft}`); setDraftPath(result.saved_draft); setDraftOverwrite(false); }
        else setDraftSaved('');
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
    : selection?.kind === 'route' ? model?.graph.routes.find(route => route.id === selection.id) : undefined;
  const selectedResource = model && (selection?.kind === 'machine' || selection?.kind === 'worker')
    ? resourceDefinitions(model, selection.kind).find(resource => resource.id === selection.id) : undefined;
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
      {model && <><label>Display grouping<select aria-label="Display grouping" value={model.layout.grouping} disabled={busy}
        onChange={event => { const grouping = event.target.value as 'none' | 'area' | 'hall'; void load('layout', { grouping, positions: arrangedPositions(model, grouping) }); }}>
        <option value="none">None</option><option value="area">Area</option><option value="hall">Hall</option>
      </select></label><button disabled={busy} onClick={() => void load('layout/save', {})}>Save layout</button></>}
      <span>{model ? `Loaded: ${model.name}` : 'Open a project model or import YAML below'}</span>
      <button disabled={busy || !project.can_undo} onClick={() => void load('undo', {})}>Undo</button>
      <button disabled={busy || !project.can_redo} onClick={() => void load('redo', {})}>Redo</button>
      <button disabled={busy || !model?.valid} onClick={() => void download()}>Download YAML</button>
    </section>
    {diagnostics.length > 0 && <section role="alert" className="diagnostics"><strong>{model && !model.valid ? '⚠ Draft needs correction' : '⚠ Action was not accepted'}</strong><ul>{diagnostics.map((message, index) => <li key={index}>{message}</li>)}</ul><p>{model && !model.valid ? 'Correct the indicated properties or undo the change. Save incomplete work as a draft. Executable YAML requires all errors to be corrected.' : model ? `Still displaying ${model.name}. Correct the input and retry.` : 'Correct the YAML and retry.'}</p></section>}
    <div className="workspace">
      <section className="graph-panel" aria-label="Material Flow Graph">
        <div className="panel-title"><h2>Material Flow Graph</h2><span>{model ? `${model.graph.nodes.length} nodes · ${model.graph.routes.length} routes` : 'No topology yet'}</span></div>
        <div className="graph-canvas">{model ? <Graph key={model.name} model={model} busy={busy} onMove={positions => void load('layout', { positions })} onSelect={element => setSelection({ kind: 'kind' in element ? 'node' : 'route', id: element.id })}/> : <div className="empty"><strong>Inspect your Plant</strong><p>Load YAML to see sources, Stations, Buffers, sinks and their typed Ports.</p></div>}</div>
        <p className="hint">Select a node or route to inspect properties. Drag nodes to improve readability; save layout to restore positions and display grouping. Grouping uses existing assignments.</p>
      </section>
      <aside>
        <section className="panel" aria-label="Properties"><h2>Properties</h2>{model && <label className="resource-selector">Resource definition<select disabled={busy} value={selectedResource && selection ? `${selection.kind}:${selection.id}` : ''} onChange={event => {
          const value = event.target.value;
          if (!value) setSelection(null);
          else { const colon = value.indexOf(':'); setSelection({ kind: value.slice(0, colon) as 'machine' | 'worker', id: value.slice(colon + 1) }); }
        }}><option value="">Choose a Machine or Worker…</option>{(['machine', 'worker'] as const).map(kind => <optgroup key={kind} label={kind === 'machine' ? 'Machines' : 'Workers'}>{resourceDefinitions(model, kind).map(resource => <option key={resource.id} value={`${kind}:${resource.id}`}>{resource.name ?? resource.id} ({resource.id})</option>)}</optgroup>)}</select></label>}
          {selectedResource && model && selection && (selection.kind === 'machine' || selection.kind === 'worker') && <ResourceProperties key={selection.kind + selection.id + model.yaml} resource={selectedResource} kind={selection.kind} model={model} busy={busy} edit={command => load('edit', command)}/>}{selectedElement && model && selection && (selection.kind === 'node' || selection.kind === 'route') ? <Properties key={selection.kind + selection.id + model.yaml} element={selectedElement} kind={selection.kind} model={model} busy={busy} edit={(command: ParameterEdit) => load('edit', command)}/> : !selectedResource && <p>Select a node or route in the graph, or choose a resource.</p>}
          {selectedElement && model && model.configuration.material_flow != null && selection && (selection.kind === 'node' || selection.kind === 'route') && <>
            {selection.kind === 'node' ? <PortEditor key={`ports:${selectedElement.id}:${model.yaml}`} node={selectedElement as FlowNode} busy={busy} command={command => load('structure', command)}/>
              : <RouteConnections key={`connection:${selectedElement.id}:${model.yaml}`} model={model} route={selectedElement as Route} busy={busy} command={command => load('structure', command)}/>}
            <button disabled={busy} onClick={() => void load('structure', { action: 'delete', kind: selection.kind, element_id: selection.id })}>Delete {selection.kind}</button>
            <p className="hint">References are retained and reported for correction. Undo restores the element.</p>
          </>}
        </section>
        {model && <section className="panel" aria-label="Graph editing"><h2>Graph editing</h2><GraphTools model={model} busy={busy} command={command => load('structure', command)} select={route => setSelection({ kind: 'route', id: route.id })}/></section>}
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
    <section className="import-panel save-panel" aria-label="Project drafts">
      <h2>Incomplete drafts</h2><p>Save unfinished work separately, including validation errors and presentation.</p>
      <label>Draft filename<input value={draftName} disabled={busy} onChange={event => { setDraftName(event.target.value); setDraftOverwrite(false); setDraftSaved(''); }}/></label>
      <label><input type="checkbox" checked={draftOverwrite} disabled={busy} onChange={event => setDraftOverwrite(event.target.checked)}/>Overwrite existing draft</label>
      <button disabled={busy || !model || !draftName.trim()} onClick={() => void load('draft/save', { path: draftName, overwrite: draftOverwrite })}>Save draft</button>
      <label>Saved draft<select value={draftPath} disabled={busy} onChange={event => setDraftPath(event.target.value)}>
        <option value="">Choose a draft…</option>{project.drafts?.map(file => <option key={file}>{file}</option>)}
      </select></label>
      <button disabled={busy || !draftPath} onClick={() => void load('draft/open', { path: draftPath })}>Open draft</button>
      {draftSaved && <p>{draftSaved}</p>}
    </section>
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
