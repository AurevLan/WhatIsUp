<template>
  <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
    <div class="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-md p-6">
      <h2 class="text-lg font-semibold text-white mb-6">Modifier la sonde</h2>

      <form @submit.prevent="save" class="space-y-4">
        <div>
          <label class="block text-xs text-gray-400 mb-1">Nom affiché (location)</label>
          <input v-model="form.location_name" type="text" required
            class="input w-full" placeholder="ex. Paris — OVH" />
        </div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">Latitude</label>
          <input v-model.number="form.latitude" type="number" step="0.0001"
            min="-90" max="90" class="input w-full" placeholder="ex. 48.8566" />
        </div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">Longitude</label>
          <input v-model.number="form.longitude" type="number" step="0.0001"
            min="-180" max="180" class="input w-full" placeholder="ex. 2.3522" />
        </div>

        <p v-if="error" class="text-red-400 text-sm">{{ error }}</p>

        <div class="flex gap-3 pt-2">
          <button type="submit" :disabled="saving" class="btn-primary flex-1">
            {{ saving ? 'Sauvegarde…' : 'Sauvegarder' }}
          </button>
          <button type="button" @click="$emit('close')" class="btn-secondary flex-1">
            Annuler
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { probesApi } from '../../api/probes'

const props = defineProps({
  probe: { type: Object, required: true },
})
const emit = defineEmits(['close', 'updated'])

const saving = ref(false)
const error = ref(null)

const form = reactive({
  location_name: props.probe.location_name ?? '',
  latitude: props.probe.latitude ?? null,
  longitude: props.probe.longitude ?? null,
})

async function save() {
  saving.value = true
  error.value = null
  try {
    const payload = {
      location_name: form.location_name || undefined,
      latitude: form.latitude !== '' && form.latitude !== null ? Number(form.latitude) : null,
      longitude: form.longitude !== '' && form.longitude !== null ? Number(form.longitude) : null,
    }
    const { data } = await probesApi.update(props.probe.id, payload)
    emit('updated', data)
  } catch (e) {
    error.value = e.response?.data?.detail ?? 'Erreur lors de la sauvegarde'
  } finally {
    saving.value = false
  }
}
</script>
