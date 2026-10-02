import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

const reference = readFileSync('../examples/reference_automotive_plant.yaml', 'utf8');

test('open and import a Plant, inspect topology, retain it after errors and reconnect', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Open model' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await expect(page.getByText('15 nodes · 16 routes', { exact: true })).toBeVisible();
  await expect(page.locator('.react-flow__node')).toHaveCount(15);
  await expect(page.locator('.react-flow__edge')).toHaveCount(16);
  await expect(page.getByText('Reference Automotive Plant', { exact: true })).toBeVisible();
  await expect(page.locator('.port').filter({ hasText: 'p-out · body' }).first()).toBeVisible();
  await page.locator('.react-flow__node').filter({ hasText: 'st-body-1' }).click();
  await expect(page.getByRole('heading', { name: 'st-body-1', exact: true })).toBeVisible();
  await expect(page.locator('aside pre').first()).toContainText('op-body-weld');

  await page.getByLabel('YAML file').setInputFiles({ name: 'imported-plant.yaml', mimeType: 'text/yaml', buffer: Buffer.from(reference) });
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByText('Loaded: imported-plant.yaml', { exact: true })).toBeVisible();
  await expect(page.locator('.react-flow__node')).toHaveCount(15);

  for (const [yaml, diagnostic] of [
    ['episode: [', 'YAML parsing error'],
    ['seed: 42', 'episode'],
    [reference.replace('hall_id: "hall-body-construction"', 'hall_id: "missing-hall"'), 'unknown hall'],
  ]) {
    await page.getByLabel('YAML content').fill(yaml);
    await page.getByRole('button', { name: 'Validate and import' }).click();
    await expect(page.getByRole('alert')).toContainText(diagnostic);
    await expect(page.getByRole('alert')).toContainText('Still displaying imported-plant.yaml');
    await expect(page.locator('.react-flow__node')).toHaveCount(15);
    await expect(page.locator('.react-flow__edge')).toHaveCount(16);
  }
  await page.reload();
  await expect(page.getByText('Loaded: imported-plant.yaml', { exact: true })).toBeVisible();
  await expect(page.locator('.react-flow__edge')).toHaveCount(16);
});

test('parallel routes and a self-cycle remain separate and selectable', async ({ page }) => {
  const yaml = JSON.stringify({
    episode: { end_condition: { type: 'all_units_terminal' } },
    production_units: [{ id: 'unit-1', variant: 'sedan', source_id: 'source' }],
    material_flow: {
      nodes: [
        { id: 'source', kind: 'source', output_ports: [{ id: 'out', direction: 'output', port_type: 'body' }] },
        { id: 'buffer', kind: 'buffer', capacity: 4,
          input_ports: [{ id: 'in', direction: 'input', port_type: 'body' }],
          output_ports: [{ id: 'out', direction: 'output', port_type: 'body' }] },
        { id: 'sink', kind: 'sink', input_ports: [{ id: 'in', direction: 'input', port_type: 'body' }] },
      ],
      routes: [
        { id: 'primary', source_node_id: 'source', source_port_id: 'out', target_node_id: 'buffer', target_port_id: 'in', transit_time: '1s' },
        { id: 'alternative', source_node_id: 'source', source_port_id: 'out', target_node_id: 'buffer', target_port_id: 'in', transit_time: '2s' },
        { id: 'cycle', source_node_id: 'buffer', source_port_id: 'out', target_node_id: 'buffer', target_port_id: 'in', transit_time: '3s' },
        { id: 'exit', source_node_id: 'buffer', source_port_id: 'out', target_node_id: 'sink', target_port_id: 'in' },
      ],
    },
  });
  await page.goto('/');
  await page.getByLabel('YAML content').fill(yaml);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByText('3 nodes · 4 routes', { exact: true })).toBeVisible();
  await expect(page.locator('.react-flow__edge')).toHaveCount(4);
  for (const name of ['primary', 'alternative', 'cycle']) {
    await page.getByText(name, { exact: true }).click();
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await expect(page.locator('aside pre').first()).toContainText('transit_time');
  }
});
