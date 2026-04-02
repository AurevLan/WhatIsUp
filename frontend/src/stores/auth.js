import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

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

  async function init() {
    if (accessToken.value) {
      if (_isTokenExpired(accessToken.value)) {
        logout()
        return
      }
      try {
        const { data } = await axios.get('/api/v1/auth/me', {
          headers: { Authorization: `Bearer ${accessToken.value}` },
        })
        user.value = data
      } catch {
        logout()
      }
    }
  }

  async function login(email, password) {
    const form = new URLSearchParams({ username: email, password })
    const { data } = await axios.post('/api/v1/auth/login', form)
    accessToken.value = data.access_token
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)

    // Fetch user info
    const { data: me } = await axios.get('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${data.access_token}` },
    })
    user.value = me
  }

  async function logout() {
    const refresh = localStorage.getItem('refresh_token')
    if (refresh) {
      try {
        await axios.post('/api/v1/auth/logout', { refresh_token: refresh })
      } catch {}
    }
    user.value = null
    accessToken.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  return { user, accessToken, isAuthenticated, isSuperadmin, init, login, logout }
})
