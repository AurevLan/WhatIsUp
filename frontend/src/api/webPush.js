import api from './client'

export const webPushApi = {
  getPublicKey: () => api.get('/push/vapid-public-key'),
  getSubscription: () => api.get('/push/subscription'),
  subscribe: (sub, config = {}) => api.post('/push/subscription', sub, config),
  unsubscribe: (config = {}) => api.delete('/push/subscription', config),
  test: () => api.post('/push/subscription/test'),
}
