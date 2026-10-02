import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
const reference = readFileSync(new URL('../../examples/reference_automotive_plant.yaml', import.meta.url), 'utf8');

test('prepare Episode inputs, correct row errors and reopen saved setup', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('YAML content', { exact: true }).fill(reference);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  const setup = page.getByRole('form', { name: 'Episode setup' });
  await expect(setup.getByLabel('Seed', { exact: true })).toHaveValue('42');
  await setup.getByLabel('Seed', { exact: true }).fill('9007199254740993');
  await setup.getByLabel('Simulation duration', { exact: true }).fill('3h');
  await setup.getByRole('button', { name: 'Apply Episode setup' }).click();
  const plan = page.getByRole('form', { name: 'Production Plan' });
  await plan.getByLabel('Release time · row 1', { exact: true }).fill('1000000001');
  await plan.getByLabel('Quantity · row 1', { exact: true }).fill('0');
  await plan.getByRole('button', { name: 'Apply Production Plan' }).click();
  await expect(page.getByLabel('Production Plan row 1 diagnostics', { exact: true })).toContainText('quantity');
  await expect(page.getByRole('button', { name: 'Download YAML' })).toBeDisabled();
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await plan.getByLabel('Quantity · row 1', { exact: true }).fill('2');
  await plan.getByLabel('Due date · row 1', { exact: true }).fill('2h');
  await plan.getByRole('button', { name: 'Apply Production Plan' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByLabel('Save as project path').fill('episode-setup.yaml');
  await page.getByRole('button', { name: 'Save YAML', exact: true }).click();
  await expect(page.getByText('Saved: episode-setup.yaml', { exact: true })).toBeVisible();
  await page.reload();
  await page.getByLabel('Project model').selectOption('episode-setup.yaml');
  await page.getByRole('button', { name: 'Open model', exact: true }).click();
  await expect(setup.getByLabel('Seed', { exact: true })).toHaveValue('9007199254740993');
  await expect(setup.getByLabel('Simulation duration', { exact: true })).toHaveValue('3h');
  await expect(plan.getByLabel('Release time · row 1', { exact: true })).toHaveValue('1000000001');
  await expect(plan.getByLabel('Quantity · row 1', { exact: true })).toHaveValue('2');
  await expect(plan.getByLabel('Due date · row 1', { exact: true })).toHaveValue('2h');
});

test('setup errors gate export and plan rows can be added and removed', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('YAML content', { exact: true }).fill(`
episode: {end_condition: {type: all_units_terminal}}
production_plan: [{id: batch, variant: sedan, quantity: 1}]
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
`);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  const setup = page.getByRole('form', { name: 'Episode setup' });
  await setup.getByLabel('Seed', { exact: true }).fill('bad');
  await setup.getByRole('button', { name: 'Apply Episode setup' }).click();
  await expect(page.getByLabel('Seed diagnostics', { exact: true })).toContainText('seed');
  await expect(page.getByRole('button', { name: 'Download YAML' })).toBeDisabled();
  await setup.getByLabel('Seed', { exact: true }).fill('7');
  await setup.getByLabel('Simulation duration', { exact: true }).fill('0.5s');
  await setup.getByRole('button', { name: 'Apply Episode setup' }).click();
  await expect(page.getByLabel('Simulation duration diagnostics', { exact: true })).toContainText('Invalid duration');
  await setup.getByLabel('Simulation duration', { exact: true }).fill('');
  await setup.getByRole('button', { name: 'Apply Episode setup' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  const plan = page.getByRole('form', { name: 'Production Plan' });
  await plan.getByRole('button', { name: 'Add Production Plan row' }).click();
  await plan.getByLabel('Product variant · row 2', { exact: true }).fill('suv');
  await plan.getByLabel('Release time · row 2', { exact: true }).fill('9007199254740993');
  await plan.getByRole('button', { name: 'Apply Production Plan' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await plan.getByRole('button', { name: 'Remove row 1', exact: true }).click();
  await plan.getByRole('button', { name: 'Apply Production Plan' }).click();
  await expect(plan.getByLabel('Product variant · row 1', { exact: true })).toHaveValue('suv');
  await expect(plan.getByLabel('Release time · row 1', { exact: true })).toHaveValue('9007199254740993');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(plan.getByLabel('Product variant · row 1', { exact: true })).toHaveValue('sedan');
});

test('applying one preparation form preserves pending edits in the other and row defaults', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('YAML content', { exact: true }).fill(`
episode: {end_condition: {type: all_units_terminal}}
production_plan: [{variant: sedan, quantity: 2, release_time: 10}, {variant: suv}]
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
`);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  const setup = page.getByRole('form', { name: 'Episode setup' });
  const plan = page.getByRole('form', { name: 'Production Plan' });
  await plan.getByLabel('Quantity · row 1', { exact: true }).fill('3');
  await setup.getByLabel('Seed', { exact: true }).fill('7');
  await setup.getByRole('button', { name: 'Apply Episode setup' }).click();
  await expect(plan.getByLabel('Quantity · row 1', { exact: true })).toHaveValue('3');
  await expect(page.getByRole('button', { name: 'Save YAML', exact: true })).toBeDisabled();
  await setup.getByLabel('Seed', { exact: true }).fill('8');
  await plan.getByRole('button', { name: 'Apply Production Plan' }).click();
  await expect(setup.getByLabel('Seed', { exact: true })).toHaveValue('8');
  await expect(page.getByRole('button', { name: 'Download YAML' })).toBeDisabled();
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(setup.getByLabel('Seed', { exact: true })).toHaveValue('7');
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect(setup.getByLabel('Seed', { exact: true })).toHaveValue('7');
  await setup.getByLabel('Seed', { exact: true }).fill('8');
  await setup.getByRole('button', { name: 'Apply Episode setup' }).click();
  await plan.getByRole('button', { name: 'Remove row 1', exact: true }).click();
  await plan.getByRole('button', { name: 'Apply Production Plan' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await expect(plan.getByLabel('Product variant · row 1', { exact: true })).toHaveValue('suv');
  await expect(plan.getByLabel('Quantity · row 1', { exact: true })).toHaveValue('1');
  await expect(plan.getByLabel('Release time · row 1', { exact: true })).toHaveValue('0');
});
