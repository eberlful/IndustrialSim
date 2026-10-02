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

test('edit, undo validation, download and reload the authoritative draft', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('YAML content').fill(reference);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.locator('.react-flow__node').filter({ hasText: 'buf-body-out' }).click();
  await page.getByLabel('Buffer capacity').fill('0');
  await page.getByRole('button', { name: 'Apply parameters', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('⚠ Draft invalid');
  await expect(page.getByRole('alert')).toContainText('capacity');
  await expect(page.getByRole('button', { name: 'Download YAML' })).toBeDisabled();
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await expect(page.getByLabel('Buffer capacity')).toHaveValue('4');
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('⚠ Draft invalid');
  await page.getByLabel('Buffer capacity').fill('8');
  await page.getByRole('button', { name: 'Apply parameters', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download YAML' }).click();
  const download = await downloading;
  const file = await download.path();
  expect(file).not.toBeNull();
  const exported = readFileSync(file!, 'utf8');
  expect(exported).toContain('process_plans:');
  expect(exported).toContain('decision_triggers:');
  await page.getByLabel('Save as project path').fill('edited.yaml');
  await page.getByRole('button', { name: 'Save YAML', exact: true }).click();
  await expect(page.getByText('Saved: edited.yaml', { exact: true })).toBeVisible();
  await page.reload();
  await page.getByLabel('Project model').selectOption('edited.yaml');
  await page.getByRole('button', { name: 'Open model' }).click();
  await page.locator('.react-flow__node').filter({ hasText: 'buf-body-out' }).click();
  await expect(page.getByLabel('Buffer capacity')).toHaveValue('8');
  await page.getByLabel('YAML content').fill(exported);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await page.locator('.react-flow__node').filter({ hasText: 'buf-body-out' }).click();
  await expect(page.getByLabel('Buffer capacity')).toHaveValue('8');
});

test('route edit preserves exact transit time and capability names with commas', async ({ page }) => {
  const yaml = `
episode:
  end_condition: {type: all_units_terminal}
production_units: [{id: unit-1, variant: sedan}]
material_flow:
  nodes:
    - id: source
      kind: source
      output_ports: [{id: out, direction: output, port_type: body}]
    - id: sink
      kind: sink
      input_ports: [{id: in, direction: input, port_type: body}]
  routes:
    - id: exact-route
      source_node_id: source
      source_port_id: out
      target_node_id: sink
      target_port_id: in
      transit_time: 9007199254740993
      required_capabilities: ["lift,heavy"]
`;
  await page.goto('/');
  await page.getByLabel('YAML content').fill(yaml);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await page.getByRole('button', { name: 'exact-route', exact: true }).click();
  await expect(page.getByLabel('Transit time')).toHaveValue('9007199254740993');
  await page.getByLabel('Route capacity').fill('3');
  await page.getByRole('button', { name: 'Apply parameters', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download YAML' }).click();
  const download = await downloading;
  const exported = readFileSync((await download.path())!, 'utf8');
  expect(exported).toContain('transit_time: 9007199254740993');
  await page.getByLabel('YAML content').fill(exported);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await page.getByRole('button', { name: 'exact-route', exact: true }).click();
  await expect(page.getByLabel('Required capabilities')).toHaveValue('lift,heavy');
  await expect(page.getByLabel('Route capacity')).toHaveValue('3');
});
