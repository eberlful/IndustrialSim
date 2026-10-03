import { test, expect } from '@playwright/test';
import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('saved results reopen after service restart with metrics and Deadlock entity navigation', async ({ page, context }) => {
  const directory = mkdtempSync(join(tmpdir(), 'industrialsim-results-'));
  const python = process.env.INDUSTRIALSIM_PYTHON ?? '../.venv/bin/python';
  const seed = spawnSync(python, ['-c', `
import sys
from pathlib import Path
sys.path.insert(0, '../tests')
from test_saved_results import MODEL
from test_deadlock_simulation_e2e import BUFFER_CYCLE_YAML
from industrialsim.application import run_episode, EpisodeSession
root = Path(sys.argv[1]) / 'runs'
run_episode(MODEL, output_dir=root / 'completed')
run_episode(BUFFER_CYCLE_YAML, output_dir=root / 'deadlocked')
session = EpisodeSession(MODEL, output_dir=root / 'incomplete')
session.advance(max_events=1)
session.close()
`, directory]);
  expect(seed.status, seed.stderr.toString()).toBe(0);
  function files() {
    return Object.fromEntries(readdirSync(directory, { recursive: true, withFileTypes: true }).filter(entry => entry.isFile())
      .map(entry => { const file = join(entry.parentPath, entry.name); return [file, readFileSync(file).toString('base64')]; }));
  }
  const before = files();
  let child: ChildProcess | undefined;
  let logs = '';
  async function start() {
    child = spawn(python, ['tests/recovery_service.py', directory], { stdio: ['ignore', 'ignore', 'pipe'] });
    child.stderr?.on('data', data => { logs += data.toString(); });
    await expect.poll(async () => {
      if (child?.exitCode != null) throw new Error(logs);
      try { return (await context.request.get('http://127.0.0.1:18766/api/results')).status(); } catch { return 0; }
    }).toBe(200);
  }
  async function stop() {
    if (!child || child.exitCode != null) return;
    const service = child;
    await new Promise<void>(resolve => { service.once('exit', () => resolve()); service.kill('SIGTERM'); });
    child = undefined;
  }
  try {
    await start();
    await page.goto('http://127.0.0.1:18766');
    const saved = page.getByLabel('Saved Episode results', { exact: true });
    await saved.getByLabel('Saved Episode output', { exact: true }).selectOption('runs/completed');
    await saved.getByRole('button', { name: 'Open saved results', exact: true }).click();
    await expect(saved.getByLabel('Saved result status')).toContainText('✓ completed');
    await expect(saved).toContainText('good_output');
    await stop();
    await start();
    await page.reload();
    await expect(page.getByLabel('Episode status', { exact: true })).toContainText('Not started');
    await saved.getByLabel('Saved Episode output', { exact: true }).selectOption('runs/deadlocked');
    await saved.getByRole('button', { name: 'Open saved results', exact: true }).click();
    await expect(saved.getByLabel('Saved result status')).toContainText('⚠ deadlocked');
    const diagnosis = saved.getByLabel('Deadlock diagnosis', { exact: true });
    await saved.getByRole('button', { name: 'r-stB-sink', exact: true }).click();
    await expect(saved.getByLabel('Saved entity details')).toContainText('source_node_id');
    await diagnosis.getByRole('button').first().click();
    await expect(saved.getByLabel('Saved entity details')).toBeVisible();
    await diagnosis.getByText('Wait relationships, capacities and ownership', { exact: true }).click();
    await expect(diagnosis).toContainText('wait_edges');
    await saved.getByLabel('Saved Episode output', { exact: true }).selectOption('runs/incomplete');
    await saved.getByRole('button', { name: 'Open saved results', exact: true }).click();
    await expect(saved.getByLabel('Saved result status')).toContainText('incomplete');
    await expect(saved).toContainText('Final metrics unavailable.');
    expect(files()).toEqual(before);
  } finally { await stop(); rmSync(directory, { recursive: true, force: true }); }
});
