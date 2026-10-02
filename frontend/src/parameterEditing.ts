export type ParameterEdit = { kind: 'node' | 'route' | 'machine' | 'worker'; element_id: string; changes: Record<string, unknown>; operation_id?: string };

// Integer YAML durations are nanoseconds; strings may include units. Keep
// out-of-range integers as text for the authoritative Python validator.
export function integerOrText(value: string): number | string | null {
  if (!value.trim()) return null;
  if (/^-?\d+$/.test(value) && Number.isSafeInteger(Number(value))) return Number(value);
  return value;
}
