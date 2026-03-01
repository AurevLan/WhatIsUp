<template>
  <router-view />
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from './stores/auth'
import { useWebSocketStore } from './stores/websocket'

const auth = useAuthStore()
const ws = useWebSocketStore()

onMounted(async () => {
  await auth.init()
  if (auth.isAuthenticated) {
    ws.connect()
  }
})
</script>
