// keyword/json_path merged into http as optional assertions (plan cap v2,
// 6f-2) — no longer distinct check_types.
export const CHECK_TYPES = ['http', 'tcp', 'dns', 'scenario', 'heartbeat']

export const CONDITIONS_BY_TYPE = {
  http: ['any_down', 'all_down', 'ssl_expiry', 'response_time_above', 'response_time_above_baseline', 'anomaly_detection', 'schema_drift'],
  tcp: ['any_down', 'all_down', 'response_time_above'],
  dns: ['any_down', 'all_down'],
  scenario: ['any_down', 'all_down', 'response_time_above'],
  heartbeat: ['any_down'],
}

export const THRESHOLD_CONDITIONS = new Set(['response_time_above', 'ssl_expiry'])

export function conditionsForCheckType(checkType) {
  return CONDITIONS_BY_TYPE[checkType] ?? CONDITIONS_BY_TYPE.http
}

export function needsThreshold(condition) {
  return THRESHOLD_CONDITIONS.has(condition)
}
