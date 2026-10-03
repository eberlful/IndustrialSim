import { useEffect, useRef, useState } from 'react';

import type { Episode, EpisodeResponse } from './types';
import { ManualDecisionBatch } from './ManualDecisionBatch';

type Response = EpisodeResponse;

export function EpisodeControl({ canStart, episode, onChange: setEpisode }: { canStart: boolean; episode: Episode | null; onChange: (episode: Episode | null) => void }) {
  const [pending, setPending] = useState(false);
  const [mode, setMode] = useState<'baseline' | 'manual'>('baseline');
  const active = !!episode && ['running', 'pausing', 'paused', 'seeking_batch', 'awaiting_decisions', 'resolving'].includes(episode.state);
  const [errors, setErrors] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
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
        if (!disposed && current === revision.current && !mutationInFlight.current) { setEpisode(result.episode ?? null); setConnected(true); }
      } catch (error) {
        if (!disposed && current === revision.current && !mutationInFlight.current) { setConnected(false); setErrors([error instanceof Error ? error.message : 'Could not reach the Episode service.']); }
      } finally {
        if (!disposed) timer = setTimeout(() => void poll(), 500);
      }
    }
    void poll();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [setEpisode]);
  async function command(action: 'start' | 'pause' | 'continue' | 'next-batch' | 'submit-batch', proposal?: { batch_id: string; actions: Record<string, unknown>[] }): Promise<Response | undefined> {
    if (mutationInFlight.current) return;
    mutationInFlight.current = true;
    revision.current += 1;
    setPending(true); setErrors([]);
    try {
      const response = await fetch(`/api/episode/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(action === 'start' ? { mode } : { episode_id: episode?.id, ...proposal }) });
      const result: Response = await response.json();
      if (result.episode !== undefined) setEpisode(result.episode);
      if (action !== 'submit-batch' && (!response.ok || !result.accepted)) setErrors((result.diagnostics ?? ['Episode command was rejected.']).map(diagnostic => typeof diagnostic === 'string' ? diagnostic : diagnostic.message ?? diagnostic.msg ?? 'Invalid command'));
      return result;
    } catch { if (action !== 'submit-batch') setErrors(['Could not reach the service to control the Episode.']); }
    finally { revision.current += 1; mutationInFlight.current = false; setPending(false); }
  }
  return <section className="import-panel" aria-label="Episode execution">
    <h2>Episode execution</h2>
    <label>Decision mode<select aria-label="Decision mode" disabled={active || pending} value={active ? episode!.mode : mode} onChange={event => setMode(event.target.value as 'baseline' | 'manual')}>
      <option value="baseline">Automatic Baseline</option><option value="manual">Manual</option>
    </select></label>
    <p>Decision Provider: {episode?.provider ?? (mode === 'manual' ? 'Manual' : 'Baseline')}</p>
    <button disabled={!canStart || !connected || pending || active} onClick={() => void command('start')}>Start Episode</button>
    <button disabled={!connected || pending || !['running', 'seeking_batch'].includes(episode?.state ?? '')} onClick={() => void command('pause')}>Pause Episode</button>
    <button disabled={!connected || pending || !(episode?.state === 'paused' || (episode?.state === 'awaiting_decisions' && episode.mode === 'baseline'))} onClick={() => void command('continue')}>Continue Episode</button>
    <button disabled={!connected || pending || !['running', 'paused'].includes(episode?.state ?? '')} onClick={() => void command('next-batch')}>Next Decision Batch</button>
    <p aria-live="polite" aria-label="Episode status">{pending ? 'Applying Episode command…' : !connected ? 'Connecting to Episode service…' : episode ? `${episode.state === 'running' ? '◷ Running' : episode.state === 'seeking_batch' ? '◷ Seeking Decision Batch' : episode.state === 'awaiting_decisions' ? 'Ⅱ Awaiting decisions' : episode.state === 'resolving' ? '◷ Answering with Baseline' : episode.state === 'pausing' ? '◷ Pausing' : episode.state === 'paused' ? 'Ⅱ Paused' : episode.state === 'finished' ? `✓ ${episode.summary?.status}` : `⚠ ${episode.state}`} · ${episode.id}` : '○ Not started'}</p>
    <p className="hint">The local service runs independently of this browser. Plant and setup edits apply to the next Episode. Execution requires applied, valid configuration.</p>
    {errors.length > 0 && <ul role="alert">{errors.map((error, index) => <li key={index}>{error}</li>)}</ul>}
    {episode?.decision_batch && <ManualDecisionBatch key={`${episode.id}:${episode.decision_batch.batch.batch_id}`} episode={episode} onSubmit={actions => command('submit-batch', { batch_id: episode.decision_batch!.batch.batch_id, actions })}/>}
    {episode && <>
      <p>Frozen seed: {episode.seed} · Simulated time: {episode.simulated_time_ns} ns · Events processed: {episode.events_processed}</p>
      <p>Wall-clock elapsed: {episode.wall_clock_seconds.toFixed(1)} s (includes pauses)</p>
      <p>Result directory: <code>{episode.result_path}</code></p>
      {episode.diagnostics.length > 0 && <ul role="alert">{episode.diagnostics.map((error, index) => <li key={index}>{error}</li>)}</ul>}
      {episode.summary && <div aria-label="Episode outcome"><h3>Outcome: {episode.summary.status}</h3>
        <p>Result hash: <code>{episode.summary.result_hash}</code></p>
        <dl className="outcome-metrics">{Object.entries(episode.summary.raw_metrics).map(([metric, value]) => <div key={metric}><dt>{metric.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>)}</dl>
        {episode.summary.reward != null && <p>Reward: {episode.summary.reward}</p>}
        <p>Manifest, audit, summary, resolved configuration and final Checkpoint are saved in the result directory. Telemetry follows the loaded configuration.</p>
      </div>}
    </>}
  </section>;
}
