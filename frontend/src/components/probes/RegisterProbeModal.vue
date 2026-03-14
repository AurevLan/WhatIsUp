<template>
  <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
    <div class="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-md p-6">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-lg font-semibold text-white">{{ t('probes.add') }}</h2>
        <button @click="$emit('close')" class="text-gray-400 hover:text-white">✕</button>
      </div>

      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('probes.name_label') }} *</label>
          <input v-model="form.name" class="input w-full" :placeholder="t('probes.name_placeholder')" required />
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('probes.location') }} *</label>
          <div class="flex gap-2">
            <input v-model="form.location_name" class="input flex-1" :placeholder="t('probes.address_placeholder')" required />
            <button type="button" @click="geocode" :disabled="geocoding || !form.location_name"
              class="btn-secondary text-xs flex items-center gap-1.5 shrink-0">
              <span v-if="geocoding" class="animate-spin text-base">⏳</span>
              <span v-else>📍</span>
              {{ geocoding ? t('probes.locating') : t('probes.locate_btn') }}
            </button>
          </div>
          <div v-if="geoResult" class="text-xs text-emerald-400 flex items-center gap-1 mt-1">
            ✓ {{ geoResult.display_name_short }} — {{ form.latitude }}°, {{ form.longitude }}°
          </div>
          <div v-if="geoError" class="text-xs text-red-400 mt-1">{{ geoError }}</div>
        </div>

        <details class="mt-1">
          <summary class="text-xs text-gray-500 cursor-pointer select-none hover:text-gray-400">{{ t('probes.manual_coordinates') }}</summary>
          <div class="grid grid-cols-2 gap-3 mt-2">
            <div>
              <label class="block text-xs text-gray-400 mb-1">{{ t('probes.latitude') }}</label>
              <input v-model.number="form.latitude" type="number" step="0.0001" min="-90" max="90" class="input w-full" placeholder="48.8566" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">{{ t('probes.longitude') }}</label>
              <input v-model.number="form.longitude" type="number" step="0.0001" min="-180" max="180" class="input w-full" placeholder="2.3522" />
            </div>
          </div>
        </details>

        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('probes.network_type') }}</label>
          <select v-model="form.network_type" class="input w-full">
            <option value="external">🌐 {{ t('probes.network_external') }}</option>
            <option value="internal">🏢 {{ t('probes.network_internal') }}</option>
          </select>
          <p class="text-xs text-gray-500 mt-1">
            {{ t('probes.network_type_hint') }}
          </p>
        </div>

        <div v-if="error" class="bg-red-900/40 border border-red-700 rounded p-3 text-sm text-red-300">
          {{ error }}
        </div>

        <div class="flex gap-3 pt-2">
          <button type="button" @click="$emit('close')" class="flex-1 px-4 py-2 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-800">{{ t('common.cancel') }}</button>
          <button type="submit" :disabled="loading" class="flex-1 btn-primary">
            {{ loading ? t('probes.registering') : t('probes.register') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { probesApi } from '../../api/probes'

const { t } = useI18n()
const emit = defineEmits(['close', 'registered'])
const form = ref({
  name: '',
  location_name: '',
  latitude: null,
  longitude: null,
  network_type: 'external',
})
const loading = ref(false)
const error = ref('')

const geocoding = ref(false)
const geoResult = ref(null)
const geoError = ref(null)

async function geocode() {
  if (!form.value.location_name) return
  geocoding.value = true
  geoResult.value = null
  geoError.value = null
  try {
    const params = new URLSearchParams({
      q: form.value.location_name,
      format: 'json',
      limit: '1',
      addressdetails: '0',
    })
    const res = await fetch(`https://nominatim.openstreetmap.org/search?${params}`, {
      headers: { 'Accept-Language': 'fr', 'User-Agent': 'WhatIsUp/1.0' },
    })
    const data = await res.json()
    if (!data.length) {
      geoError.value = t('probes.geocode_error')
      return
    }
    form.value.latitude = parseFloat(parseFloat(data[0].lat).toFixed(4))
    form.value.longitude = parseFloat(parseFloat(data[0].lon).toFixed(4))
    geoResult.value = {
      display_name_short: data[0].display_name.split(',').slice(0, 2).join(',').trim(),
    }
  } catch (e) {
    geoError.value = t('probes.geocode_network_error')
  } finally {
    geocoding.value = false
  }
}

async function handleSubmit() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await probesApi.register(form.value)
    emit('registered', data)
  } catch (err) {
    error.value = err.response?.data?.detail || t('common.error')
  } finally {
    loading.value = false
  }
}
</script>
