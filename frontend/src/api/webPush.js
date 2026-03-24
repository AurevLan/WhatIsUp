import api from './client'

export const webPushApi = {
  getPublicKey: () => api.get('/push/vapid-public-key'),
  getSubscription: () => api.get('/push/subscription'),
  subscribe: (sub) => api.post('/push/subscription', sub),
  unsubscribe: () => api.delete('/push/subscription'),
  test: () => api.post('/push/subscription/test'),
}
