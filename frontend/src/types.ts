export type Port = { id: string; port_type: string; direction: 'input' | 'output' };
export type FlowNode = {
  id: string; kind: 'source' | 'sink' | 'station' | 'buffer'; hall_id?: string | null;
  input_ports: Port[]; output_ports: Port[]; [key: string]: unknown;
};
export type Route = {
  id: string; source_node_id: string; target_node_id: string;
  source_port_id: string; target_port_id: string; transit_time: number | string;
  [key: string]: unknown;
};
export type Plant = { id: string; name: string; areas: { id: string; name: string; halls: { id: string; name: string }[] }[] };
export type Model = { name: string; yaml: string; configuration: Record<string, unknown>; graph: { nodes: FlowNode[]; routes: Route[] }; plant: Plant | null; valid: boolean; diagnostics: string[] };
export type Project = { project: string; model: Model | null; models?: string[]; accepted?: boolean; diagnostics?: string[]; can_undo?: boolean; can_redo?: boolean; saved_path?: string };
