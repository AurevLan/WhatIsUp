import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import { apiBaseUrl } from '../lib/serverConfig'
import api from '../api/client'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const accessToken = ref(localStorage.getItem('access_token') || null)

  const isAuthenticated = computed(() => !!accessToken.value)
  const isSuperadmin = computed(() => user.value?.is_superadmin ?? false)

  function _isTokenExpired(token) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      return payload.exp && payload.exp * 1000 < Date.now()
    } catch { return true }
  }

  async function _refreshAccess() {
    const refresh = localStorage.getItem('refresh_token')
    if (!refresh) return false
    try {
      const { data } = await axios.post(`${apiBaseUrl()}/auth/refresh`, { refresh_token: refresh })
      accessToken.value = data.access_token
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      return true
    } catch {
      return false
    }
  }

  async function init() {
    if (!accessToken.value && !localStorage.getItem('refresh_token')) return

    // If the stored access token has already expired, try to rotate it via
    // the refresh token BEFORE touching any endpoint. Only a failed refresh
    // (refresh expired / revoked / absent) should log the user out — a
    // stale-but-still-rotatable session must survive an app restart.
    if (!accessToken.value || _isTokenExpired(accessToken.value)) {
      const ok = await _refreshAccess()
      if (!ok) {
        await logout()
        return
      }
    }

    try {
      // Use the shared api client so the 401 interceptor picks up any
      // remaining edge cases (e.g. token revoked between refresh and /me).
      const { data } = await api.get('/auth/me')
      user.value = data
    } catch {
      await logout()
    }
  }

  async function login(email, password) {
    const form = new URLSearchParams({ username: email, password })
    const { data } = await axios.post(`${apiBaseUrl()}/auth/login`, form)
    accessToken.value = data.access_token
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)

    // Fetch user info
    const { data: me } = await axios.get(`${apiBaseUrl()}/auth/me`, {
      headers: { Authorization: `Bearer ${data.access_token}` },
    })
    user.value = me
  }

  async function logout() {
    const refresh = localStorage.getItem('refresh_token')
    if (refresh) {
      try {
        await axios.post(`${apiBaseUrl()}/auth/logout`, { refresh_token: refresh })
      } catch {}
    }
    user.value = null
    accessToken.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  return { user, accessToken, isAuthenticated, isSuperadmin, init, login, logout }
})
