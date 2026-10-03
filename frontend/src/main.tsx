import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Graph, arrangedPositions } from './Graph';
import { GraphTools, PortEditor, RouteConnections } from './GraphEditing';
import { EpisodeControl } from './EpisodeControl';
import { EpisodeEvents, EpisodeInspection, EpisodeMetrics } from './EpisodeObservation';
import { EpisodeSetup, ProductionPlan } from './EpisodeInputs';
import { Properties } from './Properties';
import { ResourceProperties, resourceDefinitions } from './Resources';
import type { ParameterEdit } from './parameterEditing';
import type { FlowNode, Model, Project, Route, Episode, LiveSelection } from './types';
import './style.css';

function App() {
  const projectRevision = useRef(0);
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [observeEpisode, setObserveEpisode] = useState(false);
  const [liveSelection, setLiveSelection] = useState<LiveSelection | null>(null);
  useEffect(() => {
    setLiveSelection(null);
    if (episode && ['running', 'pausing', 'paused', 'seeking_batch', 'awaiting_decisions', 'resolving'].includes(episode.state)) setObserveEpisode(true);
  }, [episode?.id]);
  const [project, setProject] = useState<Project>({ project: '', model: null });
  const [path, setPath] = useState('');
  const [yaml, setYaml] = useState('');
  const [name, setName] = useState('Imported YAML');
  const [view, setView] = useState<'visual' | 'yaml'>('visual');
  const [editorYaml, setEditorYaml] = useState('');
  const [formDirty, setFormDirty] = useState(false);
  const [inputsRevision, setInputsRevision] = useState(0);
  const [setupDirty, setSetupDirty] = useState(false);
  const [planDirty, setPlanDirty] = useState(false);
  const inputsDirty = formDirty || setupDirty || planDirty;
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
    const revision = projectRevision.current;
    fetch('/api/project').then(async (response) => {
      if (!response.ok) throw new Error(`Project request failed (${response.status})`);
      return response.json() as Promise<Project>;
    }).then((result) => { if (revision !== projectRevision.current) return; setProject(result); setPath(result.models?.[0] ?? ''); setDraftPath(result.drafts?.[0] ?? ''); setDiagnostics(result.diagnostics ?? []); setEditorYaml(result.model?.yaml ?? ''); if (result.model && !result.model.graph_available) setView('yaml'); })
      .catch((error: Error) => { if (revision === projectRevision.current) setDiagnostics([error.message]); });
  }, []);
  async function request(endpoint: string, body: object): Promise<boolean> {
    projectRevision.current += 1;
    setBusy(true);
    try {
      const response = await fetch(`/api/project/${endpoint}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const result: Project = await response.json();
      if (result.accepted) {
        setProject((previous) => ({ ...previous, ...result }));
        setEditorYaml(result.model?.yaml ?? '');
        if (result.model?.yaml !== model?.yaml || ['episode', 'edit', 'structure', 'open', 'import', 'draft/open', 'undo', 'redo'].includes(endpoint)) setFormDirty(false);
        if (['open', 'import', 'draft/open', 'undo', 'redo', 'yaml'].includes(endpoint)) { setSetupDirty(false); setPlanDirty(false); setInputsRevision(previous => previous + 1); }
        if (endpoint === 'draft/open' && result.model && !result.model.graph_available) setView('yaml');
        if (endpoint === 'open' || endpoint === 'import' || endpoint === 'draft/open') setSelection(null);
        if (endpoint !== 'save') setSaved('');
        setDiagnostics(result.diagnostics ?? []);
        if (result.saved_draft) { setDraftSaved(`Draft saved: ${result.saved_draft}`); setDraftPath(result.saved_draft); setDraftOverwrite(false); }
        else setDraftSaved('');
        if (result.saved_path) { setSaved(`Saved: ${result.saved_path}`); setPath(result.saved_path); setOverwrite(false); }
        return true;
      } else {
        setDiagnostics(result.diagnostics ?? [`Request failed (${response.status}). Check the YAML and retry.`]);
        return false;
      }
    } catch (error) {
      setDiagnostics([error instanceof Error ? error.message : 'Could not reach the local service.']);
      return false;
    } finally { setBusy(false); }
  }
  const model: Model | null = project.model;
  const live = observeEpisode ? episode?.observation : null;
  const graphModel = useMemo(() => model && live ? { ...model, graph: live.graph, plant: live.plant } : model, [model, live?.graph, live?.plant]);
  const yamlDirty = !!model && editorYaml !== model.yaml;
  async function submitYaml(): Promise<boolean> {
    if (!yamlDirty || !model) return true;
    return request('yaml', { yaml: editorYaml, expected_yaml: model.yaml });
  }
  async function load(endpoint: string, body: object): Promise<void> {
    if (['save', 'draft/save', 'undo'].includes(endpoint) && !await submitYaml()) return;
    await request(endpoint, body);
  }
  async function switchView(next: 'visual' | 'yaml') {
    if (next === 'yaml' && inputsDirty) return;
    if (next === 'visual' && !await submitYaml()) return;
    setView(next);
  }
  async function reloadYaml() {
    setBusy(true);
    try {
      const response = await fetch('/api/project');
      if (!response.ok) throw new Error('Could not reload the current draft.');
      const result: Project = await response.json();
      setProject(result); setEditorYaml(result.model?.yaml ?? ''); setDiagnostics(result.diagnostics ?? []);
    } catch (error) { setDiagnostics([error instanceof Error ? error.message : 'Could not reload the current draft.']); }
    finally { setBusy(false); }
  }
  const selectedElement = selection?.kind === 'node'
    ? model?.graph.nodes.find(node => node.id === selection.id)
    : selection?.kind === 'route' ? model?.graph.routes.find(route => route.id === selection.id) : undefined;
  const selectedResource = model && (selection?.kind === 'machine' || selection?.kind === 'worker')
    ? resourceDefinitions(model, selection.kind).find(resource => resource.id === selection.id) : undefined;
  async function download() {
    if (!await submitYaml()) return;
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
      <div className="status" role="status">{busy ? '◷ Validating…' : yamlDirty ? '○ YAML needs validation' : model ? model.valid ? '✓ Model valid' : '⚠ Draft invalid' : '○ No model loaded'}</div></header>
    <section className="toolbar" aria-label="Project controls">
      <label>Project model <select value={path} onChange={(event) => setPath(event.target.value)} disabled={busy}>
        {!project.models?.length && <option value="">No project YAML files</option>}
        {project.models?.map((file) => <option key={file}>{file}</option>)}
      </select></label>
      <button disabled={busy || yamlDirty || !path} onClick={() => void load('open', { path })}>Open model</button>
      {model?.graph_available && <><label>Display grouping<select aria-label="Display grouping" value={model.layout.grouping} disabled={busy || view === 'yaml'}
        onChange={event => { const grouping = event.target.value as 'none' | 'area' | 'hall'; void load('layout', { grouping, positions: arrangedPositions(model, grouping) }); }}>
        <option value="none">None</option><option value="area">Area</option><option value="hall">Hall</option>
      </select></label><button disabled={busy || view === 'yaml'} onClick={() => void load('layout/save', {})}>Save layout</button></>}
      {model && <><button disabled={busy} aria-pressed={view === 'visual'} onClick={() => void switchView('visual')}>Visual editor</button><button disabled={busy || inputsDirty} aria-pressed={view === 'yaml'} onClick={() => void switchView('yaml')}>YAML editor</button></>}
      {inputsDirty && <span role="note">Apply form changes before switching to YAML or saving.</span>}
      <span>{model ? `Loaded: ${model.name}` : 'Open a project model or import YAML below'}</span>
      <button disabled={busy || (!project.can_undo && !yamlDirty)} onClick={() => void load('undo', {})}>Undo</button>
      <button disabled={busy || yamlDirty || !project.can_redo} onClick={() => void load('redo', {})}>Redo</button>
      <button disabled={busy || inputsDirty || (!model?.valid && !yamlDirty)} onClick={() => void download()}>Download YAML</button>
    </section>
    <EpisodeControl episode={episode} onChange={setEpisode} canStart={!!model?.valid && !inputsDirty && !yamlDirty && !busy}/>
    {diagnostics.length > 0 && <section role="alert" className="diagnostics"><strong>{model && !model.valid ? '⚠ Draft needs correction' : '⚠ Action was not accepted'}</strong><ul>{diagnostics.map((message, index) => <li key={index}>{message}</li>)}</ul><p>{model && !model.valid ? 'Correct the indicated properties or undo the change. Save incomplete work as a draft. Executable YAML requires all errors to be corrected.' : model ? `Still displaying ${model.name}. Correct the input and retry.` : 'Correct the YAML and retry.'}</p></section>}
    {model && view === 'yaml' && <section className="import-panel yaml-editor" aria-label="Advanced YAML editor">
      <h2>Advanced YAML editor</h2>
      <p>Edit the complete simulation configuration. Switching to visual editing or saving submits and validates this text. Invalid text can be saved as an incomplete draft.</p>
      <label>Advanced YAML content<textarea spellCheck={false} value={editorYaml} disabled={busy} onChange={event => { setEditorYaml(event.target.value); setSaved(''); setDraftSaved(''); }}/></label>
      <button disabled={busy || !yamlDirty} onClick={() => void submitYaml()}>Apply YAML</button>
      <button disabled={busy} onClick={() => void reloadYaml()}>Reload current YAML</button>
      {yamlDirty && <p role="note">YAML changes await validation.</p>}
    </section>}
    {model && view === 'visual' && !live && !model.graph_available && <section className="import-panel" aria-label="Unavailable visual editor"><h2>Visual editing unavailable</h2><p>The current YAML draft has validation errors. Its text is retained. Use the YAML editor to correct it or undo the edit.</p></section>}
    {view === 'visual' && (live || !model || model.graph_available) && <div className="workspace" onChangeCapture={event => {
      if (event.target instanceof HTMLElement && event.target.closest('form')?.getAttribute('aria-label') !== 'Episode setup' && event.target.closest('form')) setFormDirty(true);
    }} onClickCapture={event => {
      if (!(event.target instanceof HTMLElement)) return;
      const button = event.target.closest('button');
      if (button?.type === 'button' && button.closest('form')) setFormDirty(true);
    }}>
      <section className="graph-panel" aria-label="Material Flow Graph">
        {episode && <div><button aria-pressed={observeEpisode} onClick={() => setObserveEpisode(true)}>Episode graph</button><button aria-pressed={!observeEpisode} onClick={() => setObserveEpisode(false)}>Draft graph</button></div>}
        <div className="panel-title"><h2>Material Flow Graph</h2><span>{graphModel ? `${graphModel.graph.nodes.length} nodes · ${graphModel.graph.routes.length} routes` : 'No topology yet'}</span></div>
        <div className="graph-canvas">{graphModel ? <Graph key={live ? episode?.id : model?.name} model={graphModel} observation={live} busy={busy || !!live} onMove={positions => void load('layout', { positions })} onSelect={element => { if (live && 'kind' in element && (element.kind === 'station' || element.kind === 'buffer')) setLiveSelection({ kind: element.kind === 'station' ? 'stations' : 'buffers', id: element.id }); else if (!live) setSelection({ kind: 'kind' in element ? 'node' : 'route', id: element.id }); }}/> : <div className="empty"><strong>Inspect your Plant</strong><p>Load YAML to see sources, Stations, Buffers, sinks and their typed Ports.</p></div>}</div>
        <p className="hint">Select a node or route to inspect properties. Drag nodes to improve readability; save layout to restore positions and display grouping. Grouping uses existing assignments.</p>
      </section>
      <aside>
        {episode && live && <><EpisodeInspection episode={episode} selection={liveSelection} onSelect={setLiveSelection}/><EpisodeMetrics episode={episode}/><EpisodeEvents key={episode.id} episodeId={episode.id}/></>}

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
        <section className="panel" aria-label="Episode controls"><h2>Episode setup</h2>{model?.episode_inputs && <EpisodeSetup key={JSON.stringify([inputsRevision, model.episode_inputs.seed, model.episode_inputs.episode])} model={model} busy={busy} onDirty={() => setSetupDirty(true)} edit={async changes => { if (await request('episode', { changes })) setSetupDirty(false); }}/>}</section>
        <section className="panel"><h2>Plant organization</h2><p className="hint">Area and Hall locations are separate from material flow.</p>{model?.plant ? <><h3>{model.plant.name}</h3>{model.plant.areas.map((area) => <details key={area.id}><summary>{area.name}</summary><ul>{area.halls.map((hall) => <li key={hall.id}>{hall.name} <small>({hall.id})</small></li>)}</ul></details>)}</> : <p>No Plant hierarchy declared.</p>}</section>
      </aside>
    </div>}
    {model?.episode_inputs && view === 'visual' && <ProductionPlan key={JSON.stringify([inputsRevision, model.episode_inputs.production_plan])} model={model} busy={busy} onDirty={() => setPlanDirty(true)} edit={async changes => { if (await request('episode', { changes })) setPlanDirty(false); }}/>}
    {model && <section className="import-panel save-panel" aria-label="Save model">
      <h2>Save validated YAML</h2><p>Save explicitly to a project-local file. Existing files require overwrite to be enabled.</p>
      <label>Save as project path<input value={savePath} disabled={busy} onChange={event => { setSavePath(event.target.value); setOverwrite(false); setSaved(''); }}/></label>
      <label><input type="checkbox" checked={overwrite} disabled={busy} onChange={event => setOverwrite(event.target.checked)}/>Overwrite existing file at this path</label>
      <button disabled={busy || inputsDirty || (!model.valid && !yamlDirty) || !savePath.trim()} onClick={() => void load('save', { path: savePath, overwrite })}>Save YAML</button>
      {saved && <p>{saved}</p>}
    </section>}
    <section className="import-panel save-panel" aria-label="Project drafts">
      <h2>Incomplete drafts</h2><p>Save unfinished work separately, including validation errors and presentation.</p>
      <label>Draft filename<input value={draftName} disabled={busy} onChange={event => { setDraftName(event.target.value); setDraftOverwrite(false); setDraftSaved(''); }}/></label>
      <label><input type="checkbox" checked={draftOverwrite} disabled={busy} onChange={event => setDraftOverwrite(event.target.checked)}/>Overwrite existing draft</label>
      <button disabled={busy || inputsDirty || !model || !draftName.trim()} onClick={() => void load('draft/save', { path: draftName, overwrite: draftOverwrite })}>Save draft</button>
      <label>Saved draft<select value={draftPath} disabled={busy} onChange={event => setDraftPath(event.target.value)}>
        <option value="">Choose a draft…</option>{project.drafts?.map(file => <option key={file}>{file}</option>)}
      </select></label>
      <button disabled={busy || yamlDirty || !draftPath} onClick={() => void load('draft/open', { path: draftPath })}>Open draft</button>
      {draftSaved && <p>{draftSaved}</p>}
    </section>
    <details className="import-panel" open><summary>Import simulation YAML</summary>
      <p>Imports are validated in memory. Original files are preserved.</p>
      <label>YAML file <input type="file" accept=".yaml,.yml,text/yaml" disabled={busy || yamlDirty} onChange={async (event) => {
        const file = event.target.files?.[0];
        if (file) { try { setYaml(await file.text()); setName(file.name); } catch { setDiagnostics(['Could not read the selected YAML file.']); } }
      }}/></label>
      <label>YAML content <textarea spellCheck={false} value={yaml} disabled={busy || yamlDirty} onChange={(event) => { setYaml(event.target.value); setName('Imported YAML'); }}/></label>
      <button disabled={busy || yamlDirty || !yaml.trim()} onClick={() => void load('import', { yaml, name })}>Validate and import</button>
    </details>
    {model && <details className="import-panel"><summary>Complete project draft</summary><p>Includes sections outside the graph. Edits and export use this project draft.</p><pre>{model.graph_available ? JSON.stringify(model.configuration, null, 2) : model.yaml}</pre></details>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
