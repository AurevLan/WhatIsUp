<template>
  <BaseModal :title="t('discovery.accept_title')" @close="$emit('close')">
    <div class="space-y-4">
      <div class="text-sm text-(--text-2)">
        <p class="font-mono text-xs text-(--text-3) mb-2">{{ service.normalized_target }}</p>
        <p>{{ t('discovery.accept_intro') }}</p>
      </div>

      <div v-if="service.suggested_group || service.suggested_tags?.length" class="text-xs text-(--text-3) space-y-1">
        <p v-if="service.suggested_group">{{ t('discovery.suggested_group') }}: <span class="text-(--text-2)">{{ service.suggested_group }}</span></p>
        <p v-if="service.suggested_tags?.length">{{ t('discovery.suggested_tags') }}: <span class="text-(--text-2)">{{ service.suggested_tags.join(', ') }}</span></p>
      </div>

      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('common.name') }}</label>
        <input v-model="form.name" class="input w-full" :placeholder="service.suggested_name" />
      </div>

      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.check_type') }}</label>
        <select v-model="form.check_type" class="input w-full">
          <option v-for="typ in CHECK_TYPE_OPTIONS" :key="typ" :value="typ">{{ typ }}</option>
        </select>
      </div>

      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('monitors.col_interval') }}</label>
        <input v-model.number="form.interval_seconds" type="number" min="5" max="86400" class="input w-full" />
      </div>

      <div v-if="error" class="bg-[color-mix(in_srgb,var(--down)_10%,transparent)] border border-[color-mix(in_srgb,var(--down)_30%,transparent)] rounded p-3 text-sm text-(--down)">
        {{ error }}
      </div>

      <div class="flex gap-3 pt-2">
        <button type="button" @click="$emit('close')" class="btn-secondary flex-1">{{ t('common.cancel') }}</button>
        <button type="button" :disabled="loading" @click="handleAccept" class="flex-1 btn-primary">
          {{ loading ? t('common.saving') : t('discovery.accept') }}
        </button>
      </div>
    </div>
  </BaseModal>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { discoveryApi } from '../../api/discovery'
import BaseModal from '../BaseModal.vue'

const { t } = useI18n()

const props = defineProps({
  service: { type: Object, required: true },
})
const emit = defineEmits(['close', 'accepted'])

// A curated subset of Monitor.check_type — every value the accept endpoint's
// schema accepts, minus the ones that don't make sense as an override for a
// bare network target discovery reports (keyword/json_path/scenario/
// heartbeat/composite need config discovery has no way to prefill).
const CHECK_TYPE_OPTIONS = ['http', 'tcp', 'udp', 'dns', 'smtp', 'ping', 'domain_expiry']

const form = ref({
  name: '',
  check_type: props.service.suggested_check_type,
  interval_seconds: 60,
})

const loading = ref(false)
const error = ref('')

async function handleAccept() {
  loading.value = true
  error.value = ''
  try {
    const payload = { interval_seconds: form.value.interval_seconds }
    if (form.value.name) payload.name = form.value.name
    if (form.value.check_type) payload.check_type = form.value.check_type
    const { data } = await discoveryApi.services.accept(props.service.id, payload, {
      skipErrorToast: true,
    })
    emit('accepted', data)
  } catch (err) {
    error.value = err.response?.data?.detail || t('common.error')
  } finally {
    loading.value = false
  }
}
</script>
