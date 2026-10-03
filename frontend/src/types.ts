import type { EpisodeInputs } from './EpisodeInputs';
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
export type Layout = { positions: Record<string, { x: number; y: number }>; grouping: 'none' | 'area' | 'hall' };
export type Model = { episode_inputs?: EpisodeInputs; layout: Layout; name: string; yaml: string; configuration: Record<string, unknown>; graph: { nodes: FlowNode[]; routes: Route[] }; plant: Plant | null; valid: boolean; graph_available: boolean; diagnostics: string[] };
export type Project = { project: string; model: Model | null; models?: string[]; drafts?: string[]; saved_draft?: string; accepted?: boolean; diagnostics?: string[]; can_undo?: boolean; can_redo?: boolean; saved_path?: string };
export type Resource = { id: string; name?: string | null; capacity?: number | string | null; kind?: 'individual' | 'pool'; qualifications?: string[]; [key: string]: unknown };
export type WorkerRequirement = { worker_id?: string | null; qualification?: string | null; count?: number | string | null };
export type Operation = { id: string; duration: number | string; required_machines?: string[]; required_workers?: WorkerRequirement[] };

export type LiveNode = { id: string; occupancy: number; unit_ids: string[]; busy?: boolean; blocked?: boolean; capacity?: number; machine_ids?: string[] };
export type LiveResource = { id: string; capacity: number; available_capacity: number; on_shift: boolean; on_break: boolean;
  allocations: { station_id: string; unit_id: string; op_id: string }[]; failed?: boolean; in_maintenance?: boolean; health?: number; operating_mode?: string; assigned_station_id?: string | null; qualifications?: string[] };
export type LiveUnit = { id: string; variant: string; state: string; location: string; quality_state: string; process_step_index: number; findings: unknown[] };
export type Observation = { simulated_time_ns: string; graph: Model['graph']; plant: Plant | null; stations: Record<string, LiveNode>; buffers: Record<string, LiveNode>;
  machines: Record<string, LiveResource>; workers: Record<string, LiveResource>; production_units: Record<string, LiveUnit>; raw_metrics: Record<string, number> };
export type Episode = {
  id: string; state: 'running' | 'pausing' | 'paused' | 'finished' | 'failed' | 'interrupted' | 'seeking_batch' | 'awaiting_decisions' | 'resolving'; provider: string; mode: 'baseline' | 'manual'; decision_batch: PendingDecisionBatch | null;
  seed: string; result_path: string; simulated_time_ns: string; events_processed: number; wall_clock_seconds: number;
  observation: Observation | null; diagnostics: string[];
  summary: { status: string; result_hash: string; raw_metrics: Record<string, number>; reward: number | null } | null;
};
export type LiveSelection = { kind: 'stations' | 'buffers' | 'machines' | 'workers' | 'production_units'; id: string };

export type DecisionSchema = { type?: string; anyOf?: DecisionSchema[]; default?: unknown; const?: unknown;
  properties?: Record<string, DecisionSchema>; required?: string[] };
export type PendingDecisionBatch = { batch: { batch_id: string; episode_id: string; time_ns: string | number;
  requests: { request_id: string; target_id: string; action_schema: string; time_ns: string | number; observation: Record<string, unknown> }[] };
  action_schemas: Record<string, DecisionSchema>; action_types: Record<string, string[]>; suggested_actions: Record<string, unknown>[] };

export type EpisodeResponse = { episode?: Episode | null; accepted?: boolean;
  diagnostics?: (string | { message?: string; msg?: string })[]; detail?: string | { msg?: string; message?: string }[] };
