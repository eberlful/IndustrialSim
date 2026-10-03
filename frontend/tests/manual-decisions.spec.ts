import { test, expect } from '@playwright/test';

const model = `
episode: {end_condition: {type: max_time, max_time: 2s}}
production_plan: [{id: batch, variant: sedan, quantity: 1, release_time: 2s}]
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
workers: [{id: worker, qualifications: [operator]}]
decision_triggers:
  - {id: station-safe, trigger_type: safe_point, target_id: station, times_ns: [0], on_failure: abort}
  - {id: worker-safe, trigger_type: safe_point, target_id: worker, times_ns: [0], on_failure: abort}
`;

test('manual batch preserves rejected fields and applies one complete corrected proposal', async ({ page, context }) => {
  await page.goto('/');
  await page.getByLabel('YAML content', { exact: true }).fill(model);
  await page.getByRole('button', { name: 'Validate and import' }).click();
  await expect(page.getByRole('status')).toHaveText('✓ Model valid');
  await page.getByLabel('Decision mode', { exact: true }).selectOption('manual');
  await page.getByRole('button', { name: 'Start Episode', exact: true }).click();
  await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Awaiting decisions');
  const episode = (await (await context.request.get('/api/episode')).json()).episode;
  const batch = episode.decision_batch.batch;
  expect(typeof batch.time_ns).toBe('string');
  await expect(page.getByRole('group', { name: /station/ })).toBeVisible();
  await expect(page.getByRole('group', { name: /worker/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Continue Episode', exact: true })).toBeDisabled();
  const duration = page.getByRole('group', { name: /station/ }).getByLabel('duration ns', { exact: true });
  await duration.fill('-1');
  await page.getByRole('button', { name: 'Submit complete Decision Batch', exact: true }).click();
  await expect(page.getByLabel('Manual Decision Batch').getByRole('alert')).toContainText('greater than or equal to 0');
  await expect(duration).toHaveValue('-1');
  const unchanged = (await (await context.request.get('/api/episode')).json()).episode;
  expect(unchanged.simulated_time_ns).toBe(episode.simulated_time_ns);
  expect(unchanged.decision_batch.batch.batch_id).toBe(batch.batch_id);
  await duration.fill('0');
  const submission = page.waitForResponse(response => response.url().endsWith('/api/episode/submit-batch'));
  await page.getByRole('button', { name: 'Submit complete Decision Batch', exact: true }).click();
  expect((await (await submission).json()).accepted).toBe(true);
  await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Paused');
  const duplicate = await context.request.post('/api/episode/submit-batch', { data: {
    episode_id: episode.id, batch_id: batch.batch_id, actions: [],
  } });
  expect(duplicate.status()).toBe(409);
  await page.getByRole('button', { name: 'Continue Episode', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Outcome:', exact: false })).toBeVisible();
  const events = await context.request.get(`/api/episode/events?episode_id=${episode.id}&limit=500`);
  const records = (await events.json()).records;
  expect(records.filter((record: { event_type: string }) => record.event_type === 'decision_action')).toHaveLength(2);
  expect(records.find((record: { event_type: string; details: { action?: { action_type: string } } }) => record.event_type === 'decision_action' && record.details.action?.action_type === 'worker_reassignment').details.action.qualifications).toBeNull();
  expect(records.filter((record: { event_type: string }) => ['fallback', 'failure'].includes(record.event_type))).toHaveLength(0);
});
