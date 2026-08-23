<template>
  <BaseModal :title="isEdit ? t('discovery.edit_source') : t('discovery.add_source')" @close="$emit('close')">
    <form @submit.prevent="handleSubmit" class="space-y-4">
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.probe_label') }} *</label>
        <select v-model="form.probe_id" class="input w-full" required :disabled="isEdit">
          <option value="" disabled>{{ t('discovery.probe_placeholder') }}</option>
          <option v-for="probe in probes" :key="probe.id" :value="probe.id">{{ probe.name }}</option>
        </select>
      </div>

      <!-- Capability gate: never a silently-empty source_type list -->
      <div v-if="!isEdit">
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.source_type_label') }} *</label>
        <p v-if="!form.probe_id" class="text-xs text-(--text-3)">{{ t('discovery.pick_probe_first') }}</p>
        <p v-else-if="availableSourceTypes.length === 0" class="text-xs text-(--warn)">
          {{ t('discovery.no_capabilities', { probe: selectedProbeName }) }}
        </p>
        <select v-else v-model="form.source_type" class="input w-full" required>
          <option value="" disabled>{{ t('discovery.source_type_placeholder') }}</option>
          <option v-for="typ in availableSourceTypes" :key="typ" :value="typ">
            {{ t(`discovery.source_type_${typ}`) }}
          </option>
        </select>
      </div>
      <div v-else>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.source_type_label') }}</label>
        <p class="text-sm text-(--text-1)">{{ t(`discovery.source_type_${form.source_type}`) }}</p>
      </div>

      <!-- Params: docker has none, port_scan needs cidr + ports, dns_zone needs zone + resolver -->
      <template v-if="form.source_type === 'port_scan'">
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.cidr_label') }} *</label>
          <input v-model="form.cidr" class="input w-full" placeholder="10.0.0.0/24" required />
          <p class="text-xs text-(--text-3) mt-1">{{ t('discovery.cidr_hint') }}</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.ports_label') }} *</label>
          <input v-model="form.portsText" class="input w-full" placeholder="22, 80, 443" required />
          <p class="text-xs text-(--text-3) mt-1">{{ t('discovery.ports_hint') }}</p>
        </div>
      </template>
      <template v-else-if="form.source_type === 'dns_zone'">
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.zone_label') }} *</label>
          <input v-model="form.zone" class="input w-full" placeholder="example.com" required />
          <p class="text-xs text-(--text-3) mt-1">{{ t('discovery.zone_hint') }}</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.resolver_label') }} *</label>
          <input v-model="form.resolver" class="input w-full" placeholder="203.0.113.10" required />
          <p class="text-xs text-(--text-3) mt-1">{{ t('discovery.resolver_hint') }}</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.record_types_label') }}</label>
          <div class="flex gap-4">
            <label v-for="rt in DNS_RECORD_TYPES" :key="rt" class="flex items-center gap-1.5 text-sm text-(--text-2)">
              <input type="checkbox" :value="rt" v-model="form.recordTypes" class="w-4 h-4 rounded border-(--border-hover)" />
              {{ rt }}
            </label>
          </div>
          <p class="text-xs text-(--text-3) mt-1">{{ t('discovery.record_types_hint') }}</p>
        </div>
      </template>
      <p v-else-if="form.source_type === 'docker'" class="text-xs text-(--text-3)">
        {{ t('discovery.docker_hint') }}
      </p>

      <label class="flex items-center gap-2 text-sm text-(--text-2)">
        <input v-model="form.enabled" type="checkbox" class="w-4 h-4 rounded border-(--border-hover)" />
        {{ t('discovery.enabled_label') }}
      </label>

      <div v-if="error" class="bg-[color-mix(in_srgb,var(--down)_10%,transparent)] border border-[color-mix(in_srgb,var(--down)_30%,transparent)] rounded p-3 text-sm text-(--down)">
        {{ error }}
      </div>

      <div class="flex gap-3 pt-2">
        <button type="button" @click="$emit('close')" class="btn-secondary flex-1">{{ t('common.cancel') }}</button>
        <button type="submit" :disabled="loading || !canSubmit" class="flex-1 btn-primary">
          {{ loading ? t('common.saving') : t('common.save') }}
        </button>
      </div>
    </form>
  </BaseModal>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { discoveryApi } from '../../api/discovery'
import BaseModal from '../BaseModal.vue'

const { t } = useI18n()

const props = defineProps({
  probes: { type: Array, default: () => [] },
  source: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved'])

const isEdit = computed(() => !!props.source)

// Fixed vocabulary, mirrors `schemas/discovery.py::_DNS_ZONE_RECORD_TYPES`.
const DNS_RECORD_TYPES = ['A', 'AAAA', 'CNAME']

function paramsToForm(source) {
  if (!source) return { cidr: '', portsText: '', zone: '', resolver: '', recordTypes: [...DNS_RECORD_TYPES] }
  return {
    cidr: source.params?.cidr || '',
    portsText: (source.params?.ports || []).join(', '),
    zone: source.params?.zone || '',
    resolver: source.params?.resolver || '',
    recordTypes: source.params?.record_types?.length ? source.params.record_types : [...DNS_RECORD_TYPES],
  }
}

const form = ref({
  probe_id: props.source?.probe_id || '',
  source_type: props.source?.source_type || '',
  enabled: props.source ? props.source.enabled : true,
  ...paramsToForm(props.source),
})

const loading = ref(false)
const error = ref('')

const selectedProbeName = computed(
  () => props.probes.find((p) => p.id === form.value.probe_id)?.name || ''
)

// Only source_type values the backend accepts AND the selected probe
// declared runnable at its last heartbeat — never a silently empty list
// when a probe declares nothing (plan D, D-3 §4).
const KNOWN_SOURCE_TYPES = ['docker', 'port_scan', 'dns_zone']
const availableSourceTypes = computed(() => {
  const probe = props.probes.find((p) => p.id === form.value.probe_id)
  const capabilities = probe?.discovery_capabilities || []
  return KNOWN_SOURCE_TYPES.filter((typ) => capabilities.includes(typ))
})

const canSubmit = computed(() => {
  if (!form.value.probe_id || !form.value.source_type) return false
  if (form.value.source_type === 'port_scan') {
    return Boolean(form.value.cidr && form.value.portsText)
  }
  if (form.value.source_type === 'dns_zone') {
    return Boolean(form.value.zone && form.value.resolver && form.value.recordTypes.length)
  }
  return true
})

function buildParams() {
  if (form.value.source_type === 'port_scan') {
    const ports = form.value.portsText
      .split(',')
      .map((p) => parseInt(p.trim(), 10))
      .filter((p) => Number.isFinite(p))
    return { cidr: form.value.cidr.trim(), ports }
  }
  if (form.value.source_type === 'dns_zone') {
    return {
      zone: form.value.zone.trim(),
      resolver: form.value.resolver.trim(),
      record_types: form.value.recordTypes,
    }
  }
  return {}
}

async function handleSubmit() {
  loading.value = true
  error.value = ''
  try {
    if (isEdit.value) {
      const { data } = await discoveryApi.sources.update(
        props.source.id,
        { probe_id: form.value.probe_id, params: buildParams(), enabled: form.value.enabled },
        { skipErrorToast: true }
      )
      emit('saved', data)
    } else {
      const { data } = await discoveryApi.sources.create(
        {
          probe_id: form.value.probe_id,
          source_type: form.value.source_type,
          params: buildParams(),
          enabled: form.value.enabled,
        },
        { skipErrorToast: true }
      )
      emit('saved', data)
    }
  } catch (err) {
    error.value = err.response?.data?.detail || t('common.error')
  } finally {
    loading.value = false
  }
}
</script>
