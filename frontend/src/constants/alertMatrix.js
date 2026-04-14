export const CHECK_TYPES = ['http', 'tcp', 'dns', 'keyword', 'json_path', 'scenario', 'heartbeat']

export const CONDITIONS_BY_TYPE = {
  http: ['any_down', 'all_down', 'ssl_expiry', 'response_time_above', 'response_time_above_baseline', 'anomaly_detection'],
  tcp: ['any_down', 'all_down', 'response_time_above'],
  dns: ['any_down', 'all_down'],
  keyword: ['any_down', 'all_down'],
  json_path: ['any_down', 'all_down', 'schema_drift'],
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
