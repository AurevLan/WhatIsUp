import api from './client.js'

// Two-factor (TOTP) + active session management endpoints.
// Login / refresh / logout themselves live in stores/auth.js (token plumbing).
export const authApi = {
  // TOTP enrolment & lifecycle (all require an authenticated session)
  totpSetup: () => api.post('/auth/totp/setup'),
  totpEnable: (code) => api.post('/auth/totp/enable', { code }),
  totpDisable: (password, code) => api.post('/auth/totp/disable', { password, code }),

  // MFA challenge during login — exchanges the short-lived mfa_token + code
  // for the real access/refresh token pair.
  totpVerify: (mfa_token, code) => api.post('/auth/totp/verify', { mfa_token, code }),

  // Active sessions
  sessionsList: (refresh_token) => api.post('/auth/sessions/list', { refresh_token }),
  sessionRevoke: (id) => api.delete(`/auth/sessions/${id}`),
  sessionsRevokeAll: (refresh_token) => api.post('/auth/sessions/revoke-all', { refresh_token }),
}
