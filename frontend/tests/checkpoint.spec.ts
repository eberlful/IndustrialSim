import { test, expect } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const model = `
episode: {end_condition: {type: all_units_terminal}}
production_plan: [{id: batch, variant: sedan, quantity: 2, release_time: 1s}]
stations: [{id: original, operations: [{id: op, duration: 1s}]}]
decision_triggers: [{id: safe, trigger_type: safe_point, target_id: original, times_ns: [0]}]
`;

test('durable manual Checkpoint restores explicitly after a backend restart into new artifacts', async ({ page, context }) => {
  const directory = mkdtempSync(join(tmpdir(), 'industrialsim-recovery-'));
  let service: ChildProcess | undefined;
  let logs = '';
  const url = 'http://127.0.0.1:18766';
  async function start() {
    const python = process.env.INDUSTRIALSIM_PYTHON ?? '../.venv/bin/python';
    service = spawn(python, ['tests/recovery_service.py', directory], { stdio: ['ignore', 'ignore', 'pipe'] });
    service.stderr?.on('data', data => { logs += data.toString(); });
    await expect.poll(async () => {
      if (service?.exitCode != null) throw new Error(logs);
      try { return (await context.request.get(`${url}/api/episode`)).status(); } catch { return 0; }
    }).toBe(200);
  }
  async function stop() {
    if (!service || service.exitCode != null) return;
    const child = service;
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('Service did not stop')); }, 5000);
      child.once('exit', () => { clearTimeout(timer); resolve(); });
      child.kill('SIGTERM');
    });
    service = undefined;
  }
  function files(path: string): Record<string, string> {
    return Object.fromEntries(readdirSync(path, { recursive: true, withFileTypes: true }).filter(entry => entry.isFile())
      .map(entry => { const file = join(entry.parentPath, entry.name); return [file, readFileSync(file).toString('base64')]; }));
  }
  try {
    await start();
    await page.goto(url);
    await page.getByLabel('YAML content', { exact: true }).fill(model);
    await page.getByRole('button', { name: 'Validate and import' }).click();
    await expect(page.getByRole('status')).toHaveText('✓ Model valid');
    await page.getByLabel('Decision mode', { exact: true }).selectOption('manual');
    await page.getByLabel('Playback speed', { exact: true }).selectOption('0');
    await page.getByRole('button', { name: 'Start Episode', exact: true }).click();
    await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Awaiting decisions');
    const original = (await (await context.request.get(`${url}/api/episode`)).json()).episode;
    const response = page.waitForResponse(response => response.url().endsWith('/api/episode/checkpoint'));
    await page.getByRole('button', { name: 'Create Checkpoint', exact: true }).click();
    const saved = await (await response).json();
    expect(saved.accepted).toBe(true);
    await expect(page.getByLabel('Created Checkpoint')).toContainText(original.id);
    expect(JSON.parse(readFileSync(join(directory, saved.checkpoint.path), 'utf8')).checkpoint.domain_state.decision_coordinator).toBeTruthy();
    await stop();
    const previous = files(join(directory, original.result_path));
    await start();
    await page.reload();
    await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Not started');
    expect((await (await context.request.get(`${url}/api/episode`)).json()).episode).toBeNull();
    await page.getByLabel('YAML content', { exact: true }).fill(model.replaceAll('original', 'newer'));
    await page.getByRole('button', { name: 'Validate and import' }).click();
    await expect(page.getByRole('status')).toHaveText('✓ Model valid');
    await page.getByLabel('Saved Checkpoint', { exact: true }).selectOption(saved.checkpoint.path);
    await page.getByRole('button', { name: 'Restore Checkpoint', exact: true }).click();
    await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Awaiting decisions');
    await expect(page.getByLabel('Checkpoint provenance')).toContainText(original.id);
    await expect(page.locator('.material-node strong')).toHaveText(['original']);
    await page.getByText('Inspect Episode configuration', { exact: true }).click();
    await expect(page.getByLabel('Frozen Episode configuration')).toContainText('"id": "original"');
    const restored = (await (await context.request.get(`${url}/api/episode`)).json()).episode;
    expect(restored.id).not.toBe(original.id);
    expect(restored.decision_batch).toEqual(original.decision_batch);
    const stale = await context.request.post(`${url}/api/episode/submit-batch`, { data: {
      episode_id: original.id, batch_id: original.decision_batch.batch.batch_id, actions: [],
    } });
    expect(stale.status()).toBe(409);
    await page.getByRole('button', { name: 'Submit complete Decision Batch', exact: true }).click();
    await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Paused');
    await page.getByRole('button', { name: 'Continue Episode', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Outcome:', exact: false })).toBeVisible();
    const manifest = JSON.parse(readFileSync(join(directory, restored.result_path, 'manifest.json'), 'utf8'));
    expect(manifest.parent_run_id).toBe(original.id);
    expect(manifest.checkpoint_hash).toBe(saved.checkpoint.checkpoint_hash);
    expect(manifest.status).toBe('completed');
    expect(files(join(directory, original.result_path))).toEqual(previous);
    expect(files(join(directory, original.result_path))).not.toHaveProperty(join(directory, original.result_path, 'summary.json'));
  } finally {
    await stop();
    rmSync(directory, { recursive: true, force: true });
  }
});
