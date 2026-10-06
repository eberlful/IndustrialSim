import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

const reference = readFileSync('../examples/reference_automotive_plant.yaml', 'utf8');

test('element changes retain multiple pending forms and discard only the selected form', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('YAML content', { exact: true }).fill(reference);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  const buffer = page.locator('.react-flow__node').filter({ hasText: 'buf-body-out' });
  await buffer.click();
  await page.getByLabel('Buffer capacity', { exact: true }).fill('8');
  await page.getByLabel('Resource definition').selectOption('machine:m-body-welder-1');
  await page.getByLabel('Resource capacity', { exact: true }).fill('2');
  await expect(page.getByRole('button', { name: 'Open model', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Validate and import', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Start Episode', exact: true })).toBeDisabled();
  await buffer.click();
  await expect(page.getByLabel('Buffer capacity', { exact: true })).toHaveValue('8');
  await page.getByRole('button', { name: 'Apply parameters', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save YAML', exact: true })).toBeDisabled();
  await page.getByLabel('Resource definition').selectOption('machine:m-body-welder-1');
  await expect(page.getByLabel('Resource capacity', { exact: true })).toHaveValue('2');
  await page.getByRole('region', { name: 'Properties', exact: true }).getByRole('button', { name: 'Discard form changes', exact: true }).click();
  await expect(page.getByLabel('Resource capacity', { exact: true })).toHaveValue('1');
  await expect(page.getByRole('button', { name: 'Save YAML', exact: true })).toBeEnabled();
  await buffer.click();
  await expect(page.getByLabel('Buffer capacity', { exact: true })).toHaveValue('8');
  await page.getByLabel('Buffer capacity', { exact: true }).fill('9');
  await page.getByRole('button', { name: 'Discard all form changes', exact: true }).click();
  await expect(page.getByLabel('Buffer capacity', { exact: true })).toHaveValue('8');
});

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

test('move, group, undo and reopen a separately saved layout', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Project model').selectOption('reference.yaml');
  await page.getByRole('button', { name: 'Open model', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByLabel('Display grouping').selectOption('hall');
  await expect(page.locator('.display-group-label').filter({ hasText: 'Hall:' }).first()).toBeVisible();
  await expect(page.locator('.react-flow__edge')).toHaveCount(16);
  const node = page.locator('.react-flow__node-plant').filter({ hasText: 'st-body-1' });
  const companion = page.locator('.react-flow__node-plant').filter({ hasText: 'st-body-2' });
  await node.locator('small').first().click();
  await companion.locator('small').first().click({ modifiers: ['Control'] });
  await expect(page.locator('.react-flow__node-plant.selected')).toHaveCount(2);
  const companionBefore = await companion.evaluate(element => getComputedStyle(element).transform);
  const before = await node.evaluate(element => getComputedStyle(element).transform);
  await expect(page.getByRole('button', { name: 'Save layout', exact: true })).toBeEnabled();
  const box = await node.locator('small').first().boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width / 2 + 70, box!.y + box!.height / 2 + 40, { steps: 12 });
  await page.mouse.up();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await expect(node).not.toHaveCSS('transform', before!);
  const moved = await node.evaluate(element => getComputedStyle(element).transform);
  await expect(companion).not.toHaveCSS('transform', companionBefore!);
  const companionMoved = await companion.evaluate(element => getComputedStyle(element).transform);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(node).toHaveCSS('transform', before!);
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect(node).toHaveCSS('transform', moved!);
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.reload();
  await page.getByLabel('Project model').selectOption('reference.yaml');
  await page.getByRole('button', { name: 'Open model', exact: true }).click();
  await expect(page.getByLabel('Display grouping')).toHaveValue('hall');
  await expect(node).toHaveCSS('transform', moved!);
  await expect(companion).toHaveCSS('transform', companionMoved!);
  await expect(page.locator('.react-flow__edge')).toHaveCount(16);
  await page.getByLabel('Display grouping').selectOption('area');
  await expect(page.locator('.display-group-label').filter({ hasText: 'Area:' }).first()).toBeVisible();
  await expect(page.locator('.react-flow__edge')).toHaveCount(16);
});

test('save an unconnected Station draft, reopen, connect and export', async ({ page }) => {
  const yaml = `
seed: 42
episode:
  end_condition: {type: all_units_terminal}
production_units: [{id: unit-1, variant: sedan, source_id: source}]
material_flow:
  nodes:
    - id: source
      kind: source
      output_ports: [{id: out, direction: output, port_type: body}]
    - id: sink
      kind: sink
      input_ports: [{id: in, direction: input, port_type: body}]
  routes:
    - {id: direct, source_node_id: source, source_port_id: out, target_node_id: sink, target_port_id: in, transit_time: 3s}
`;
  await page.goto('/');
  await page.getByLabel('YAML content').fill(yaml);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByLabel('New node ID').fill('new-station');
  await page.getByLabel('Node type').selectOption('station');
  await page.getByRole('button', { name: 'Add node', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('⚠ Draft invalid');
  await expect(page.getByRole('alert')).toContainText('new-station');
  await expect(page.getByRole('alert')).toContainText('disconnected');
  await expect(page.getByRole('button', { name: 'Download YAML' })).toBeDisabled();
  await page.getByLabel('Draft filename').fill('unfinished-station.json');
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByText('Draft saved: unfinished-station.json', { exact: true })).toBeVisible();
  // Leave the draft before reopening it from disk, rather than just reconnecting.
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.reload();
  await page.getByLabel('Saved draft').selectOption('unfinished-station.json');
  await page.getByRole('button', { name: 'Open draft', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('⚠ Draft invalid');
  await expect(page.getByRole('alert')).toContainText('new-station');
  await expect(page.locator('.react-flow__node-plant')).toHaveCount(3);
  await page.getByText('Create directed route', { exact: true }).click();
  const editor = page.getByRole('region', { name: 'Graph editing' });
  await editor.getByLabel('New route ID').fill('incoming');
  await editor.getByLabel('Source node').selectOption('source');
  await editor.getByLabel('Target node').selectOption('new-station');
  await editor.getByRole('button', { name: 'Add route', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('⚠ Draft invalid');
  await editor.getByLabel('New route ID').fill('outgoing');
  await editor.getByLabel('Source node').selectOption('new-station');
  await editor.getByLabel('Target node').selectOption('sink');
  await editor.getByRole('button', { name: 'Add route', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await expect(page.locator('.react-flow__edge')).toHaveCount(3);
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download YAML' }).click();
  const download = await downloading;
  const exported = readFileSync((await download.path())!, 'utf8');
  expect(exported).toContain('new-station');
  expect(exported).toContain('transit_time: 3s');
  await page.getByLabel('YAML content').fill(exported);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await expect(page.locator('.react-flow__node-plant')).toHaveCount(3);
  await page.locator('.react-flow__node-plant').filter({ hasText: 'new-station' }).locator('small').first().click();
  const ports = page.getByRole('form', { name: 'Typed Ports' });
  await ports.getByLabel('Port type', { exact: true }).first().fill('painted-body');
  await ports.getByRole('button', { name: 'Apply Ports', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('⚠ Draft invalid');
  await expect(page.getByLabel('Selected element diagnostics')).toContainText('Incompatible port types');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByRole('button', { name: 'Delete node', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('⚠ Draft invalid');
  await expect(page.getByRole('alert')).toContainText('incoming');
  await expect(page.getByRole('alert')).toContainText('missing node');
  await page.getByText('All routes (3)', { exact: true }).click();
  await editor.getByRole('button', { name: 'Inspect incoming', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'incoming', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
});

test('edit resources and Operation requirements, correct errors and reload saved YAML', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('YAML content').fill(reference);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await page.getByLabel('Resource definition').selectOption('machine:m-body-welder-1');
  await expect(page.getByLabel('Hall assignment')).toHaveCount(0);
  await page.getByLabel('Resource name').fill('Updated welder');
  await page.getByLabel('Resource capacity').fill('0');
  await page.getByRole('button', { name: 'Apply resource', exact: true }).click();
  await expect(page.getByLabel('Selected resource diagnostics')).toContainText('capacity');
  await expect(page.getByRole('button', { name: 'Download YAML' })).toBeDisabled();
  await page.getByLabel('Resource capacity').fill('2');
  await page.getByRole('button', { name: 'Apply resource', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByLabel('Resource definition').selectOption('worker:w-body-1');
  await page.getByLabel('Worker kind').selectOption('pool');
  await page.getByLabel('Resource capacity').fill('3');
  await page.getByLabel('Worker qualifications').fill('body_operator\nbackup,weld');
  await page.getByRole('button', { name: 'Apply resource', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.locator('.react-flow__node').filter({ hasText: 'st-body-1' }).click();
  const requirements = page.getByRole('form', { name: 'Resource requirements · op-body-weld' });
  await requirements.getByLabel('Required Machines').selectOption('m-body-welder-2');
  await requirements.getByLabel('Assigned Worker').selectOption('w-body-1');
  await requirements.getByLabel('Required qualification').fill('missing-qualification');
  await requirements.getByRole('button', { name: 'Apply requirements' }).click();
  await expect(page.getByLabel('Selected element diagnostics')).toContainText('missing-qualification');
  await expect(page.getByRole('button', { name: 'Save YAML', exact: true })).toBeDisabled();
  await requirements.getByLabel('Required qualification').fill('body_operator');
  await requirements.getByLabel('Worker count').fill('2');
  await requirements.getByRole('button', { name: 'Apply requirements' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('⚠ Draft invalid');
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByLabel('Save as project path').fill('resource-edits.yaml');
  await page.getByRole('button', { name: 'Save YAML', exact: true }).click();
  await expect(page.getByText('Saved: resource-edits.yaml', { exact: true })).toBeVisible();
  await page.reload();
  await page.getByLabel('Project model').selectOption('resource-edits.yaml');
  await page.getByRole('button', { name: 'Open model', exact: true }).click();
  await page.getByLabel('Resource definition').selectOption('machine:m-body-welder-1');
  await expect(page.getByLabel('Resource name')).toHaveValue('Updated welder');
  await expect(page.getByLabel('Resource capacity')).toHaveValue('2');
  await page.getByText('All resource properties', { exact: true }).click();
  await expect(page.getByRole('region', { name: 'Properties' })).toContainText('condition_threshold');
  await page.getByLabel('Resource definition').selectOption('worker:w-body-1');
  await expect(page.getByLabel('Worker kind')).toHaveValue('pool');
  await expect(page.getByLabel('Worker qualifications')).toHaveValue('body_operator\nbackup,weld');
  await page.locator('.react-flow__node').filter({ hasText: 'st-body-1' }).click();
  await expect(requirements.getByLabel('Required Machines')).toHaveValues(['m-body-welder-2']);
  await expect(requirements.getByLabel('Assigned Worker')).toHaveValue('w-body-1');
  await expect(requirements.getByLabel('Worker count')).toHaveValue('2');
});

test('resource forms preserve exact capacities and unchanged Worker counts', async ({ page }) => {
  const yaml = `
episode: {end_condition: {type: all_units_terminal}}
production_units: [{id: unit, variant: sedan}]
machines: [{id: machine, capacity: 9007199254740993}]
workers: [{id: worker, kind: pool, capacity: 9007199254740993, qualifications: [weld]}]
stations:
  - id: station
    operations:
      - id: weld
        duration: 1s
        required_workers: [{worker_id: worker, count: 9007199254740993}]
`;
  await page.goto('/');
  await page.getByLabel('YAML content').fill(yaml);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await page.getByLabel('Resource definition').selectOption('machine:machine');
  await expect(page.getByLabel('Resource capacity')).toHaveValue('9007199254740993');
  await page.getByLabel('Resource name').fill('Named machine');
  await page.getByRole('button', { name: 'Apply resource', exact: true }).click();
  await page.getByLabel('Resource definition').selectOption('worker:worker');
  await expect(page.getByLabel('Resource capacity')).toHaveValue('9007199254740993');
  await page.locator('.react-flow__node').filter({ hasText: 'station' }).click();
  await expect(page.getByLabel('Worker count')).toHaveValue('9007199254740993');
  await page.getByLabel('Required qualification').fill('weld');
  await page.getByRole('button', { name: 'Apply requirements', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download YAML' }).click();
  const exported = readFileSync((await (await downloading).path())!, 'utf8');
  expect(exported).toMatch(/count: '?9007199254740993'?(?:,|\n)/);
  expect(exported.match(/capacity: 9007199254740993/g)).toHaveLength(2);
});

test('blank resource capacities and Worker counts can be corrected to one', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('YAML content').fill(reference);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await page.getByLabel('Resource definition').selectOption('machine:m-body-welder-1');
  await page.getByLabel('Resource capacity').fill('');
  await page.getByRole('button', { name: 'Apply resource', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('⚠ Draft invalid');
  await expect(page.getByLabel('Resource capacity')).toHaveValue('');
  await page.getByLabel('Resource capacity').fill('1');
  await page.getByRole('button', { name: 'Apply resource', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.locator('.react-flow__node').filter({ hasText: 'st-body-1' }).click();
  await page.getByLabel('Worker count').fill('');
  await page.getByRole('button', { name: 'Apply requirements', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('⚠ Draft invalid');
  await expect(page.getByLabel('Worker count')).toHaveValue('');
  await page.getByLabel('Worker count').fill('1');
  await page.getByRole('button', { name: 'Apply requirements', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
});

test('advanced YAML shares the form draft, preserves invalid text and reloads exports', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('YAML content').fill(reference);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.locator('.react-flow__node').filter({ hasText: 'buf-body-out' }).click();
  await page.getByLabel('Buffer capacity').fill('8');
  await expect(page.getByRole('button', { name: 'YAML editor', exact: true })).toBeDisabled();
  await expect(page.getByText('Apply form changes before switching to YAML or saving.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save YAML', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Download YAML', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Apply parameters', exact: true }).click();
  await page.getByRole('button', { name: 'YAML editor', exact: true }).click();
  const editor = page.getByLabel('Advanced YAML content');
  const current = await editor.inputValue();
  expect(current).toContain('capacity: 8');
  for (const section of ['telemetry:', 'process_plans:', 'decision_triggers:', 'maintenance:']) expect(current).toContain(section);
  const advanced = current.replace('initial_health: 1.0', 'initial_health: 0.8');
  await editor.fill(advanced);
  // Switching to forms submits pending text first.
  await page.getByRole('button', { name: 'Visual editor', exact: true }).click();
  await page.getByLabel('Resource definition').selectOption('machine:m-body-welder-1');
  await page.getByText('All resource properties', { exact: true }).click();
  await expect(page.getByRole('region', { name: 'Properties' })).toContainText('0.8');
  await page.getByRole('button', { name: 'YAML editor', exact: true }).click();
  await expect(editor).toHaveValue(advanced);
  await editor.fill('episode: [');
  await page.getByLabel('Draft filename').fill('invalid-yaml.json');
  // Saving a draft also submits pending invalid text.
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByText('Draft saved: invalid-yaml.json', { exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('YAML parsing error');
  await expect(page.getByRole('button', { name: 'Download YAML' })).toBeDisabled();
  await page.getByRole('button', { name: 'Visual editor', exact: true }).click();
  await expect(page.getByText('Visual editing unavailable', { exact: true })).toBeVisible();
  await expect(page.locator('.react-flow__node')).toHaveCount(0);
  await page.reload();
  await expect(editor).toHaveValue('episode: [');
  await page.getByLabel('Saved draft').selectOption('invalid-yaml.json');
  await page.getByRole('button', { name: 'Open draft', exact: true }).click();
  await expect(editor).toHaveValue('episode: [');
  await editor.fill(advanced.replace('initial_health: 0.8', 'initial_health: 2.0'));
  await page.getByRole('button', { name: 'Apply YAML', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('initial_health');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(editor).toHaveValue('episode: [');
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect(editor).toHaveValue(/initial_health: 2.0/);
  await editor.fill(advanced);
  await page.getByLabel('Save as project path').fill('advanced-yaml.yaml');
  // Executable save validates and uses the pending corrected text.
  await page.getByRole('button', { name: 'Save YAML', exact: true }).click();
  await expect(page.getByText('Saved: advanced-yaml.yaml', { exact: true })).toBeVisible();
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download YAML' }).click();
  const exported = readFileSync((await (await downloading).path())!, 'utf8');
  expect(exported).toBe(advanced);
  await page.getByLabel('YAML content', { exact: true }).fill(exported);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await page.getByRole('button', { name: 'Visual editor', exact: true }).click();
  await page.locator('.react-flow__node').filter({ hasText: 'buf-body-out' }).click();
  await expect(page.getByLabel('Buffer capacity')).toHaveValue('8');
  await page.getByRole('button', { name: 'YAML editor', exact: true }).click();
  await expect(editor).toHaveValue(exported);
});
