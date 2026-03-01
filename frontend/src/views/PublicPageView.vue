<template>
  <div class="min-h-screen bg-gray-950 p-8">
    <!-- Header -->
    <div class="max-w-4xl mx-auto">
      <div class="text-center mb-12">
        <h1 class="text-3xl font-bold text-white">{{ page?.name || 'Status Page' }}</h1>
        <p class="text-gray-400 mt-2">Real-time service status</p>
        <div class="mt-4 flex items-center justify-center gap-2">
          <span v-if="allUp" class="inline-flex items-center gap-2 text-emerald-400 font-medium">
            <span class="w-3 h-3 rounded-full bg-emerald-400"></span>
            All systems operational
          </span>
          <span v-else class="inline-flex items-center gap-2 text-red-400 font-medium">
            <span class="w-3 h-3 rounded-full bg-red-500 animate-pulse"></span>
            Service disruption detected
          </span>
        </div>
      </div>

      <!-- Monitor list -->
      <div class="space-y-3">
        <div v-for="m in monitors" :key="m.id" class="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="font-semibold text-white">{{ m.name }}</h3>
              <p class="text-sm text-gray-500 font-mono mt-0.5">{{ m.url }}</p>
            </div>
            <div class="text-right">
              <p class="text-lg font-bold"
                :class="m.uptime_24h >= 99 ? 'text-emerald-400' : m.uptime_24h >= 90 ? 'text-amber-400' : 'text-red-400'">
                {{ m.uptime_24h?.toFixed(3) ?? '—' }}%
              </p>
              <p class="text-xs text-gray-500">24h uptime</p>
            </div>
          </div>
          <div class="mt-3 flex items-center gap-2 text-xs text-gray-500" v-if="m.avg_response_time_ms">
            Avg response: {{ Math.round(m.avg_response_time_ms) }}ms
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="mt-16 text-center text-xs text-gray-600">
        Powered by <span class="text-gray-500">WhatIsUp</span> •
        Last updated: {{ lastUpdated }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const page = ref(null)
const monitors = ref([])
const lastUpdated = ref(new Date().toLocaleTimeString('fr-FR'))

const allUp = computed(() => monitors.value.every(m => m.uptime_24h >= 99))

onMounted(async () => {
  const slug = route.params.slug
  const [pageResp, monResp] = await Promise.all([
    axios.get(`/api/v1/public/pages/${slug}`),
    axios.get(`/api/v1/public/pages/${slug}/monitors`),
  ])
  page.value = pageResp.data
  monitors.value = monResp.data

  // Real-time via WebSocket (public endpoint)
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/public/${slug}`)
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'check_result') {
      lastUpdated.value = new Date().toLocaleTimeString('fr-FR')
    }
  }
})
</script>
