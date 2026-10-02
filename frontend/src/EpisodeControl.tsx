import { useEffect, useRef, useState } from 'react';

import type { Episode } from './types';

type Response = { episode: Episode | null; accepted?: boolean; diagnostics?: string[] };

export function EpisodeControl({ canStart, episode, onChange: setEpisode }: { canStart: boolean; episode: Episode | null; onChange: (episode: Episode | null) => void }) {
  const [pending, setStarting] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const revision = useRef(0);
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
        if (!disposed && current === revision.current) { setEpisode(result.episode); setConnected(true); }
      } catch (error) {
        if (!disposed) { setConnected(false); setErrors([error instanceof Error ? error.message : 'Could not reach the Episode service.']); }
      } finally {
        if (!disposed) timer = setTimeout(() => void poll(), 500);
      }
    }
    void poll();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [setEpisode]);
  async function command(action: 'start' | 'pause' | 'continue') {
    revision.current += 1;
    setStarting(true); setErrors([]);
    try {
      const response = await fetch(`/api/episode/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: action === 'start' ? undefined : JSON.stringify({ episode_id: episode?.id }) });
      const result: Response = await response.json();
      setEpisode(result.episode);
      if (!response.ok || !result.accepted) setErrors(result.diagnostics ?? ['Episode command was rejected.']);
    } catch { setErrors(['Could not reach the service to control the Episode.']); }
    finally { revision.current += 1; setStarting(false); }
  }
  return <section className="import-panel" aria-label="Episode execution">
    <h2>Episode execution</h2>
    <p>Decision Provider: Baseline</p>
    <button disabled={!canStart || !connected || pending || ['running', 'pausing', 'paused'].includes(episode?.state ?? '')} onClick={() => void command('start')}>Start Episode</button>
    <button disabled={!connected || pending || episode?.state !== 'running'} onClick={() => void command('pause')}>Pause Episode</button>
    <button disabled={!connected || pending || episode?.state !== 'paused'} onClick={() => void command('continue')}>Continue Episode</button>
    <p aria-live="polite" aria-label="Episode status">{pending ? 'Applying Episode command…' : !connected ? 'Connecting to Episode service…' : episode ? `${episode.state === 'running' ? '◷ Running' : episode.state === 'pausing' ? '◷ Pausing' : episode.state === 'paused' ? 'Ⅱ Paused' : episode.state === 'finished' ? `✓ ${episode.summary?.status}` : `⚠ ${episode.state}`} · ${episode.id}` : '○ Not started'}</p>
    <p className="hint">The local service runs independently of this browser. Plant and setup edits apply to the next Episode. Execution requires applied, valid configuration.</p>
    {errors.length > 0 && <ul role="alert">{errors.map((error, index) => <li key={index}>{error}</li>)}</ul>}
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
