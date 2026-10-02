import { useState } from 'react';
import { integerOrText } from './parameterEditing';
import type { Model } from './types';

export type EpisodeInputs = {
  seed: number | string | null;
  episode: { end_condition: { type: 'max_time' | 'all_units_terminal'; max_time?: number | string | null } };
  production_plan: Record<string, unknown>[];
};
type Props = { model: Model; busy: boolean; edit: (changes: Record<string, unknown>) => Promise<void>; onDirty: () => void };
const text = (value: unknown) => value == null ? '' : String(value);

function Errors({ errors, label }: { errors: string[]; label: string }) {
  return errors.length > 0 && <ul className="field-errors" aria-label={label}>{errors.map((error, index) => <li key={index}>{error}</li>)}</ul>;
}

export function EpisodeSetup({ model, busy, edit, onDirty }: Props) {
  const inputs = model.episode_inputs!;
  const end = inputs.episode.end_condition;
  const [seed, setSeed] = useState(text(inputs.seed));
  const [duration, setDuration] = useState(text(end.max_time));
  return <form className="property-form" aria-label="Episode setup" onChangeCapture={onDirty} onSubmit={event => {
    event.preventDefault();
    const changes: Record<string, unknown> = {};
    if (seed !== text(inputs.seed)) changes.seed = integerOrText(seed);
    if (duration !== text(end.max_time)) changes.max_time = duration.trim() ? integerOrText(duration) : null;
    void edit(changes);
  }}>
    <label>Seed<input value={seed} disabled={busy} onChange={event => setSeed(event.target.value)}/></label>
    <Errors label="Seed diagnostics" errors={model.diagnostics.filter(error => error.startsWith('seed:'))}/>
    <label>Simulation duration<input value={duration} disabled={busy} onChange={event => setDuration(event.target.value)}/></label>
    <Errors label="Simulation duration diagnostics" errors={model.diagnostics.filter(error => error.startsWith('episode.end_condition'))}/>
    <p className="hint">End condition: {end.type}. {end.type === 'all_units_terminal' ? 'Ends when all Production Units are terminal; duration is an optional time limit.' : 'Ends at the configured time limit.'} Times accept integer nanoseconds or whole-number units such as 30s or 2h. The existing Episode start and warm-up times are preserved.</p>
    <button disabled={busy}>Apply Episode setup</button>
  </form>;
}

export function ProductionPlan({ model, busy, edit, onDirty }: Props) {
  const original = model.episode_inputs!.production_plan;
  const [rows, setRows] = useState(original.map(row => ({ ...row })));
  function change(index: number, field: string, value: unknown) {
    setRows(previous => previous.map((row, position) => position === index ? { ...row, [field]: value } : row));
  }
  return <section className="import-panel production-plan" aria-label="Production Plan editing">
    <h2>Production Plan</h2>
    <p>Planned releases are materialized as individually tracked Production Units before the Episode. Existing row IDs, source assignments and quality states are retained.</p>
    <form aria-label="Production Plan" onChangeCapture={onDirty} onClickCapture={event => {
      if (event.target instanceof HTMLElement && event.target.closest('button')?.type === 'button') onDirty();
    }} onSubmit={event => {
      event.preventDefault();
      const plan = rows.map((row, index) => {
        const result = { ...row };
        for (const field of ['release_time', 'quantity', 'due_date']) {
          if (row[field] !== undefined && row[field] !== original[index]?.[field]) {
            const value = text(row[field]);
            result[field] = field === 'due_date' && !value.trim() ? null : integerOrText(value) ?? '';
          }
        }
        return result;
      });
      void edit({ production_plan: plan });
    }}>
      <fieldset disabled={busy}>
        <div className="plan-scroll"><table><thead><tr><th>Row / ID</th><th>Release time</th><th>Product variant</th><th>Quantity</th><th>Due date (optional)</th><th>Actions / errors</th></tr></thead>
          <tbody>{rows.map((row, index) => <tr key={index}>
            <th scope="row">{index + 1}{row.id != null && <small> · {text(row.id)}</small>}</th>
            {['release_time', 'variant', 'quantity', 'due_date'].map(field => <td key={field}><input aria-label={`${({ release_time: 'Release time', variant: 'Product variant', quantity: 'Quantity', due_date: 'Due date' } as Record<string, string>)[field]} · row ${index + 1}`}
              value={text(row[field] === undefined ? (field === 'release_time' ? 0 : field === 'quantity' ? 1 : '') : row[field])} onChange={event => change(index, field, event.target.value)}/></td>)}
            <td><button type="button" onClick={() => setRows(previous => previous.filter((_, position) => position !== index))}>Remove row {index + 1}</button>
              <Errors label={`Production Plan row ${index + 1} diagnostics`} errors={model.diagnostics.filter(error => error.startsWith(`production_plan.${index}.`) || error.startsWith(`production_plan.${index}:`))}/></td>
          </tr>)}</tbody>
        </table></div>
        <button type="button" onClick={() => setRows(previous => [...previous, { variant: '', quantity: 1, release_time: 0 }])}>Add Production Plan row</button>
        <button>Apply Production Plan</button>
      </fieldset>
      <Errors label="Production Plan diagnostics" errors={model.diagnostics.filter(error => !error.startsWith('production_plan.') && (error.includes('production') || error.includes('Production') || error.includes('variant') || error.includes('source')))}/>
      <p className="hint">Times use integer nanoseconds or whole-number units. Explicit Production Units remain in the configuration; conflicting plan changes must be corrected in the YAML editor.</p>
    </form>
  </section>;
}
