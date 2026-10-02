import { useState } from 'react';
import { integerOrText, type ParameterEdit } from './parameterEditing';
import type { Model, Operation, Resource } from './types';

type EditorProps = { model: Model; busy: boolean; edit: (command: ParameterEdit) => Promise<void> };

export function resourceDefinitions(model: Model, kind: 'machine' | 'worker'): Resource[] {
  return (model.configuration[kind === 'machine' ? 'machines' : 'workers'] as Resource[] | undefined) ?? [];
}

export function ResourceProperties({ resource, kind, model, busy, edit }: EditorProps & { resource: Resource; kind: 'machine' | 'worker' }) {
  const [name, setName] = useState(resource.name ?? '');
  const [capacity, setCapacity] = useState(String(resource.capacity ?? 1));
  const [workerKind, setWorkerKind] = useState(resource.kind ?? 'individual');
  const [qualifications, setQualifications] = useState(resource.qualifications?.join('\n') ?? '');
  const collection = kind === 'machine' ? 'machines' : 'workers';
  const prefix = `${collection}.${resourceDefinitions(model, kind).findIndex(item => item.id === resource.id)}`;
  const errors = model.diagnostics.filter(error => error.includes(resource.id) || error.startsWith(prefix + '.') || error.startsWith(prefix + ':'));
  return <>
    <h3>{resource.id}</h3>
    {!!errors.length && <ul className="field-errors" aria-label="Selected resource diagnostics">{errors.map((error, index) => <li key={index}>{error}</li>)}</ul>}
    <form className="property-form" onSubmit={event => {
      event.preventDefault();
      const changes: Record<string, unknown> = {};
      if (name !== (resource.name ?? '')) changes.name = name || null;
      if (capacity !== String(resource.capacity ?? 1)) changes.capacity = integerOrText(capacity);
      if (kind === 'worker') {
        if (workerKind !== (resource.kind ?? 'individual')) changes.kind = workerKind;
        if (qualifications !== (resource.qualifications?.join('\n') ?? '')) changes.qualifications = qualifications.split('\n').filter(Boolean);
      }
      void edit({ kind, element_id: resource.id, changes });
    }}>
      <label>Resource name<input value={name} disabled={busy} onChange={event => setName(event.target.value)}/></label>
      <label>Resource capacity<input value={capacity} disabled={busy} onChange={event => setCapacity(event.target.value)}/></label>
      {kind === 'worker' && <>
        <label>Worker kind<select value={workerKind} disabled={busy} onChange={event => setWorkerKind(event.target.value as 'individual' | 'pool')}><option value="individual">Individual</option><option value="pool">Pool</option></select></label>
        <label>Worker qualifications<textarea value={qualifications} disabled={busy} onChange={event => setQualifications(event.target.value)}/><small>One qualification per line; commas are part of the name.</small></label>
        <p className="hint">Individuals have capacity 1. Pools may have a larger capacity.</p>
      </>}
      <button disabled={busy}>Apply resource</button>
    </form>
    <details><summary>All resource properties</summary><pre>{JSON.stringify(resource, null, 2)}</pre></details>
  </>;
}

export function OperationResources({ operation, nodeId, model, busy, edit }: EditorProps & { operation: Operation; nodeId: string }) {
  const [machines, setMachines] = useState(operation.required_machines ?? []);
  const [workers, setWorkers] = useState((operation.required_workers ?? []).map(requirement => ({
    worker_id: requirement.worker_id ?? '', qualification: requirement.qualification ?? '', count: String(requirement.count ?? 1),
  })));
  const machineDefinitions = resourceDefinitions(model, 'machine');
  const workerDefinitions = resourceDefinitions(model, 'worker');
  const qualifications = [...new Set(workerDefinitions.flatMap(worker => worker.qualifications ?? []))];
  const qualificationListId = `qualifications:${nodeId}:${operation.id}`;
  return <form className="property-form" aria-label={`Resource requirements · ${operation.id}`} onSubmit={event => {
    event.preventDefault();
    const requirements = workers.map(requirement => ({
      worker_id: requirement.worker_id || null, qualification: requirement.qualification || null, count: integerOrText(requirement.count),
    }));
    const changes: Record<string, unknown> = {};
    if (JSON.stringify(machines) !== JSON.stringify(operation.required_machines ?? [])) changes.required_machines = machines;
    const original = (operation.required_workers ?? []).map(requirement => ({ worker_id: requirement.worker_id ?? null, qualification: requirement.qualification ?? null, count: requirement.count ?? 1 }));
    if (JSON.stringify(requirements) !== JSON.stringify(original)) changes.required_workers = requirements;
    void edit({ kind: 'node', element_id: nodeId, operation_id: operation.id, changes });
  }}>
    <h4>Resource requirements · {operation.id}</h4>
    <label>Required Machines<select multiple value={machines} disabled={busy} onChange={event => setMachines(Array.from(event.target.selectedOptions, option => option.value))}>
      {machines.filter(id => !machineDefinitions.some(machine => machine.id === id)).map(id => <option key={id} value={id}>{id} (unknown)</option>)}
      {machineDefinitions.map(machine => <option key={machine.id} value={machine.id}>{machine.name ?? machine.id} ({machine.id})</option>)}
    </select><small>Use Ctrl or Command to select multiple Machines or clear a selection.</small></label>
    <datalist id={qualificationListId}>{qualifications.map(qualification => <option key={qualification} value={qualification}/>)}</datalist>
    {workers.map((requirement, index) => <fieldset key={index} disabled={busy}>
      <legend>Worker requirement {index + 1}</legend>
      <label>Assigned Worker<select value={requirement.worker_id} onChange={event => setWorkers(previous => previous.map((item, position) => position === index ? { ...item, worker_id: event.target.value } : item))}>
        <option value="">Any Worker with qualification</option>
        {requirement.worker_id && !workerDefinitions.some(worker => worker.id === requirement.worker_id) && <option value={requirement.worker_id}>{requirement.worker_id} (unknown)</option>}
        {workerDefinitions.map(worker => <option key={worker.id} value={worker.id}>{worker.name ?? worker.id} ({worker.id})</option>)}
      </select></label>
      <label>Required qualification<input list={qualificationListId} value={requirement.qualification} onChange={event => setWorkers(previous => previous.map((item, position) => position === index ? { ...item, qualification: event.target.value } : item))}/></label>
      <label>Worker count<input value={requirement.count} onChange={event => setWorkers(previous => previous.map((item, position) => position === index ? { ...item, count: event.target.value } : item))}/></label>
      <button type="button" onClick={() => setWorkers(previous => previous.filter((_, position) => position !== index))}>Remove Worker requirement {index + 1}</button>
    </fieldset>)}
    <p className="hint">Each requirement needs an assigned Worker, a qualification, or both.</p>
    <button type="button" disabled={busy} onClick={() => setWorkers(previous => [...previous, { worker_id: '', qualification: '', count: '1' }])}>Add Worker requirement</button>
    <button disabled={busy}>Apply requirements</button>
  </form>;
}
