import { useDraftField, useDraftForm, DiscardForm } from './PlantDraftContext';
import type { FlowNode, Model, Port, Route } from './types';

export type StructureCommand = {
  action: 'add' | 'update' | 'delete'; kind: 'node' | 'route'; element_id: string;
  changes?: Record<string, unknown>;
};
type Command = (command: StructureCommand) => Promise<boolean>;

export function RouteConnections({ model, route, busy, command }: {
  model: Model; route?: Route; busy: boolean; command: Command;
}) {
  const formId = route ? `route:${route.id}:connections` : 'graph:new-route';
  const form = useDraftForm(formId);
  const firstSource = model.graph.nodes.find(node => node.kind === 'source') ?? model.graph.nodes[0];
  const firstTarget = model.graph.nodes.find(node => node.kind === 'sink') ?? model.graph.nodes[0];
  const [id, setId] = useDraftField(formId, 'id', route?.id ?? '');
  const [source, setSource] = useDraftField(formId, 'source', route?.source_node_id ?? firstSource?.id ?? '');
  const [target, setTarget] = useDraftField(formId, 'target', route?.target_node_id ?? firstTarget?.id ?? '');
  const [output, setOutput] = useDraftField(formId, 'output', route?.source_port_id ?? firstSource?.output_ports[0]?.id ?? '');
  const [input, setInput] = useDraftField(formId, 'input', route?.target_port_id ?? firstTarget?.input_ports[0]?.id ?? '');
  const sourcePorts = model.graph.nodes.find(node => node.id === source)?.output_ports ?? [];
  const targetPorts = model.graph.nodes.find(node => node.id === target)?.input_ports ?? [];
  function options(values: string[], current: string) {
    return [...new Set(['', ...values, ...(current ? [current] : [])])].map(value => <option key={value} value={value}>{value || 'Choose…'}</option>);
  }
  return <form className="property-form" onSubmit={event => {
    event.preventDefault(); void form.apply(() => command({ action: route ? 'update' : 'add', kind: 'route', element_id: id,
      changes: { source_node_id: source, source_port_id: output, target_node_id: target, target_port_id: input } }));
  }}>
    {!route && <label>New route ID<input value={id} disabled={busy} onChange={event => setId(event.target.value)}/></label>}
    <label>Source node<select value={source} disabled={busy} onChange={event => {
      setSource(event.target.value); setOutput(model.graph.nodes.find(node => node.id === event.target.value)?.output_ports[0]?.id ?? '');
    }}>{options(model.graph.nodes.map(node => node.id), source)}</select></label>
    <label>Output Port<select value={output} disabled={busy} onChange={event => setOutput(event.target.value)}>{options(sourcePorts.map(port => port.id), output)}</select></label>
    <label>Target node<select value={target} disabled={busy} onChange={event => {
      setTarget(event.target.value); setInput(model.graph.nodes.find(node => node.id === event.target.value)?.input_ports[0]?.id ?? '');
    }}>{options(model.graph.nodes.map(node => node.id), target)}</select></label>
    <label>Input Port<select value={input} disabled={busy} onChange={event => setInput(event.target.value)}>{options(targetPorts.map(port => port.id), input)}</select></label>
    <button disabled={busy || !id.trim()}>{route ? 'Apply connection' : 'Add route'}</button><DiscardForm id={formId}/>
  </form>;
}

export function PortEditor({ node, busy, command }: { node: FlowNode; busy: boolean; command: Command }) {
  const formId = `node:${node.id}:ports`;
  const form = useDraftForm(formId);
  const [ports, setPorts] = useDraftField<Port[]>(formId, 'ports', [...node.input_ports, ...node.output_ports]);
  function change(index: number, changes: Partial<Port>) {
    setPorts(previous => previous.map((port, i) => i === index ? { ...port, ...changes } : port));
  }
  return <form className="property-form" aria-label="Typed Ports" onSubmit={event => {
    event.preventDefault(); void form.apply(() => command({ action: 'update', kind: 'node', element_id: node.id,
      changes: { input_ports: ports.filter(port => port.direction === 'input'), output_ports: ports.filter(port => port.direction === 'output') } }));
  }}>
    <h3>Typed Ports</h3>
    {ports.map((port, index) => <fieldset key={index} disabled={busy}>
      <legend>Port {index + 1}</legend>
      <label>Port ID<input value={port.id} onChange={event => change(index, { id: event.target.value })}/></label>
      <label>Port type<input value={port.port_type} onChange={event => change(index, { port_type: event.target.value })}/></label>
      <label>Port direction<select value={port.direction} onChange={event => change(index, { direction: event.target.value as Port['direction'] })}>
        <option value="input">Input</option><option value="output">Output</option>
      </select></label>
      <button type="button" onClick={() => setPorts(previous => previous.filter((_, i) => i !== index))}>Remove Port {index + 1}</button>
    </fieldset>)}
    <button type="button" disabled={busy} onClick={() => setPorts(previous => [...previous, { id: '', port_type: 'body', direction: node.kind === 'source' ? 'output' : 'input' }])}>Add Port</button>
    <button disabled={busy}>Apply Ports</button><DiscardForm id={formId}/>
    <p className="hint">Removing or renaming a Port retains its routes and reports references that need correction.</p>
  </form>;
}

export function GraphTools({ model, busy, command, select }: {
  model: Model; busy: boolean; command: Command; select: (route: Route) => void;
}) {
  const formId = 'graph:new-node';
  const form = useDraftForm(formId);
  const [id, setId] = useDraftField(formId, 'id', '');
  const [kind, setKind] = useDraftField<FlowNode['kind']>(formId, 'kind', 'station');
  if (!model.configuration.material_flow) return <p>Structural editing requires a model with material_flow.</p>;
  return <>
    <form className="property-form" onSubmit={event => {
      event.preventDefault(); void form.apply(() => command({ action: 'add', kind: 'node', element_id: id, changes: { kind } }));
    }}>
      <label>New node ID<input value={id} disabled={busy} onChange={event => setId(event.target.value)}/></label>
      <label>Node type<select value={kind} disabled={busy} onChange={event => setKind(event.target.value as FlowNode['kind'])}>
        <option value="source">Source</option><option value="sink">Sink</option><option value="station">Station</option><option value="buffer">Buffer</option>
      </select></label>
      <button disabled={busy || !id.trim()}>Add node</button><DiscardForm id={formId}/>
    </form>
    <p className="hint">New nodes start with body Ports. Stations start with a 1s Operation; Buffers have capacity 1. Select the node to edit its properties.</p>
    <details><summary>Create directed route</summary><RouteConnections model={model} busy={busy} command={command}/></details>
    <details><summary>All routes ({model.graph.routes.length})</summary>
      <p className="hint">Includes routes whose endpoints or Ports need correction.</p>
      <ul>{model.graph.routes.map(route => <li key={route.id}><button disabled={busy} onClick={() => select(route)}>Inspect {route.id}</button> {route.source_node_id} → {route.target_node_id}</li>)}</ul>
    </details>
  </>;
}
