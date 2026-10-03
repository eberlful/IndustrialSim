import { useEffect } from 'react';
import { ReactFlow, Background, Controls, Handle, Position, BaseEdge, EdgeLabelRenderer, MarkerType, useNodesState,
  type Node, type NodeProps, type Edge, type EdgeProps } from '@xyflow/react';
import type { FlowNode, Layout, Model, Route, Observation, LiveNode } from './types';
import '@xyflow/react/dist/style.css';
import { resourcesAtNode } from './episodeResources';

type PlantNode = Node<{ model: FlowNode; live?: LiveNode; resources?: string }, 'plant'>;
function MaterialNode({ data }: NodeProps<PlantNode>) {
  const node = data.model;
  return <article className={`material-node ${node.kind}`}>
    <small>{node.kind === 'station' ? 'Station' : node.kind === 'buffer' ? 'Buffer' : node.kind}</small>
    <strong>{node.id}</strong>
    {data.live && <span className="occupancy">Occupancy: {data.live.occupancy ?? 'Unavailable'}{data.live.capacity != null ? ` / ${data.live.capacity}` : ''}
      {data.live.busy ? ' · busy' : ''}{data.live.blocked ? ' · blocked' : ''}</span>}
    {data.live?.observed_unit_ids?.length ? <span>Observed Production Units: {data.live.observed_unit_ids.join(', ')}</span> : null}
    {data.resources && <span>{data.resources}</span>}
    {node.hall_id && <span className="hall">Hall: {node.hall_id}</span>}
    <div className="ports">
      {[...node.input_ports, ...node.output_ports].map((port, index) => <div key={`${index}:${port.direction}:${port.id}`} className={`port ${port.direction}`}>
        <Handle id={`${port.direction}:${port.id}`} type={port.direction === 'input' ? 'target' : 'source'}
          position={port.direction === 'input' ? Position.Left : Position.Right} isConnectable={false}/>
        <span>{port.direction === 'input' ? '→' : '↗'} {port.id} · {port.port_type}</span>
      </div>)}
    </div>
  </article>;
}

type MaterialEdge = Edge<{ route: Route; lane: number; select: () => void }, 'route'>;
function MaterialRoute({ sourceX, sourceY, targetX, targetY, data, markerEnd, selected }: EdgeProps<MaterialEdge>) {
  // Separate every parallel route and give backward/self routes a visible arc.
  const lane = data?.lane ?? 0;
  const backwards = targetX <= sourceX;
  const bend = backwards ? 160 + lane * 65 : 45 + lane * 65;
  const middleX = (sourceX + targetX) / 2;
  const middleY = (sourceY + targetY) / 2 - bend;
  const path = `M ${sourceX},${sourceY} Q ${sourceX + 100},${middleY} ${middleX},${middleY} Q ${targetX - 100},${middleY} ${targetX},${targetY}`;
  return <><BaseEdge path={path} markerEnd={markerEnd}
    style={{ stroke: selected ? '#174bc0' : '#677a92', strokeWidth: selected ? 3 : 1.6 }}/><EdgeLabelRenderer>
    <button className="route-label nodrag nopan" style={{ transform: `translate(-50%, -50%) translate(${middleX}px, ${middleY}px)` }}
      onClick={data?.select}>{data?.route.id}</button>
  </EdgeLabelRenderer></>;
}
function DisplayGroup({ data }: NodeProps<Node<{ label: string }, 'group'>>) {
  return <strong className="display-group-label">{data.label}</strong>;
}
const nodeTypes = { plant: MaterialNode, group: DisplayGroup };

export function locationGroups(model: Model, grouping: Layout['grouping']) {
  const groups = new Map<string, { label: string; nodes: FlowNode[] }>();
  for (const node of model.graph.nodes) {
    const area = model.plant?.areas.find(area => area.halls.some(hall => hall.id === node.hall_id));
    const hall = area?.halls.find(hall => hall.id === node.hall_id);
    const key = grouping === 'none' ? 'all' : grouping === 'area' ? area?.id ?? 'unassigned' : hall?.id ?? 'unassigned';
    const label = grouping === 'area' ? `Area: ${area?.name ?? 'Unassigned'}` : `Hall: ${hall?.name ?? 'Unassigned'}`;
    if (!groups.has(key)) groups.set(key, { label, nodes: [] });
    groups.get(key)!.nodes.push(node);
  }
  return groups;
}

export function arrangedPositions(model: Model, grouping: Layout['grouping']) {
  const positions: Layout['positions'] = {};
  let offsetY = 0;
  for (const group of locationGroups(model, grouping).values()) {
    group.nodes.forEach((node, index) => { positions[node.id] = { x: (index % 5) * 340, y: offsetY + Math.floor(index / 5) * 330 }; });
    offsetY += Math.ceil(group.nodes.length / 5) * 330 + 120;
  }
  return positions;
}
const edgeTypes = { route: MaterialRoute };

export function Graph({ model, onSelect, onMove, busy, observation }: { observation?: Observation | null; model: Model; onSelect: (value: FlowNode | Route) => void;
  onMove: (positions: Layout['positions']) => void; busy: boolean }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  useEffect(() => {
    const initial = arrangedPositions(model, model.layout.grouping);
    const material: PlantNode[] = model.graph.nodes.map(node => ({ id: node.id, type: 'plant',
      position: model.layout.positions[node.id] ?? initial[node.id], data: { model: node } }));
    const backgrounds: Node[] = [];
    if (model.layout.grouping !== 'none') {
      let index = 0;
      for (const group of locationGroups(model, model.layout.grouping).values()) {
        const positions = group.nodes.map(node => model.layout.positions[node.id] ?? initial[node.id]);
        const left = Math.min(...positions.map(p => p.x)) - 30;
        const top = Math.min(...positions.map(p => p.y)) - 60;
        backgrounds.push({ id: `display-group:${index++}`, type: 'group', position: { x: left, y: top },
          data: { label: group.label }, draggable: false, selectable: false, zIndex: -1,
          style: { width: Math.max(...positions.map(p => p.x)) - left + 290,
            height: Math.max(...positions.map(p => p.y)) - top + 280, background: '#e8eef680',
            border: '1px solid #a6b8cc', borderRadius: 12, pointerEvents: 'none' } });
      }
    }
    setNodes([...backgrounds, ...material]);
  }, [model, setNodes]);
  useEffect(() => {
    setNodes(current => current.map(node => {
      if (node.type !== 'plant') return node;
      const live = observation?.stations[node.id] ?? observation?.buffers[node.id];
      const resources = resourcesAtNode(observation, node.id).map(({ resource }) =>
        `${resource.id}: ${resource.failed ? 'failed' : resource.in_maintenance ? 'maintenance' : `${resource.available_capacity ?? 'Unavailable'}/${resource.capacity ?? 'Unavailable'} available`}`).join(' · ');
      return { ...node, data: { ...node.data, live, resources } };
    }));
  }, [observation, model, setNodes]);
  const lanes = new Map<string, number>();
  const edges: MaterialEdge[] = model.graph.routes.filter(route => {
    const source = model.graph.nodes.find(node => node.id === route.source_node_id);
    const target = model.graph.nodes.find(node => node.id === route.target_node_id);
    return source?.output_ports.some(port => port.id === route.source_port_id)
      && target?.input_ports.some(port => port.id === route.target_port_id);
  }).map((route) => {
    const pair = JSON.stringify([route.source_node_id, route.target_node_id]);
    const lane = lanes.get(pair) ?? 0;
    lanes.set(pair, lane + 1);
    return { id: route.id, type: 'route', source: route.source_node_id, target: route.target_node_id,
      sourceHandle: `output:${route.source_port_id}`, targetHandle: `input:${route.target_port_id}`,
      markerEnd: { type: MarkerType.ArrowClosed }, data: { route, lane, select: () => onSelect(route) } };
  });
  return <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
    onNodesChange={onNodesChange} onNodeClick={(_, node) => { if (node.type === 'plant') onSelect(node.data.model as FlowNode); }}
    nodesDraggable={!busy} onNodeDragStop={(_, _node, moved) => onMove(Object.fromEntries(moved.map(node => [node.id, node.position])))}
    onEdgeClick={(_, edge) => edge.data && onSelect(edge.data.route)} nodesConnectable={false}
    deleteKeyCode={null} fitView minZoom={0.08} maxZoom={2}>
    <Background gap={24}/><Controls showInteractive={false}/>
  </ReactFlow>;
}
