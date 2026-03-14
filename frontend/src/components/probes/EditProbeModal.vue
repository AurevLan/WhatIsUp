<template>
  <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
    <div class="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-md p-6">
      <h2 class="text-lg font-semibold text-white mb-6">{{ t('probes.edit_title') }}</h2>

      <form @submit.prevent="save" class="space-y-4">
        <div>
          <label class="block text-xs text-gray-400 mb-1">{{ t('probes.location_label') }}</label>
          <div class="flex gap-2">
            <input v-model="form.location_name" type="text" required
              class="input flex-1" :placeholder="t('probes.location_placeholder')" />
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
              <input v-model.number="form.latitude" type="number" step="0.0001"
                min="-90" max="90" class="input w-full" placeholder="48.8566" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">{{ t('probes.longitude') }}</label>
              <input v-model.number="form.longitude" type="number" step="0.0001"
                min="-180" max="180" class="input w-full" placeholder="2.3522" />
            </div>
          </div>
        </details>

        <div>
          <label class="block text-xs text-gray-400 mb-1">{{ t('probes.network_type') }}</label>
          <select v-model="form.network_type" class="input w-full">
            <option value="external">🌐 {{ t('probes.network_external') }}</option>
            <option value="internal">🏢 {{ t('probes.network_internal') }}</option>
          </select>
          <p class="text-xs text-gray-500 mt-1">
            {{ t('probes.network_type_hint') }}
          </p>
        </div>

        <p v-if="error" class="text-red-400 text-sm">{{ error }}</p>

        <div class="flex gap-3 pt-2">
          <button type="submit" :disabled="saving" class="btn-primary flex-1">
            {{ saving ? t('probes.saving') : t('probes.save') }}
          </button>
          <button type="button" @click="$emit('close')" class="btn-secondary flex-1">
            {{ t('common.cancel') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { probesApi } from '../../api/probes'

const { t } = useI18n()

const props = defineProps({
  probe: { type: Object, required: true },
})
const emit = defineEmits(['close', 'updated'])

const saving = ref(false)
const error = ref(null)

const geocoding = ref(false)
const geoResult = ref(null)
const geoError = ref(null)

const form = reactive({
  location_name: props.probe.location_name ?? '',
  latitude: props.probe.latitude ?? null,
  longitude: props.probe.longitude ?? null,
  network_type: props.probe.network_type ?? 'external',
})

async function geocode() {
  if (!form.location_name) return
  geocoding.value = true
  geoResult.value = null
  geoError.value = null
  try {
    const params = new URLSearchParams({
      q: form.location_name,
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
    form.latitude = parseFloat(parseFloat(data[0].lat).toFixed(4))
    form.longitude = parseFloat(parseFloat(data[0].lon).toFixed(4))
    geoResult.value = {
      display_name_short: data[0].display_name.split(',').slice(0, 2).join(',').trim(),
    }
  } catch (e) {
    geoError.value = t('probes.geocode_network_error')
  } finally {
    geocoding.value = false
  }
}

async function save() {
  saving.value = true
  error.value = null
  try {
    const payload = {
      location_name: form.location_name || undefined,
      latitude: form.latitude !== '' && form.latitude !== null ? Number(form.latitude) : null,
      longitude: form.longitude !== '' && form.longitude !== null ? Number(form.longitude) : null,
      network_type: form.network_type,
    }
    const { data } = await probesApi.update(props.probe.id, payload)
    emit('updated', data)
  } catch (e) {
    error.value = e.response?.data?.detail ?? t('common.error')
  } finally {
    saving.value = false
  }
}
</script>
