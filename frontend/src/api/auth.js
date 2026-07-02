import api from './client.js'

// Two-factor (TOTP) + active session management endpoints.
// Login / refresh / logout themselves live in stores/auth.js (token plumbing).
export const authApi = {
  // TOTP enrolment & lifecycle (all require an authenticated session)
  totpSetup: (config = {}) => api.post('/auth/totp/setup', undefined, config),
  totpEnable: (code, config = {}) => api.post('/auth/totp/enable', { code }, config),
  totpDisable: (password, code, config = {}) => api.post('/auth/totp/disable', { password, code }, config),

  // MFA challenge during login — exchanges the short-lived mfa_token + code
  // for the real access/refresh token pair.
  totpVerify: (mfa_token, code) => api.post('/auth/totp/verify', { mfa_token, code }),

  // Active sessions
  sessionsList: (refresh_token, config = {}) => api.post('/auth/sessions/list', { refresh_token }, config),
  sessionRevoke: (id, config = {}) => api.delete(`/auth/sessions/${id}`, config),
  sessionsRevokeAll: (refresh_token, config = {}) => api.post('/auth/sessions/revoke-all', { refresh_token }, config),
}
