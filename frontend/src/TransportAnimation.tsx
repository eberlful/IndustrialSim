import { useEffect, useRef, useState } from 'react';
import type { LiveTransport, Observation } from './types';

export type DisplayTransport = LiveTransport & { progress: number; arriving?: boolean };

export function transportProgress(transport: LiveTransport, time: string): number {
  const start = BigInt(transport.pickup_time_ns);
  const end = BigInt(transport.arrival_time_ns);
  const now = BigInt(time);
  if (end <= start) return now >= end ? 1 : 0;
  if (now <= start) return 0;
  if (now >= end) return 1;
  return Number((now - start) * 1_000_000n / (end - start)) / 1_000_000;
}

export function useReducedMotion() {
  const [reduced, setReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const query = matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => setReduced(query.matches);
    change();
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);
  return reduced;
}

export function useDisplayTransports(observation: Observation | null | undefined, enabled: boolean, running: boolean) {
  const previous = useRef<Record<string, LiveTransport>>({});
  const [display, setDisplay] = useState<DisplayTransport[]>([]);
  useEffect(() => {
    const current = enabled ? observation?.transports ?? {} : {};
    const arrived = (transport: LiveTransport) => {
      const unit = observation?.production_units[transport.unit_id];
      return !!observation && BigInt(observation.simulated_time_ns) >= BigInt(transport.arrival_time_ns)
        && (unit?.location === transport.target_node_id || (unit?.location === 'terminal'
          && observation.graph.nodes.some(node => node.id === transport.target_node_id && node.kind === 'sink'))
          || Object.values(current).some(next => next.unit_id === transport.unit_id
            && next.source_node_id === transport.target_node_id
            && BigInt(next.pickup_time_ns) >= BigInt(transport.arrival_time_ns)));
    };
    const arrivals = Object.values(previous.current).filter(transport => !current[transport.id]
      && arrived(transport));
    previous.current = current;
    setDisplay(existing => [
      ...Object.values(current).map(transport => ({ ...transport, progress: transportProgress(transport, observation!.simulated_time_ns) })),
      ...(enabled && running ? [
        ...existing.filter(transport => transport.arriving && !current[transport.id]
          && arrived(transport)),
        ...arrivals.map(transport => ({ ...transport, progress: 1, arriving: true })),
      ] : []),
    ]);
  }, [observation, enabled, running]);
  const complete = (id: string) => setDisplay(current => current.filter(transport => transport.id !== id));
  return { transports: display, complete };
}

export function TransportMarker({ transport, path, running, reduced, onComplete }: {
  transport: DisplayTransport; path: string; running: boolean; reduced: boolean; onComplete: (id: string) => void;
}) {
  const curve = useRef<SVGPathElement>(null);
  const marker = useRef<SVGCircleElement>(null);
  const progress = useRef(transport.progress);
  const complete = useRef(onComplete);
  complete.current = onComplete;
  useEffect(() => {
    const svgPath = curve.current!;
    const circle = marker.current!;
    const length = svgPath.getTotalLength();
    const place = (value: number) => {
      progress.current = value;
      const point = svgPath.getPointAtLength(length * value);
      circle.setAttribute('cx', String(point.x));
      circle.setAttribute('cy', String(point.y));
      circle.setAttribute('data-progress', String(value));
    };
    let frame = 0;
    if (!running || reduced || progress.current === transport.progress) {
      place(transport.progress);
      if (transport.arriving) complete.current(transport.id);
    } else {
      const start = performance.now();
      const from = progress.current;
      const tick = (now: number) => {
        const fraction = Math.min(1, (now - start) / 300);
        place(from + (transport.progress - from) * fraction);
        if (fraction < 1) frame = requestAnimationFrame(tick);
        else if (transport.arriving) complete.current(transport.id);
      };
      place(from);
      frame = requestAnimationFrame(tick);
    }
    return () => cancelAnimationFrame(frame);
  }, [path, transport.progress, transport.arriving, transport.id, running, reduced]);
  return <g className="transport-marker" pointerEvents="none">
    <path ref={curve} d={path} fill="none" stroke="none" aria-hidden="true"/>
    <circle ref={marker} pointerEvents="all" r="6" fill="#174bc0" stroke="white" strokeWidth="2" role="img"
      aria-label={`Production Unit ${transport.unit_id} on Route ${transport.route_id}`}>
      <title>{transport.unit_id}</title>
    </circle>
  </g>;
}
