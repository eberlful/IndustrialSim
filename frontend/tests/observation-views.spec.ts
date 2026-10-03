import { test, expect } from '@playwright/test';

const model = `
episode: {end_condition: {type: max_time, max_time: 3s}}
production_plan: [{id: batch, variant: sedan, quantity: 1, release_time: 2s}]
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
machines: [{id: machine, initial_health: 0.75}]
decision_triggers:
  - {id: machine-safe, trigger_type: safe_point, target_id: machine, times_ns: [0]}
  - {id: station-safe, trigger_type: safe_point, target_id: station, times_ns: [0]}
`;

test('switching views preserves provider input and exposes only contracted entity details', async ({ page, context }) => {
  await page.goto('/');
  await page.getByLabel('YAML content', { exact: true }).fill(model);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByLabel('Decision mode', { exact: true }).selectOption('manual');
  await page.getByRole('button', { name: 'Start Episode', exact: true }).click();
  await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Awaiting decisions');
  const before = (await (await context.request.get('/api/episode')).json()).episode;
  await expect(page.getByLabel('Active observation view')).toContainText('Simulator truth');
  await page.getByLabel('Live resource', { exact: true }).selectOption('machines:machine');
  await expect(page.getByLabel('Resource state')).toContainText('"capacity": 1');
  await page.getByRole('button', { name: 'Available observations', exact: true }).click();
  await expect(page.getByLabel('Active observation view')).toContainText('Available observations');
  await expect(page.getByRole('button', { name: 'Available observations', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByLabel('Resource state')).toContainText('"health": 0.75');
  await expect(page.getByLabel('Resource state')).toContainText('"capacity": "Unavailable"');
  await expect(page.getByLabel('Available Decision Request observations').locator('details')).toHaveCount(2);
  await page.locator('.material-node').filter({ has: page.getByText('station', { exact: true }) }).click();
  await expect(page.getByLabel('Resource state')).toContainText('"occupancy": "Unavailable"');
  await expect(page.locator('.material-node').filter({ has: page.getByText('station', { exact: true }) })).toContainText('Occupancy: Unavailable');
  const after = (await (await context.request.get('/api/episode')).json()).episode;
  expect(after.decision_batch).toEqual(before.decision_batch);
  expect(after.simulated_time_ns).toBe(before.simulated_time_ns);
  await page.getByRole('button', { name: 'Simulator truth', exact: true }).click();
  await expect(page.getByLabel('Resource state')).toContainText('"occupancy": 0');
  await page.getByRole('button', { name: 'Submit complete Decision Batch', exact: true }).click();
  await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Paused');
  await page.getByRole('button', { name: 'Available observations', exact: true }).click();
  await expect(page.getByText('No current observation contract. Dynamic observations are unavailable.', { exact: true })).toBeVisible();
  await page.getByLabel('Live resource', { exact: true }).selectOption('machines:machine');
  await expect(page.getByLabel('Resource state')).toContainText('"health": "Unavailable"');
  await page.getByRole('button', { name: 'Continue Episode', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Outcome:', exact: false })).toBeVisible();
});


test('Routing request keeps observed Production Unit details visible across views', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('YAML content', { exact: true }).fill(`
episode: {end_condition: {type: all_units_terminal}}
production_units: [{id: unit, variant: sedan, source_id: source}]
material_flow:
  nodes:
    - {id: source, kind: source, output_ports: [{id: out, direction: output, port_type: body}]}
    - {id: sink, kind: sink, input_ports: [{id: in, direction: input, port_type: body}]}
  routes:
    - {id: route, source_node_id: source, source_port_id: out, target_node_id: sink, target_port_id: in, transit_time: 1s}
decision_triggers:
  - {id: route-choice, trigger_type: routing_decision, node_id: source}
`);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByLabel('Decision mode', { exact: true }).selectOption('manual');
  await page.getByRole('button', { name: 'Start Episode', exact: true }).click();
  await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Awaiting decisions');
  await page.getByLabel('Live Production Unit', { exact: true }).selectOption('unit');
  await expect(page.getByLabel('Production Unit details')).toContainText('"variant": "sedan"');
  await page.getByRole('button', { name: 'Available observations', exact: true }).click();
  await expect(page.getByLabel('Production Unit details')).toContainText('"variant": "sedan"');
  await expect(page.getByLabel('Production Unit details')).toContainText('"location": "source"');
  await expect(page.getByLabel('Production Unit details')).toContainText('"quality_state": "Unavailable"');
  await page.getByRole('button', { name: 'Submit complete Decision Batch', exact: true }).click();
  await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Paused');
  await expect(page.getByText('Selected Production Unit observations: Unavailable', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Continue Episode', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Outcome:', exact: false })).toBeVisible();
});
