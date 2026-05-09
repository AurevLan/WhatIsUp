<template>
  <ErrorBoundary>
    <router-view />
  </ErrorBoundary>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from './stores/auth'
import { useWebSocketStore } from './stores/websocket'
import ErrorBoundary from './components/shared/ErrorBoundary.vue'

const auth = useAuthStore()
const ws = useWebSocketStore()

onMounted(async () => {
  await auth.init()
  if (auth.isAuthenticated) {
    ws.connect()
  }
})
</script>
