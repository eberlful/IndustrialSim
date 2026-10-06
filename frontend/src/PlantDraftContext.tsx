import { createContext, useContext, useState, useSyncExternalStore } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { PlantDraft } from './plantDraft';

export const PlantDraftContext = createContext<PlantDraft | null>(null);
export function usePlantDraft() {
  const [draft] = useState(() => new PlantDraft((url, init) => fetch(url, init)));
  const state = useSyncExternalStore(draft.subscribe, draft.snapshot);
  return { draft, ...state };
}
function useDraft() {
  const draft = useContext(PlantDraftContext);
  if (!draft) throw new Error('Plant form requires its draft owner');
  useSyncExternalStore(draft.subscribe, draft.snapshot);
  return draft;
}
export function useDraftField<T>(id: string, name: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const draft = useDraft();
  return [draft.field(id, name, initial), update => draft.editField(id, name, initial, update)];
}
export function useDraftForm(id: string) {
  const draft = useDraft();
  return { apply: (operation: () => Promise<boolean>) => draft.apply(id, operation) };
}
export function DiscardForm({ id }: { id: string }) {
  const draft = useDraft();
  return <button type="button" disabled={draft.snapshot().busy || !draft.isDirty(id)} onClick={() => draft.discard(id)}>Discard form changes</button>;
}
