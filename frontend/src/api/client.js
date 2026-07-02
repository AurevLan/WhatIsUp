import axios from 'axios'
import router from '../router'
import { apiBaseUrl } from '../lib/serverConfig'
import { i18n } from '../i18n'
import { useToast } from '../composables/useToast'

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
      router.push('/login')
    }
    return Promise.reject(error)
  }
)

// Show a global error toast for every failed request, unless:
//   • the response status is 401 (handled above by the refresh / redirect flow)
//   • the caller opted out with { skipErrorToast: true } in the axios config
//   • the request was cancelled (axios.isCancel / ERR_CANCELED) — not a real error
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status

    if (status === 401) return Promise.reject(error)
    if (error.config?.skipErrorToast) return Promise.reject(error)
    if (
      (typeof axios.isCancel === 'function' && axios.isCancel(error)) ||
      error.code === 'ERR_CANCELED'
    ) {
      return Promise.reject(error)
    }

    const t = i18n.global.t
    const detail = error.response?.data?.detail
    let msg

    // Only surface the raw FastAPI detail for non-empty strings on < 500
    // responses — 5xx bodies aren't meant for end users and fall back to the
    // generic i18n key below.
    if (typeof detail === 'string' && detail.length > 0 && detail.length <= 200 && status < 500) {
      msg = detail
    } else if (!error.response) {
      msg = error.code === 'ECONNABORTED' ? t('errors.timeout') : t('errors.network')
    } else if (status >= 500) {
      msg = t('errors.server')
    } else {
      msg = t('errors.request')
    }

    useToast().error(msg)
    return Promise.reject(error)
  }
)

export default api
