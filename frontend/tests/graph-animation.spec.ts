import { expect, test, type Page } from '@playwright/test';
import { transportProgress } from '../src/TransportAnimation';
import type { Episode, LiveTransport, Model, Observation } from '../src/types';

const transport: LiveTransport = { id: 'order', unit_id: 'unit', route_id: 'chosen', source_node_id: 'source',
  target_node_id: 'station', pickup_time_ns: '0', arrival_time_ns: '10000000000' };
const graph: Model['graph'] = {
  nodes: [
    { id: 'source', kind: 'source', input_ports: [], output_ports: [{ id: 'out', direction: 'output', port_type: 'part' }] },
    { id: 'station', kind: 'station', input_ports: [{ id: 'in', direction: 'input', port_type: 'part' }],
      output_ports: [{ id: 'out', direction: 'output', port_type: 'part' }] },
  ],
  routes: [
    { id: 'other', source_node_id: 'source', source_port_id: 'out', target_node_id: 'station', target_port_id: 'in', transit_time: '10s' },
    { id: 'chosen', source_node_id: 'source', source_port_id: 'out', target_node_id: 'station', target_port_id: 'in', transit_time: '10s' },
    { id: 'back', source_node_id: 'station', source_port_id: 'out', target_node_id: 'station', target_port_id: 'in', transit_time: '10s' },
  ],
};
const model: Model = { name: 'Animation test', yaml: '', configuration: {}, graph, layout: { positions: {}, grouping: 'none' },
  plant: null, valid: true, graph_available: true, diagnostics: [] };

function observation(time = '0'): Observation {
  return { simulated_time_ns: time, graph, plant: null, transports: { order: transport },
    stations: { station: { id: 'station', occupancy: 0, unit_ids: [], busy: true, blocked: false } }, buffers: {},
    machines: {}, workers: {}, production_units: { unit: { id: 'unit', variant: 'part', state: 'in_transport',
      location: 'chosen', quality_state: null, process_step_index: 0, findings: [] } }, raw_metrics: {} };
}

function episode(truth = observation()): Episode {
  return { id: 'animation', state: 'running', step_delay_seconds: 1, provider: 'Baseline', mode: 'baseline',
    decision_batch: null, configuration: {}, restored_from: null, last_checkpoint: null, seed: '42', result_path: '',
    simulated_time_ns: truth.simulated_time_ns, events_processed: 0, wall_clock_seconds: 0, observation: truth,
    observation_views: { truth, available: { ...truth, transports: undefined, production_units: {},
      stations: { station: { id: 'station', occupancy: null, unit_ids: null, busy: null, blocked: null } }, requests: [] } },
    diagnostics: [], summary: null };
}

async function openGraph(page: Page) {
  let current = episode();
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const body = url.pathname === '/api/project' ? { project: '/test', model }
      : url.pathname === '/api/episode' ? { episode: current }
      : url.pathname.endsWith('/events') ? { records: [], next_cursor: 0, has_more: false }
      : url.pathname.endsWith('/checkpoints') ? { checkpoints: [] } : { results: [] };
    await route.fulfill({ json: body });
  });
  await page.goto('/');
  await expect(page.locator('.transport-marker circle')).toHaveAttribute('data-progress', '0');
  return (next: Episode) => { current = next; };
}

test('progress preserves large nanosecond values and handles boundaries and zero duration', () => {
  const huge = { ...transport, pickup_time_ns: '9007199254740993000', arrival_time_ns: '9007199254740993010' };
  expect(transportProgress(huge, '9007199254740993005')).toBe(0.5);
  expect(transportProgress(huge, '0')).toBe(0);
  expect(transportProgress(huge, huge.arrival_time_ns)).toBe(1);
  expect(transportProgress({ ...transport, arrival_time_ns: '0' }, '0')).toBe(1);
});

test('markers follow the chosen curve, smooth confirmed progress and stop between updates', async ({ page }) => {
  const update = await openGraph(page);
  const marker = page.getByRole('img', { name: 'Production Unit unit on Route chosen' });
  await expect(marker).toHaveCount(1);
  await expect(marker.locator('title')).toHaveText('unit');
  const edge = page.locator('.react-flow__edge').filter({ has: marker });
  expect(await edge.locator('.transport-marker path').getAttribute('d')).toBe(await edge.locator('.react-flow__edge-path').getAttribute('d'));
  await page.evaluate(() => {
    document.documentElement.setAttribute('data-samples', '[]');
    new MutationObserver(records => {
      const samples: number[] = JSON.parse(document.documentElement.getAttribute('data-samples')!);
      for (const record of records) if (record.target instanceof SVGCircleElement) samples.push(Number(record.target.getAttribute('data-progress')));
      document.documentElement.setAttribute('data-samples', JSON.stringify(samples));
    }).observe(document.querySelector('.transport-marker circle')!, { attributes: true, attributeFilter: ['data-progress'] });
  });
  update(episode(observation('5000000000')));
  await expect(marker).toHaveAttribute('data-progress', '0.5');
  const samples: number[] = JSON.parse((await page.locator('html').getAttribute('data-samples'))!);
  expect(samples.some(value => value > 0 && value < 0.5)).toBe(true);
  await page.clock.install();
  await page.clock.fastForward(1500);
  await expect(marker).toHaveAttribute('data-progress', '0.5');
  update(episode({ ...observation('10000000000'), transports: {}, production_units: {
    unit: { ...observation().production_units.unit, state: 'in_station', location: 'station' },
  } }));
  await page.clock.runFor(1000);
  await expect(marker).toHaveCount(0);
});

test('pause, view changes, blocked stations and terminal episodes clean up animation', async ({ page }) => {
  const update = await openGraph(page);
  const station = page.locator('.material-node.station');
  await expect(station).toHaveClass(/is-processing/);
  update({ ...episode(observation('5000000000')), state: 'paused' });
  await expect(page.locator('.transport-marker circle')).toHaveAttribute('data-progress', '0.5');
  await expect(station).not.toHaveClass(/is-processing/);
  update(episode(observation('5000000000')));
  await expect(station).toHaveClass(/is-processing/);
  update({ ...episode(observation('6000000000')), state: 'awaiting_decisions' });
  await expect(page.locator('.transport-marker circle')).toHaveAttribute('data-progress', '0.6');
  await expect(station).not.toHaveClass(/is-processing/);
  await page.getByRole('button', { name: 'Available observations', exact: true }).click();
  await expect(page.locator('.transport-marker')).toHaveCount(0);
  await page.getByRole('button', { name: 'Simulator truth', exact: true }).click();
  await expect(page.locator('.transport-marker circle')).toHaveAttribute('data-progress', '0.6');
  const blocked = observation('5000000000');
  blocked.stations.station.blocked = true;
  update(episode(blocked));
  await expect(station).toHaveClass(/is-blocked/);
  await expect(station).not.toHaveClass(/is-processing/);
  update({ ...episode(blocked), state: 'finished' });
  await expect(page.locator('.transport-marker')).toHaveCount(0);
  await expect(station).not.toHaveClass(/is-processing/);
});

test('reduced motion shows confirmed positions without pulsing, and missing units disappear', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const update = await openGraph(page);
  await expect(page.locator('.material-node.station')).not.toHaveClass(/is-processing/);
  update(episode(observation('7500000000')));
  await expect(page.locator('.transport-marker circle')).toHaveAttribute('data-progress', '0.75');
  update(episode({ ...observation('7500000000'), transports: {}, production_units: {} }));
  await expect(page.locator('.transport-marker')).toHaveCount(0);
});

test('backward/self routes and a new episode place new markers at their confirmed progress', async ({ page }) => {
  const update = await openGraph(page);
  const truth = observation('2500000000');
  truth.transports = { order: { ...transport, route_id: 'back', source_node_id: 'station' } };
  update({ ...episode(truth), id: 'new-episode' });
  const marker = page.getByRole('img', { name: 'Production Unit unit on Route back' });
  await expect(marker).toHaveAttribute('data-progress', '0.25');
  const edge = page.locator('.react-flow__edge').filter({ has: marker });
  expect(await edge.locator('.transport-marker path').getAttribute('d')).toBe(await edge.locator('.react-flow__edge-path').getAttribute('d'));
  await page.getByRole('button', { name: 'Draft graph', exact: true }).click();
  await expect(page.locator('.transport-marker')).toHaveCount(0);
  await expect(page.locator('.material-node.station')).not.toHaveClass(/is-processing/);
});

test('a transport completed between polls finishes its curve before the next transport continues', async ({ page }) => {
  const update = await openGraph(page);
  const truth = observation('10000000000');
  truth.transports = { next: { ...transport, id: 'next', route_id: 'back', source_node_id: 'station',
    pickup_time_ns: '10000000000', arrival_time_ns: '20000000000' } };
  truth.production_units.unit.location = 'back';
  update(episode(truth));
  await expect(page.getByRole('img', { name: 'Production Unit unit on Route back' })).toHaveAttribute('data-progress', '0');
  await expect(page.getByRole('img', { name: 'Production Unit unit on Route chosen' })).toHaveCount(0);
});
