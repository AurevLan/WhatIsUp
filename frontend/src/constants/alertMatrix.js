// Plan cap v2, 6f — the registry shrank from 10 members to 4: `any_down` and
// `all_down` merged into `availability` (a quorum setting, see
// AlertMatrix.vue's `quorum_ratio`), and `response_time_above` /
// `response_time_above_baseline` / `anomaly_detection` merged into
// `latency_anomaly` (a sensitivity mode). A matrix row is one-per-condition,
// so both merges are expressed as extra fields on a single row rather than
// two rows. Pushed-metric conditions (`metric_above`/`below`/`absent`) were
// cut entirely (C1) and never appear here.
//
// keyword/json_path merged into http as optional assertions (plan cap v2,
// 6f-2) — no longer distinct check_types, so `schema_drift` (which only ever
// applied to JSON responses) now hangs off `http`.
export const CHECK_TYPES = ['http', 'tcp', 'dns', 'scenario', 'heartbeat']

export const CONDITIONS_BY_TYPE = {
  http: ['availability', 'ssl_expiry', 'latency_anomaly', 'schema_drift'],
  tcp: ['availability', 'latency_anomaly'],
  dns: ['availability'],
  scenario: ['availability', 'latency_anomaly'],
  heartbeat: ['availability'],
}

export const THRESHOLD_CONDITIONS = new Set(['latency_anomaly', 'ssl_expiry'])

export function conditionsForCheckType(checkType) {
  return CONDITIONS_BY_TYPE[checkType] ?? CONDITIONS_BY_TYPE.http
}

export function needsThreshold(condition) {
  return THRESHOLD_CONDITIONS.has(condition)
}

// F4 — the merged `latency_anomaly` condition's sensitivity mode is inferred
// from which of threshold_value/baseline_factor/anomaly_zscore_threshold is
// set (services/conditions/latency.py). Mirrored here so the UI can offer an
// explicit mode picker instead of three ambiguous number fields.
export function latencyModeOf(row) {
  if (row.baseline_factor != null) return 'relative'
  if (row.anomaly_zscore_threshold != null) return 'statistical'
  return 'absolute'
}
