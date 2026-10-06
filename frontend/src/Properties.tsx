import { useDraftField, useDraftForm, DiscardForm } from './PlantDraftContext';
import type { FlowNode, Model, Operation, Route } from './types';
import { integerOrText, type ParameterEdit } from './parameterEditing';
import { OperationResources } from './Resources';

export function Properties({ element, kind, model, busy, edit }: {
  element: FlowNode | Route; kind: 'node' | 'route'; model: Model; busy: boolean;
  edit: (command: ParameterEdit) => Promise<boolean>;
}) {
  const formId = `${kind}:${element.id}:parameters`;
  const form = useDraftForm(formId);
  const [hall, setHall] = useDraftField(formId, 'hall', String(element.hall_id ?? ''));
  const [capacity, setCapacity] = useDraftField(formId, 'capacity', String(element.capacity ?? ''));
  const [outputCapacity, setOutputCapacity] = useDraftField(formId, 'outputCapacity', String(element.output_capacity ?? 0));
  const [transit, setTransit] = useDraftField(formId, 'transit', String(element.transit_time ?? 0));
  const [capabilities, setCapabilities] = useDraftField(formId, 'capabilities', (element.required_capabilities as string[] | undefined)?.join('\n') ?? '');
  const [pool, setPool] = useDraftField(formId, 'pool', String(element.pool_id ?? ''));
  const operations = (element.operations as Operation[] | undefined) ?? [];
  const index = kind === 'node' ? model.graph.nodes.findIndex(node => node.id === element.id) : model.graph.routes.findIndex(route => route.id === element.id);
  const prefix = model.configuration.material_flow ? `material_flow.${kind === 'node' ? 'nodes' : 'routes'}.${index}` : `stations.${index}`;
  const errors = model.diagnostics.filter(error => error.includes(element.id) || operations.some(operation => error.includes(`Operation '${operation.id}'`)) || error.startsWith(prefix + '.') || error.startsWith(prefix + ':'));
  async function apply() {
    const changes: Record<string, unknown> = {};
    if (kind === 'route') {
      if (transit !== String(element.transit_time ?? 0)) changes.transit_time = integerOrText(transit);
      if (capacity !== String(element.capacity ?? '')) changes.capacity = integerOrText(capacity);
      const originalCapabilities = (element.required_capabilities as string[] | undefined)?.join('\n') ?? '';
      if (capabilities !== originalCapabilities) changes.required_capabilities = capabilities.split('\n').filter(Boolean);
      if (pool !== String(element.pool_id ?? '')) changes.pool_id = pool || null;
    } else {
      if (model.configuration.material_flow && hall !== String(element.hall_id ?? '')) changes.hall_id = hall || null;
      if (element.kind === 'buffer' && capacity !== String(element.capacity ?? '')) changes.capacity = integerOrText(capacity);
      if (element.kind === 'station' && outputCapacity !== String(element.output_capacity ?? 0)) changes.output_capacity = integerOrText(outputCapacity);
    }
    await form.apply(() => edit({ kind, element_id: element.id, changes }));
  }
  const halls = model.plant?.areas.flatMap(area => area.halls) ?? [];
  return <>
    <h3>{element.id}</h3>
    {errors.length > 0 && <ul className="field-errors" aria-label="Selected element diagnostics">{errors.map((error, index) => <li key={index}>{error}</li>)}</ul>}
    <form className="property-form" onSubmit={event => { event.preventDefault(); void apply(); }}>
      {kind === 'node' && model.configuration.material_flow != null && <label>Hall assignment
        <select value={hall} disabled={busy} onChange={event => setHall(event.target.value)}>
          <option value="">Unassigned</option>
          {hall && !halls.some(item => item.id === hall) && <option value={hall}>{hall}</option>}
          {halls.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>}
      {kind === 'node' && element.kind === 'buffer' && <label>Buffer capacity<input value={capacity} disabled={busy} onChange={event => setCapacity(event.target.value)}/></label>}
      {kind === 'node' && element.kind === 'station' && <label>Station output capacity<input value={outputCapacity} disabled={busy} onChange={event => setOutputCapacity(event.target.value)}/></label>}
      {kind === 'route' && <>
        <label>Transit time<input value={transit} disabled={busy} onChange={event => setTransit(event.target.value)}/></label>
        <label>Route capacity<input value={capacity} disabled={busy} placeholder="Unlimited" onChange={event => setCapacity(event.target.value)}/></label>
        <label>Required capabilities<textarea value={capabilities} disabled={busy} placeholder="One capability per line" onChange={event => setCapabilities(event.target.value)}/><small>One capability per line; commas are part of the name.</small></label>
        <label>Vehicle pool<input value={pool} disabled={busy} placeholder="No pool requirement" onChange={event => setPool(event.target.value)}/></label>
      </>}
      <button disabled={busy}>Apply parameters</button><DiscardForm id={formId}/>
    </form>
    {operations.map(op => <OperationDuration key={op.id} operation={op} kind={kind} elementId={element.id} busy={busy} edit={edit}/>)}
    {operations.map(op => <OperationResources key={op.id} operation={op} nodeId={element.id} model={model} busy={busy} edit={edit}/>)}
    <p className="hint">Durations accept units such as 10s or 2m. Bare integers are nanoseconds.</p>
    <details><summary>All element properties</summary><pre>{JSON.stringify(element, null, 2)}</pre></details>
  </>;
}

function OperationDuration({ operation, kind, elementId, busy, edit }: {
  operation: Operation; kind: 'node' | 'route'; elementId: string; busy: boolean;
  edit: (command: ParameterEdit) => Promise<boolean>;
}) {
  const formId = `${kind}:${elementId}:duration:${operation.id}`;
  const form = useDraftForm(formId);
  const [duration, setDuration] = useDraftField(formId, 'duration', String(operation.duration));
  return <form className="property-form" onSubmit={event => {
    event.preventDefault(); void form.apply(() => edit({ kind, element_id: elementId,
      operation_id: operation.id, changes: { duration: integerOrText(duration) } }));
  }}><label>Duration · {operation.id}<input value={duration} disabled={busy} onChange={event => setDuration(event.target.value)}/></label>
    <button disabled={busy}>Apply duration · {operation.id}</button><DiscardForm id={formId}/>
  </form>;
}
