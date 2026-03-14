/**
 * Public status page API — no authentication required.
 * Uses plain axios (not the authenticated client) to avoid attaching JWT tokens.
 */
import axios from 'axios'

const publicHttp = axios.create({
  baseURL: '/api/v1/public',
  timeout: 15000,
})

export const publicApi = {
  /** Fetch page metadata (name, description). */
  getPage: (slug) => publicHttp.get(`/pages/${slug}`),

  /** Fetch monitors with current status and 90-day history. */
  getMonitors: (slug) => publicHttp.get(`/pages/${slug}/monitors`),

  /** Fetch enriched status (incidents_30d). */
  getStatus: (slug) => publicHttp.get(`/pages/${slug}/status`),

  /**
   * Subscribe an email to status page notifications.
   * @param {string} slug
   * @param {string} email
   */
  subscribe: (slug, email) =>
    publicHttp.post(`/pages/${slug}/subscribe`, { email }),

  /**
   * Unsubscribe via token (from email link).
   * @param {string} slug
   * @param {string} token
   */
  unsubscribe: (slug, token) =>
    publicHttp.get(`/pages/${slug}/unsubscribe`, { params: { token } }),
}
