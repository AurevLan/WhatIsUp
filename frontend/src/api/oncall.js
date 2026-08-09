import client from './client.js'

// Plan V2, B-4 — the UI half of on-call. The engine (B-1/B-2) has been running
// since v1.21.0; until now the only way to configure a rotation was to call
// these endpoints by hand.
export const oncallApi = {
  // Who is on duty right now, on every schedule the user can see. Drives both
  // the dashboard widget and the header of the schedules page.
  onCallNow: (config = {}) => client.get('/oncall/schedules/on-call-now', config),

  schedules: {
    list: () => client.get('/oncall/schedules/'),
    get: (id) => client.get(`/oncall/schedules/${id}`),
    create: (data) => client.post('/oncall/schedules/', data),
    update: (id, data) => client.patch(`/oncall/schedules/${id}`, data),
    remove: (id) => client.delete(`/oncall/schedules/${id}`),
    overrides: (id) => client.get(`/oncall/schedules/${id}/overrides`),
    addOverride: (id, data) => client.post(`/oncall/schedules/${id}/overrides`, data),
    removeOverride: (id, overrideId) =>
      client.delete(`/oncall/schedules/${id}/overrides/${overrideId}`),
  },

  policies: {
    list: () => client.get('/escalation-policies/'),
    get: (id) => client.get(`/escalation-policies/${id}`),
    create: (data) => client.post('/escalation-policies/', data),
    update: (id, data) => client.patch(`/escalation-policies/${id}`, data),
    remove: (id) => client.delete(`/escalation-policies/${id}`),
  },

  contacts: {
    list: () => client.get('/contacts/'),
    create: (data) => client.post('/contacts/', data),
    update: (id, data) => client.patch(`/contacts/${id}`, data),
    remove: (id) => client.delete(`/contacts/${id}`),
  },
}
