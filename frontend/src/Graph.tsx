import { useEffect } from 'react';
import { ReactFlow, Background, Controls, Handle, Position, BaseEdge, EdgeLabelRenderer, MarkerType, useNodesState,
  type Node, type NodeProps, type Edge, type EdgeProps } from '@xyflow/react';
import type { FlowNode, Model, Route } from './types';
import '@xyflow/react/dist/style.css';

type PlantNode = Node<{ model: FlowNode }, 'plant'>;
function MaterialNode({ data }: NodeProps<PlantNode>) {
  const node = data.model;
  return <article className={`material-node ${node.kind}`}>
    <small>{node.kind === 'station' ? 'Station' : node.kind === 'buffer' ? 'Buffer' : node.kind}</small>
    <strong>{node.id}</strong>
    {node.hall_id && <span className="hall">Hall: {node.hall_id}</span>}
    <div className="ports">
      {[...node.input_ports, ...node.output_ports].map((port) => <div key={`${port.direction}:${port.id}`} className={`port ${port.direction}`}>
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
const nodeTypes = { plant: MaterialNode };
const edgeTypes = { route: MaterialRoute };

export function Graph({ model, onSelect }: { model: Model; onSelect: (value: FlowNode | Route) => void }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<PlantNode>([]);
  useEffect(() => {
    setNodes(model.graph.nodes.map((node, index) => ({ id: node.id, type: 'plant',
      position: { x: (index % 5) * 340, y: Math.floor(index / 5) * 330 }, data: { model: node } })));
  }, [model, setNodes]);
  const lanes = new Map<string, number>();
  const edges: MaterialEdge[] = model.graph.routes.map((route) => {
    const pair = JSON.stringify([route.source_node_id, route.target_node_id]);
    const lane = lanes.get(pair) ?? 0;
    lanes.set(pair, lane + 1);
    return { id: route.id, type: 'route', source: route.source_node_id, target: route.target_node_id,
      sourceHandle: `output:${route.source_port_id}`, targetHandle: `input:${route.target_port_id}`,
      markerEnd: { type: MarkerType.ArrowClosed }, data: { route, lane, select: () => onSelect(route) } };
  });
  return <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
    onNodesChange={onNodesChange} onNodeClick={(_, node) => onSelect(node.data.model)}
    onEdgeClick={(_, edge) => edge.data && onSelect(edge.data.route)} nodesConnectable={false}
    deleteKeyCode={null} fitView minZoom={0.08} maxZoom={2}>
    <Background gap={24}/><Controls showInteractive={false}/>
  </ReactFlow>;
}
