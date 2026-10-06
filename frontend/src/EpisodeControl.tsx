import { useEffect, useRef, useState } from 'react';

import type { Episode, EpisodeResponse, SavedCheckpoint, EpisodeCapabilities } from './types';
import { ManualDecisionBatch } from './ManualDecisionBatch';

type Response = EpisodeResponse;

export function EpisodeControl({ canStart, episode, onChange: setEpisode }: { canStart: boolean; episode: Episode | null; onChange: (episode: Episode | null) => void }) {
  const [pending, setPending] = useState(false);
  const [mode, setMode] = useState<'baseline' | 'manual'>('baseline');
  const [stepDelay, setStepDelay] = useState(1);
  const [capabilities, setCapabilities] = useState<EpisodeCapabilities>({ start: false, pause: false, continue: false, next_batch: false, submit_batch: false, checkpoint: false, restore: false });
  const active = !!episode && !capabilities.start;
  const [errors, setErrors] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [checkpoints, setCheckpoints] = useState<SavedCheckpoint[]>([]);
  const [checkpointPath, setCheckpointPath] = useState('');
  async function readCheckpoints() {
    try {
      const response = await fetch('/api/episode/checkpoints');
      if (!response.ok) throw new Error('Could not list saved Checkpoints.');
      const result: { checkpoints: SavedCheckpoint[] } = await response.json();
      setCheckpoints(result.checkpoints);
    } catch { setErrors(['Could not list saved Checkpoints. Reconnect and refresh the list.']); }
  }
  useEffect(() => { void readCheckpoints(); }, []);
  const revision = useRef(0);
  const mutationInFlight = useRef(false);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      const current = revision.current;
      try {
        const response = await fetch('/api/episode', { signal: controller.signal });
        if (!response.ok) throw new Error('Could not read the service-owned Episode.');
        const result: Response = await response.json();
        if (!disposed && current === revision.current && !mutationInFlight.current) { setEpisode(result.episode ?? null); if (result.capabilities) setCapabilities(result.capabilities); setConnected(true); }
      } catch (error) {
        if (!disposed && current === revision.current && !mutationInFlight.current) { setConnected(false); setErrors([error instanceof Error ? error.message : 'Could not reach the Episode service.']); }
      } finally {
        if (!disposed) timer = setTimeout(() => void poll(), 250);
      }
    }
    void poll();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [setEpisode]);
  async function command(action: 'start' | 'pause' | 'continue' | 'next-batch' | 'submit-batch' | 'checkpoint' | 'restore', proposal?: { batch_id?: string; actions?: Record<string, unknown>[]; path?: string }): Promise<Response | undefined> {
    if (mutationInFlight.current) return;
    mutationInFlight.current = true;
    revision.current += 1;
    setPending(true); setErrors([]);
    try {
      const response = await fetch(`/api/episode/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(action === 'start' ? { mode, step_delay_seconds: stepDelay } : action === 'restore' ? { path: proposal?.path } : { episode_id: episode?.id, ...proposal }) });
      const result: Response = await response.json();
      if (result.episode !== undefined) setEpisode(result.episode);
      if (result.capabilities) setCapabilities(result.capabilities);
      if (action !== 'submit-batch' && (!response.ok || !result.accepted)) setErrors((result.diagnostics ?? ['Episode command was rejected.']).map(diagnostic => typeof diagnostic === 'string' ? diagnostic : diagnostic.message ?? diagnostic.msg ?? 'Invalid command'));
      if (action === 'checkpoint' && result.accepted) { setCheckpointPath(result.checkpoint?.path ?? ''); await readCheckpoints(); }
      return result;
    } catch { if (action !== 'submit-batch') setErrors(['Could not reach the service to control the Episode.']); }
    finally { revision.current += 1; mutationInFlight.current = false; setPending(false); }
  }
  return <section className="import-panel" aria-label="Episode execution">
    <h2>Episode execution</h2>
    <label>Decision mode<select aria-label="Decision mode" disabled={active || pending} value={active ? episode!.mode : mode} onChange={event => setMode(event.target.value as 'baseline' | 'manual')}>
      <option value="baseline">Automatic Baseline</option><option value="manual">Manual</option>
    </select></label>
    <label>Playback speed<select aria-label="Playback speed" disabled={active || pending} value={active ? episode!.step_delay_seconds : stepDelay} onChange={event => setStepDelay(Number(event.target.value))}>
      <option value={2}>Slow · 2 s per step</option><option value={1}>Normal · 1 s per step</option><option value={0.5}>Fast · 0.5 s per step</option><option value={0}>Unlimited</option>
    </select></label>
    <p className="hint">Choose the speed before starting. Each step completes all events at one simulation timestamp.</p>
    <p>Decision Provider: {episode?.provider ?? (mode === 'manual' ? 'Manual' : 'Baseline')}</p>
    <button disabled={!canStart || !connected || pending || !capabilities.start} onClick={() => void command('start')}>Start Episode</button>
    <button disabled={!connected || pending || !capabilities.pause} onClick={() => void command('pause')}>Pause Episode</button>
    <button disabled={!connected || pending || !capabilities.continue} onClick={() => void command('continue')}>Continue Episode</button>
    <button disabled={!connected || pending || !capabilities.next_batch} onClick={() => void command('next-batch')}>Next Decision Batch</button>
    <section aria-label="Episode Checkpoints">
      <h3>Durable Checkpoints</h3>
      <p>Create a Checkpoint explicitly while paused or awaiting decisions. Restore resumes only from that saved state, using Baseline or manual decisions. Browser reconnect does not restore execution.</p>
      <button disabled={!connected || pending || !capabilities.checkpoint} onClick={() => void command('checkpoint')}>Create Checkpoint</button>
      <label>Saved Checkpoint<select aria-label="Saved Checkpoint" disabled={pending} value={checkpointPath} onChange={event => setCheckpointPath(event.target.value)}>
        <option value="">Choose a saved Checkpoint…</option>
        {checkpoints.map(checkpoint => <option key={checkpoint.path} value={checkpoint.path}>{checkpoint.path} · {checkpoint.diagnostic ?? `${checkpoint.mode} · Episode ${checkpoint.episode_id} · ${checkpoint.simulated_time_ns} ns`}</option>)}
      </select></label>
      <button disabled={!connected || pending} onClick={() => void readCheckpoints()}>Refresh Checkpoints</button>
      <button disabled={!connected || pending || !capabilities.restore || !checkpointPath} onClick={() => void command('restore', { path: checkpointPath })}>Restore Checkpoint</button>
      {episode?.last_checkpoint && <p aria-label="Created Checkpoint">Checkpoint saved: {episode.last_checkpoint.path} · Episode {episode.last_checkpoint.episode_id} · Configuration {episode.last_checkpoint.config_hash}</p>}
      {episode?.restored_from && <p aria-label="Checkpoint provenance">Restored from {episode.restored_from.path} · Parent Episode {episode.restored_from.episode_id} · Configuration {episode.restored_from.config_hash}</p>}
    </section>
    <p aria-live="polite" aria-label="Episode status">{pending ? 'Applying Episode command…' : !connected ? 'Connecting to Episode service…' : episode ? `${episode.state === 'running' ? '◷ Running' : episode.state === 'seeking_batch' ? '◷ Seeking Decision Batch' : episode.state === 'awaiting_decisions' ? 'Ⅱ Awaiting decisions' : episode.state === 'resolving' ? '◷ Answering with Baseline' : episode.state === 'pausing' ? '◷ Pausing' : episode.state === 'paused' ? 'Ⅱ Paused' : episode.state === 'finished' ? `✓ ${episode.summary?.status}` : `⚠ ${episode.state}`} · ${episode.id}` : '○ Not started'}</p>
    <p className="hint">The local service runs independently of this browser. Plant and setup edits apply to the next Episode. Execution requires applied, valid configuration.</p>
    {errors.length > 0 && <ul role="alert">{errors.map((error, index) => <li key={index}>{error}</li>)}</ul>}
    {episode?.decision_batch && <ManualDecisionBatch key={`${episode.id}:${episode.decision_batch.batch.batch_id}`} episode={episode} disabled={!connected || pending || !capabilities.submit_batch} onSubmit={actions => command('submit-batch', { batch_id: episode.decision_batch!.batch.batch_id, actions })}/>}
    {episode && <>
      <p>Frozen seed: {episode.seed} · Simulated time: {episode.simulated_time_ns} ns · Events processed: {episode.events_processed}</p>
      <p>Wall-clock elapsed: {episode.wall_clock_seconds.toFixed(1)} s (includes pauses)</p>
      <p>Result directory: <code>{episode.result_path}</code></p>
      {episode.diagnostics.length > 0 && <ul role="alert">{episode.diagnostics.map((error, index) => <li key={index}>{error}</li>)}</ul>}
      {episode.summary && <div aria-label="Episode outcome"><h3>Outcome: {episode.summary.status}</h3>
        <p>Result hash: <code>{episode.summary.result_hash}</code></p>
        <dl className="outcome-metrics">{Object.entries(episode.summary.raw_metrics).map(([metric, value]) => <div key={metric}><dt>{metric.replaceAll('_', ' ')}</dt><dd>{JSON.stringify(value)}</dd></div>)}</dl>
        {episode.summary.reward != null && <p>Reward: {episode.summary.reward}</p>}
        <p>Manifest, audit, summary, resolved configuration and final Checkpoint are saved in the result directory. Telemetry follows the loaded configuration.</p>
      </div>}
    </>}
  </section>;
}
