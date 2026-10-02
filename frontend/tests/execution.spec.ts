import { test, expect } from '@playwright/test';

const model = `
episode: {end_condition: {type: all_units_terminal}}
production_plan: [{id: batch, variant: sedan, quantity: 2000}]
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
`;

test('start Baseline, reject a second start, close the browser page and reconnect to outcome', async ({ page, context }) => {
  await page.goto('/');
  await page.getByLabel('YAML content', { exact: true }).fill(model);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  const started = page.waitForResponse(response => response.url().endsWith('/api/episode/start'));
  await page.getByRole('button', { name: 'Start Episode', exact: true }).click();
  const episode = (await (await started).json()).episode;
  const duplicate = await context.request.post('/api/episode/start');
  expect(duplicate.status()).toBe(409);
  expect((await duplicate.json()).episode.id).toBe(episode.id);
  // Project API remains available while the worker owns the frozen model.
  const project = await context.request.get('/api/project');
  expect(project.ok()).toBeTruthy();
  await page.close();
  const reconnected = await context.newPage();
  await reconnected.goto('/');
  await expect(reconnected.getByLabel('Episode status', { exact: true })).toContainText(episode.id);
  await expect(reconnected.getByRole('heading', { name: 'Outcome: completed', exact: true })).toBeVisible({ timeout: 30000 });
  await expect(reconnected.getByText(`Result directory: ${episode.result_path}`, { exact: true })).toBeVisible();
  await expect(reconnected.getByLabel('Episode outcome')).toContainText('Result hash:');
  // Applied invalid drafts block start in the UI and at the authoritative HTTP gate.
  await reconnected.getByRole('form', { name: 'Episode setup' }).getByLabel('Seed', { exact: true }).fill('invalid');
  await reconnected.getByRole('button', { name: 'Apply Episode setup' }).click();
  await expect(reconnected.getByRole('button', { name: 'Start Episode', exact: true })).toBeDisabled();
  const invalid = await context.request.post('/api/episode/start');
  expect(invalid.status()).toBe(422);
  expect((await invalid.json()).episode.id).toBe(episode.id);
  await reconnected.close();
});

test('a delayed initial project read cannot replace imported Episode inputs', async ({ page, context }) => {
  await context.request.post('/api/project/import', { data: { yaml: model.replace('quantity: 2000', 'quantity: 1'), name: 'older.yaml' } });
  let release!: () => void;
  let captured!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const initialRead = new Promise<void>(resolve => { captured = resolve; });
  await page.route('**/api/project', async route => {
    const response = await route.fetch();
    captured();
    await held;
    await route.fulfill({ response });
  });
  await page.goto('/');
  await initialRead;
  await page.getByLabel('YAML content', { exact: true }).fill(model.replace('quantity: 2000', 'quantity: 1'));
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByText('Loaded: Imported YAML', { exact: true })).toBeVisible();
  const received = page.waitForResponse(response => response.url().endsWith('/api/project'));
  release();
  await received;
  await page.getByRole('button', { name: 'YAML editor', exact: true }).click();
  await expect(page.getByText('Loaded: Imported YAML', { exact: true })).toBeVisible();
});
