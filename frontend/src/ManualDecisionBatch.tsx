import { useState } from 'react';
import type { DecisionSchema, Episode, EpisodeResponse, PendingDecisionBatch } from './types';

type Proposal = { actionType: string; values: Record<string, string | boolean> };
function fieldType(schema: DecisionSchema): string {
  return schema.type ?? schema.anyOf?.find(option => option.type !== 'null')?.type ?? 'string';
}
function proposalFor(pending: PendingDecisionBatch, targetId: string, actionType: string): Proposal {
  const suggestion = pending.suggested_actions.find(action => action.target_id === targetId && action.action_type === actionType);
  const values: Proposal['values'] = {};
  for (const [name, schema] of Object.entries(pending.action_schemas[actionType]?.properties ?? {})) {
    const value = suggestion?.[name] ?? schema.default;
    values[name] = value == null ? (!pending.action_schemas[actionType]?.required?.includes(name) ? '' : fieldType(schema) === 'object' ? '{}' : fieldType(schema) === 'array' ? '[]' : '')
      : typeof value === 'boolean' ? value : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
  }
  return { actionType, values };
}

export function ManualDecisionBatch({ episode, onSubmit }: { episode: Episode; onSubmit: (actions: Record<string, unknown>[]) => Promise<EpisodeResponse | undefined> }) {
  const pending = episode.decision_batch!;
  const requests = pending.batch.requests.filter((request, index, all) =>
    all.findIndex(other => other.target_id === request.target_id) === index);
  function applicableTypes(targetId: string): string[] {
    const related = pending.batch.requests.filter(request => request.target_id === targetId);
    return pending.action_types[related[0].request_id].filter(type =>
      related.every(request => pending.action_types[request.request_id].includes(type)));
  }
  const [proposals, setProposals] = useState<Proposal[]>(() => requests.map(request =>
    proposalFor(pending, request.target_id, applicableTypes(request.target_id)[0])));
  const [errors, setErrors] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  function edit(index: number, name: string, value: string | boolean) {
    setProposals(current => current.map((proposal, position) => position === index ? { ...proposal, values: { ...proposal.values, [name]: value } } : proposal));
  }
  async function submit() {
    setErrors([]);
    let actions: Record<string, unknown>[];
    try {
      actions = requests.map((request, index) => {
        const proposal = proposals[index];
        const schema = pending.action_schemas[proposal.actionType];
        if (!schema) throw new Error(`No supported action contract for ${request.request_id}.`);
        const action: Record<string, unknown> = { action_type: proposal.actionType, target_id: request.target_id, schema_version: '1.0' };
        for (const [name, field] of Object.entries(schema.properties ?? {})) {
          if (['action_type', 'target_id', 'schema_version'].includes(name)) continue;
          const value = proposal.values[name];
          if (value === '' && !schema.required?.includes(name)) continue;
          if (fieldType(field) === 'array' || fieldType(field) === 'object') {
            try { action[name] = JSON.parse(String(value)); }
            catch { throw new Error(`${request.target_id}: ${name.replaceAll('_', ' ')} must contain valid JSON.`); }
          } else action[name] = value;
        }
        return action;
      });
    } catch (error) { setErrors([error instanceof Error ? error.message : 'Could not build the complete proposal.']); return; }
    setSubmitting(true);
    try {
      const result = await onSubmit(actions);
      if (!result) throw new Error('Could not reach the Episode service.');
      if (!result.accepted) {
        const diagnostics = result.diagnostics ?? (Array.isArray(result.detail) ? result.detail : [result.detail ?? 'Decision Batch was rejected.']);
        setErrors(diagnostics.map(diagnostic => typeof diagnostic === 'string' ? diagnostic : diagnostic.message ?? diagnostic.msg ?? 'Invalid action'));
      }
    } catch { setErrors(['Could not reach the service. Read the current Episode state before retrying.']); }
    finally { setSubmitting(false); }
  }
  return <section className="import-panel manual-decisions" aria-label="Manual Decision Batch">
    <h2>Decision Batch {pending.batch.batch_id}</h2>
    <p>All {pending.batch.requests.length} requests share simulated time {String(pending.batch.time_ns)} ns. Time stays frozen until this batch is answered.</p>
    <p>Submit every request together. Rejected proposals remain editable and do not invoke fallback.</p>
    {requests.map((request, index) => {
      const proposal = proposals[index];
      const schema = pending.action_schemas[proposal.actionType];
      return <fieldset key={request.request_id} disabled={submitting}>
        <legend>{request.request_id} · {request.target_id}</legend>
        {pending.batch.requests.filter(related => related.target_id === request.target_id).map(related =>
          <details key={related.request_id}><summary>{related.request_id} · Decision Request and shared-boundary observation</summary><pre>{JSON.stringify(related, null, 2)}</pre></details>)}
        <label>Action type<select value={proposal.actionType ?? ''} onChange={event => setProposals(current => current.map((old, position) =>
          position === index ? proposalFor(pending, request.target_id, event.target.value) : old))}>
          {applicableTypes(request.target_id).map(actionType => <option key={actionType} value={actionType}>{actionType.replaceAll('_', ' ')}</option>)}
        </select></label>
        {!schema && <p role="alert">No supported action contract is available for this request.</p>}
        {Object.entries(schema?.properties ?? {}).filter(([name]) => !['action_type', 'target_id', 'schema_version'].includes(name)).map(([name, field]) => {
          const label = name.replaceAll('_', ' ');
          const type = fieldType(field);
          return <label key={name}>{label}{type === 'boolean'
            ? <input type="checkbox" checked={Boolean(proposal.values[name])} onChange={event => edit(index, name, event.target.checked)}/>
            : ['array', 'object'].includes(type)
              ? <textarea aria-label={label} value={String(proposal.values[name] ?? '')} onChange={event => edit(index, name, event.target.value)}/>
              : <input aria-label={label} type="text" inputMode={['integer', 'number'].includes(type) ? 'decimal' : undefined}
                value={String(proposal.values[name] ?? '')} onChange={event => edit(index, name, event.target.value)}/>}</label>;
        })}
      </fieldset>;
    })}
    {errors.length > 0 && <ul role="alert">{errors.map((error, index) => <li key={index}>{error}</li>)}</ul>}
    <button disabled={submitting || proposals.some(proposal => !pending.action_schemas[proposal.actionType])} onClick={() => void submit()}>Submit complete Decision Batch</button>
  </section>;
}
