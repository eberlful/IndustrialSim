import { expect, test } from '@playwright/test';
import { PlantDraft } from '../src/plantDraft';
import type { Model, Project } from '../src/types';

const model: Model = { name: 'Plant', yaml: 'seed: 42', configuration: {}, graph: { nodes: [], routes: [] },
  layout: { positions: {}, grouping: 'none' }, plant: null, valid: true, graph_available: true, diagnostics: [] };
const project = (yaml = model.yaml): Project => ({ project: '/test', accepted: true, model: { ...model, yaml } });
const response = (body: Project) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

test('forms retain exact values independently and block draft replacement until discarded', async () => {
  const calls: string[] = [];
  const draft = new PlantDraft(async url => { calls.push(url); return response(project()); });
  await draft.initialize();
  draft.editField('node:buffer:parameters', 'capacity', '1', '9007199254740993');
  draft.editField('machine:machine:properties', 'capacity', '1', '2');
  // Remounting with a new server baseline cannot replace an open input.
  expect(draft.field('node:buffer:parameters', 'capacity', '4')).toBe('9007199254740993');
  for (const action of ['open', 'import', 'draft/open', 'undo', 'redo', 'save', 'draft/save']) {
    expect(await draft.load(action, {})).toBe(false);
  }
  await draft.reload();
  expect(calls).toEqual(['/api/project']);
  await draft.apply('node:buffer:parameters', () => draft.request('edit', {}));
  expect(draft.snapshot().dirty).toBe(true);
  expect(draft.field('machine:machine:properties', 'capacity', '1')).toBe('2');
  draft.discard('machine:machine:properties');
  expect(draft.field('machine:machine:properties', 'capacity', '1')).toBe('1');
  expect(draft.snapshot().dirty).toBe(false);
  expect(await draft.load('open', {})).toBe(true);
});

test('rejection keeps inputs while an accepted invalid draft resets only the submitted form', async () => {
  let accepted = false;
  const draft = new PlantDraft(async () => response({ ...project(), accepted,
    model: { ...model, valid: false }, diagnostics: ['invalid capacity'] }));
  draft.editField('buffer', 'capacity', '1', 'bad');
  draft.editField('machine', 'capacity', '1', '2');
  expect(await draft.apply('buffer', () => draft.request('edit', {}))).toBe(false);
  expect(draft.field('buffer', 'capacity', '1')).toBe('bad');
  accepted = true;
  expect(await draft.apply('buffer', () => draft.request('edit', {}))).toBe(true);
  expect(draft.isDirty('buffer')).toBe(false);
  expect(draft.isDirty('machine')).toBe(true);
  expect(draft.snapshot().project.model?.valid).toBe(false);
  expect(draft.snapshot().diagnostics).toEqual(['invalid capacity']);
});

test('a delayed initial read cannot replace a later accepted draft', async () => {
  const initial = deferred<Response>();
  const draft = new PlantDraft(url => url === '/api/project' ? initial.promise : Promise.resolve(response(project('seed: 7'))));
  const reading = draft.initialize();
  await draft.request('import', {});
  initial.resolve(response(project('seed: 42')));
  await reading;
  expect(draft.snapshot().editorYaml).toBe('seed: 7');
});

test('mutations serialize and YAML is validated before the same save operation', async () => {
  const first = deferred<Response>();
  const calls: string[] = [];
  const draft = new PlantDraft(url => {
    calls.push(url);
    return url.endsWith('/edit') ? first.promise : Promise.resolve(response(project('seed: 7')));
  });
  await draft.initialize();
  const editing = draft.request('edit', {});
  const importing = draft.request('import', {});
  await Promise.resolve();
  expect(calls).toEqual(['/api/project', '/api/project/edit']);
  expect(draft.snapshot().busy).toBe(true);
  first.resolve(response(project()));
  await Promise.all([editing, importing]);
  draft.set('editorYaml', 'seed: 8');
  await draft.load('save', {});
  expect(calls.slice(-2)).toEqual(['/api/project/yaml', '/api/project/save']);
  expect(draft.snapshot().busy).toBe(false);
});
