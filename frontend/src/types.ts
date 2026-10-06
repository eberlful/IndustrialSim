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

export type LiveNode = { id: string; occupancy: number | null; unit_ids: string[] | null; observed_unit_ids?: string[]; busy?: boolean | null; blocked?: boolean | null; capacity?: number | null; machine_ids?: string[] | null };
export type LiveResource = { id: string; capacity: number | null; available_capacity: number | null; on_shift: boolean | null; on_break: boolean | null;
  allocations: { station_id: string; unit_id: string; op_id: string }[] | null; failed?: boolean | null; in_maintenance?: boolean | null; health?: number | null; operating_mode?: string | null; assigned_station_id?: string | null; qualifications?: string[] | null };
export type LiveUnit = { id: string; variant: string | null; state: string | null; location: string | null; quality_state: string | null; process_step_index: number | null; findings: unknown[] | null };
export type LiveTransport = { id: string; unit_id: string; route_id: string; source_node_id: string; target_node_id: string;
  pickup_time_ns: string; arrival_time_ns: string };
export type Observation = { transports?: Record<string, LiveTransport>; requests?: PendingDecisionBatch['batch']['requests']; simulated_time_ns: string; graph: Model['graph']; plant: Plant | null; stations: Record<string, LiveNode>; buffers: Record<string, LiveNode>;
  machines: Record<string, LiveResource>; workers: Record<string, LiveResource>; production_units: Record<string, LiveUnit>; raw_metrics: Record<string, number> };
export type SavedCheckpoint = { path: string; episode_id?: string; result_path?: string; mode?: 'baseline' | 'manual';
  config_hash?: string; model_hash?: string; simulated_time_ns?: string; checkpoint_hash?: string; created_at?: string; diagnostic?: string };
export type Episode = {
  step_delay_seconds: number;
  id: string; state: 'running' | 'pausing' | 'paused' | 'finished' | 'failed' | 'interrupted' | 'seeking_batch' | 'awaiting_decisions' | 'resolving'; provider: string; mode: 'baseline' | 'manual'; decision_batch: PendingDecisionBatch | null;
  configuration: Record<string, unknown>; restored_from: SavedCheckpoint | null; last_checkpoint: SavedCheckpoint | null;
  seed: string; result_path: string; simulated_time_ns: string; events_processed: number; wall_clock_seconds: number;
  observation: Observation | null; observation_views: { truth: Observation; available: Observation & { requests: PendingDecisionBatch['batch']['requests'] } } | null; diagnostics: string[];
  summary: { status: string; result_hash: string; raw_metrics: Record<string, unknown>; reward: number | null } | null;
};
export type LiveSelection = { kind: 'stations' | 'buffers' | 'machines' | 'workers' | 'production_units'; id: string };

export type DecisionSchema = { type?: string; anyOf?: DecisionSchema[]; default?: unknown; const?: unknown;
  properties?: Record<string, DecisionSchema>; required?: string[] };
export type PendingDecisionBatch = { batch: { batch_id: string; episode_id: string; time_ns: string | number;
  requests: { request_id: string; target_id: string; action_schema: string; time_ns: string | number; observation: Record<string, unknown> }[] };
  action_schemas: Record<string, DecisionSchema>; action_types: Record<string, string[]>; suggested_actions: Record<string, unknown>[] };

export type EpisodeCapabilities = Record<'start' | 'pause' | 'continue' | 'next_batch' | 'submit_batch' | 'checkpoint' | 'restore', boolean>;

export type EpisodeResponse = { capabilities?: EpisodeCapabilities; checkpoint?: SavedCheckpoint; episode?: Episode | null; accepted?: boolean;
  diagnostics?: (string | { message?: string; msg?: string })[]; detail?: string | { msg?: string; message?: string }[] };
