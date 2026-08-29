<template>
  <BaseModal :title="isEdit ? t('discovery.edit_source') : t('discovery.add_source')" @close="$emit('close')">
    <form @submit.prevent="handleSubmit" class="space-y-4">
      <!-- Targeting mode: one probe, or a probe group (plan E, E-2). Immutable
           after creation — same posture as source_type below. -->
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.target_mode_label') }}</label>
        <div class="flex gap-4">
          <label class="flex items-center gap-1.5 text-sm text-(--text-2)">
            <input
              type="radio"
              value="probe"
              v-model="targetMode"
              :disabled="isEdit"
              class="w-4 h-4"
            />
            {{ t('discovery.target_probe_option') }}
          </label>
          <label class="flex items-center gap-1.5 text-sm text-(--text-2)">
            <input
              type="radio"
              value="group"
              v-model="targetMode"
              :disabled="isEdit"
              class="w-4 h-4"
            />
            {{ t('discovery.target_group_option') }}
          </label>
        </div>
      </div>

      <div v-if="targetMode === 'probe'">
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.probe_label') }} *</label>
        <select v-model="form.probe_id" class="input w-full" required :disabled="isEdit">
          <option value="" disabled>{{ t('discovery.probe_placeholder') }}</option>
          <option v-for="probe in probes" :key="probe.id" :value="probe.id">{{ probe.name }}</option>
        </select>
      </div>
      <div v-else>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.group_label') }} *</label>
        <p v-if="probeGroups.length === 0" class="text-xs text-(--warn)">{{ t('discovery.no_probe_groups') }}</p>
        <select v-else v-model="form.probe_group_id" class="input w-full" required :disabled="isEdit">
          <option value="" disabled>{{ t('discovery.group_placeholder') }}</option>
          <option v-for="group in probeGroups" :key="group.id" :value="group.id">{{ group.name }}</option>
        </select>
      </div>

      <!-- Capability gate: never a silently-empty source_type list -->
      <div v-if="!isEdit">
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.source_type_label') }} *</label>
        <p v-if="!targetId" class="text-xs text-(--text-3)">
          {{ targetMode === 'probe' ? t('discovery.pick_probe_first') : t('discovery.pick_group_first') }}
        </p>
        <p v-else-if="availableSourceTypes.length === 0" class="text-xs text-(--warn)">
          {{
            targetMode === 'probe'
              ? t('discovery.no_capabilities', { probe: selectedProbeName })
              : t('discovery.no_group_capabilities', { group: selectedGroupName })
          }}
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

      <!-- Execution hint for a group target — who actually runs the job. -->
      <p v-if="targetMode === 'group' && form.source_type" class="text-xs text-(--text-3)">
        {{ t(`discovery.group_hint_${form.source_type}`) }}
      </p>

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
  // plan E, E-2 — {id, name, capabilities, probe_count}[], visible groups.
  probeGroups: { type: Array, default: () => [] },
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

// plan E, E-2 — which kind of target this source names. Immutable once a
// source exists (the mode radios are disabled in edit mode), inferred from
// whichever id the existing source carries.
const targetMode = ref(props.source?.probe_group_id ? 'group' : 'probe')

const form = ref({
  probe_id: props.source?.probe_id || '',
  probe_group_id: props.source?.probe_group_id || '',
  source_type: props.source?.source_type || '',
  enabled: props.source ? props.source.enabled : true,
  ...paramsToForm(props.source),
})

const loading = ref(false)
const error = ref('')

// The id relevant to the current mode — used for the "pick a target first"
// gate and to look up the target's declared capabilities.
const targetId = computed(() =>
  targetMode.value === 'probe' ? form.value.probe_id : form.value.probe_group_id
)

const selectedProbeName = computed(
  () => props.probes.find((p) => p.id === form.value.probe_id)?.name || ''
)
const selectedGroupName = computed(
  () => props.probeGroups.find((g) => g.id === form.value.probe_group_id)?.name || ''
)

// Only source_type values the backend accepts AND the selected target
// declared runnable — a probe at its last heartbeat, or the union of its
// group's members — never a silently empty list when nothing was declared
// (plan D, D-3 §4 / plan E, E-2).
const KNOWN_SOURCE_TYPES = ['docker', 'port_scan', 'dns_zone']
const availableSourceTypes = computed(() => {
  const capabilities =
    targetMode.value === 'probe'
      ? props.probes.find((p) => p.id === form.value.probe_id)?.discovery_capabilities || []
      : props.probeGroups.find((g) => g.id === form.value.probe_group_id)?.capabilities || []
  return KNOWN_SOURCE_TYPES.filter((typ) => capabilities.includes(typ))
})

const canSubmit = computed(() => {
  if (!targetId.value || !form.value.source_type) return false
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
      // Targeting is locked in edit mode (the radios/selects above are
      // disabled) — never resend probe_id/probe_group_id, the server treats
      // either as a retargeting request (plan E, E-2).
      const { data } = await discoveryApi.sources.update(
        props.source.id,
        { params: buildParams(), enabled: form.value.enabled },
        { skipErrorToast: true }
      )
      emit('saved', data)
    } else {
      const payload = {
        source_type: form.value.source_type,
        params: buildParams(),
        enabled: form.value.enabled,
      }
      if (targetMode.value === 'probe') payload.probe_id = form.value.probe_id
      else payload.probe_group_id = form.value.probe_group_id
      const { data } = await discoveryApi.sources.create(payload, { skipErrorToast: true })
      emit('saved', data)
    }
  } catch (err) {
    error.value = err.response?.data?.detail || t('common.error')
  } finally {
    loading.value = false
  }
}
</script>
