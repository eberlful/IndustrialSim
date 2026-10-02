import { useEffect, useRef, useState } from 'react';

type Episode = {
  id: string; state: 'running' | 'finished' | 'failed' | 'interrupted'; provider: string;
  seed: string; result_path: string; simulated_time_ns: string; events_processed: number;
  diagnostics: string[];
  summary: { status: string; result_hash: string; raw_metrics: Record<string, number>; reward: number | null } | null;
};
type Response = { episode: Episode | null; accepted?: boolean; diagnostics?: string[] };

export function EpisodeControl({ canStart }: { canStart: boolean }) {
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [starting, setStarting] = useState(false);
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
  }, []);
  async function start() {
    revision.current += 1;
    setStarting(true); setErrors([]);
    try {
      const response = await fetch('/api/episode/start', { method: 'POST' });
      const result: Response = await response.json();
      setEpisode(result.episode);
      if (!response.ok || !result.accepted) setErrors(result.diagnostics ?? ['Episode start was rejected.']);
    } catch { setErrors(['Could not reach the service to start the Episode.']); }
    finally { revision.current += 1; setStarting(false); }
  }
  return <section className="import-panel" aria-label="Episode execution">
    <h2>Episode execution</h2>
    <p>Decision Provider: Baseline</p>
    <button disabled={!canStart || !connected || starting || episode?.state === 'running'} onClick={() => void start()}>Start Episode</button>
    <p aria-live="polite" aria-label="Episode status">{starting ? 'Starting Episode…' : !connected ? 'Connecting to Episode service…' : episode ? `${episode.state === 'running' ? '◷ Running' : episode.state === 'finished' ? `✓ ${episode.summary?.status}` : `⚠ ${episode.state}`} · ${episode.id}` : '○ Not started'}</p>
    <p className="hint">The local service runs independently of this browser. Plant and setup edits apply to the next Episode. Execution requires applied, valid configuration.</p>
    {errors.length > 0 && <ul role="alert">{errors.map((error, index) => <li key={index}>{error}</li>)}</ul>}
    {episode && <>
      <p>Frozen seed: {episode.seed} · Simulated time: {episode.simulated_time_ns} ns · Events processed: {episode.events_processed}</p>
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
