import type { Project } from './types';

export type ProjectTransport = (url: string, init?: RequestInit) => Promise<Response>;
type Field = { value: unknown; original: unknown };
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const replacements = new Set(['open', 'import', 'draft/open', 'undo', 'redo', 'yaml']);
const protectedCommands = new Set([...replacements, 'save', 'draft/save', 'export']);

export type DraftState = {
  project: Project; editorYaml: string; view: 'visual' | 'yaml'; diagnostics: string[];
  busy: boolean; dirty: boolean; saved: string; draftSaved: string; path: string;
  draftPath: string; overwrite: boolean; draftOverwrite: boolean; resetEpoch: number;
};

/** Own accepted drafts, pending forms and transport ordering behind one seam. */
export class PlantDraft {
  private state: DraftState = { project: { project: '', model: null }, editorYaml: '', view: 'visual',
    diagnostics: [], busy: false, dirty: false, saved: '', draftSaved: '', path: '', draftPath: '',
    overwrite: false, draftOverwrite: false, resetEpoch: 0 };
  private forms = new Map<string, Map<string, Field>>();
  private listeners = new Set<() => void>();
  private revision = 0;
  private queue: Promise<unknown> = Promise.resolve();
  private queued = 0;
  constructor(private transport: ProjectTransport) {}
  snapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private publish(changes: Partial<DraftState> = {}) {
    const dirty = [...this.forms.values()].some(fields => [...fields.values()].some(f => !equal(f.value, f.original)));
    this.state = { ...this.state, ...changes, dirty };
    this.listeners.forEach(listener => listener());
  }
  set<K extends keyof DraftState>(key: K, value: DraftState[K]) {
    this.revision += 1;
    this.publish({ [key]: value });
  }
  field<T>(id: string, name: string, initial: T): T {
    let fields = this.forms.get(id);
    if (!fields) { fields = new Map(); this.forms.set(id, fields); }
    const existing = fields.get(name);
    if (!existing || equal(existing.value, existing.original)) {
      fields.set(name, { value: structuredClone(initial), original: structuredClone(initial) });
    }
    return fields.get(name)!.value as T;
  }
  editField<T>(id: string, name: string, initial: T, update: T | ((previous: T) => T)) {
    const previous = this.field(id, name, initial);
    this.forms.get(id)!.get(name)!.value = typeof update === 'function' ? (update as (previous: T) => T)(previous) : update;
    this.revision += 1;
    this.publish({ saved: '', draftSaved: '' });
  }
  isDirty(id: string) { return [...(this.forms.get(id)?.values() ?? [])].some(f => !equal(f.value, f.original)); }
  discard(id?: string) {
    if (id) this.forms.delete(id); else this.forms.clear();
    this.revision += 1;
    this.publish();
  }
  async apply(id: string, operation: () => Promise<boolean>) {
    const accepted = await operation();
    if (accepted) this.discard(id);
    return accepted;
  }
  private enqueue<T>(operation: () => Promise<T>): Promise<T> {
    this.revision += 1;
    this.queued += 1;
    this.publish({ busy: true });
    const result = this.queue.then(operation);
    this.queue = result.catch(() => undefined);
    return result.finally(() => { this.queued -= 1; this.publish({ busy: this.queued > 0 }); });
  }
  private accept(result: Project, endpoint: string) {
    if (replacements.has(endpoint)) this.forms.clear();
    this.publish({ project: { ...this.state.project, ...result }, editorYaml: result.model?.yaml ?? '',
      diagnostics: result.diagnostics ?? [],
      saved: result.saved_path ? `Saved: ${result.saved_path}` : endpoint === 'save' ? this.state.saved : '',
      draftSaved: result.saved_draft ? `Draft saved: ${result.saved_draft}` : '',
      ...(result.saved_path ? { path: result.saved_path, overwrite: false } : {}),
      ...(result.saved_draft ? { draftPath: result.saved_draft, draftOverwrite: false } : {}),
      ...(['open', 'import', 'draft/open'].includes(endpoint) ? { resetEpoch: this.state.resetEpoch + 1 } : {}),
      ...(result.model && !result.model.graph_available && ['open', 'import', 'draft/open', 'reload'].includes(endpoint) ? { view: 'yaml' as const } : {}),
    });
  }
  async initialize() {
    const revision = this.revision;
    try {
      const response = await this.transport('/api/project');
      if (!response.ok) throw new Error(`Project request failed (${response.status})`);
      const result: Project = await response.json();
      if (revision !== this.revision) return;
      this.accept(result, 'reload');
      this.publish({ path: result.models?.[0] ?? '', draftPath: result.drafts?.[0] ?? '' });
    } catch (error) { if (revision === this.revision) this.publish({ diagnostics: [error instanceof Error ? error.message : 'Could not read the project.'] }); }
  }
  private blocked(endpoint: string) {
    if (!this.state.dirty || !protectedCommands.has(endpoint)) return false;
    this.publish({ diagnostics: ['Apply or discard open form changes before replacing or saving the draft.'] });
    return true;
  }
  private async post(endpoint: string, body: object): Promise<boolean> {
    if (this.blocked(endpoint)) return false;
    try {
      const response = await this.transport(`/api/project/${endpoint}`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const result: Project = await response.json();
      if (result.accepted) { this.accept(result, endpoint); return true; }
      this.publish({ diagnostics: result.diagnostics ?? [`Request failed (${response.status}). Check the YAML and retry.`] });
    } catch (error) { this.publish({ diagnostics: [error instanceof Error ? error.message : 'Could not reach the local service.'] }); }
    return false;
  }
  private async flushYaml() {
    const model = this.state.project.model;
    return !model || this.state.editorYaml === model.yaml || this.post('yaml', { yaml: this.state.editorYaml, expected_yaml: model.yaml });
  }
  request = (endpoint: string, body: object) => this.enqueue(() => this.post(endpoint, body));
  load = (endpoint: string, body: object) => this.enqueue(async () => {
    if (this.blocked(endpoint)) return false;
    if (['save', 'draft/save', 'undo'].includes(endpoint) && !await this.flushYaml()) return false;
    return this.post(endpoint, body);
  });
  submitYaml = () => this.enqueue(() => this.flushYaml());
  switchView = (view: 'visual' | 'yaml') => this.enqueue(async () => {
    if (this.state.dirty) return;
    if (view === 'visual' && !await this.flushYaml()) return;
    this.publish({ view });
  });
  reload = () => this.enqueue(async () => {
    if (this.state.dirty) return;
    try {
      const response = await this.transport('/api/project');
      if (!response.ok) throw new Error('Could not reload the current draft.');
      this.forms.clear();
      this.accept(await response.json(), 'reload');
    } catch (error) { this.publish({ diagnostics: [error instanceof Error ? error.message : 'Could not reload the current draft.'] }); }
  });
  exportBlob = () => this.enqueue(async () => {
    if (this.blocked('export') || !await this.flushYaml()) return null;
    try {
      const response = await this.transport('/api/project/export');
      if (response.ok) return response.blob();
      const result: Project = await response.json();
      this.publish({ diagnostics: result.diagnostics ?? ['Could not export YAML.'] });
    } catch { this.publish({ diagnostics: ['Could not reach the local service to export YAML.'] }); }
    return null;
  });
}
