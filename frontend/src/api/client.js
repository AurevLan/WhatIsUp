import axios from 'axios'
import { apiBaseUrl } from '../lib/serverConfig'

const api = axios.create({
  baseURL: apiBaseUrl(),
  timeout: 15000,
})

// Resolve baseURL on every request — it can change after the user updates
// the server URL from the setup screen without a full page reload.
api.interceptors.request.use((config) => {
  config.baseURL = apiBaseUrl()
  return config
})

// Attach access token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Singleton lock — prevents multiple concurrent 401s from each triggering
// an independent refresh call. All queued requests await the same promise.
let _refreshPromise = null

// Handle 401 — attempt token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        try {
          if (_refreshPromise) {
            await _refreshPromise
          } else {
            _refreshPromise = axios
              .post(`${apiBaseUrl()}/auth/refresh`, { refresh_token: refresh })
              .then(({ data }) => {
                localStorage.setItem('access_token', data.access_token)
                localStorage.setItem('refresh_token', data.refresh_token)
              })
              .finally(() => { _refreshPromise = null })
            await _refreshPromise
          }
          const newToken = localStorage.getItem('access_token')
          original.headers.Authorization = `Bearer ${newToken}`
          return api(original)
        } catch {
          // refresh failed — fall through to redirect
        }
      }
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
