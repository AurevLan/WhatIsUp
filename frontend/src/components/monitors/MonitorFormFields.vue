<template>
  <!-- Check type selector -->
  <div>
    <label class="block text-sm font-medium text-(--text-2) mb-2">{{ t('create_monitor.check_type') }}</label>
    <div class="grid grid-cols-4 sm:grid-cols-6 gap-1">
      <button
        v-for="ct in checkTypes" :key="ct.value" type="button"
        @click="form.check_type = ct.value"
        class="py-2 px-1 rounded-lg border text-xs font-medium transition-colors text-center"
        :class="form.check_type === ct.value
          ? 'bg-(--accent-glow) border-(--accent-border) text-(--accent)'
          : 'border-(--border) text-(--text-2) hover:border-(--border-hover) hover:text-(--text-1)'"
      >
        <div class="text-base mb-0.5">{{ ct.icon }}</div>
        {{ ct.label }}
      </button>
    </div>
    <p class="text-xs text-(--text-3) mt-1.5">{{ currentType.description }}</p>
  </div>

  <!-- Name -->
  <div>
    <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('common.name') }} *</label>
    <input v-model="form.name" class="input w-full" :placeholder="currentType.namePlaceholder" required />
  </div>

  <!-- URL / Host field -->
  <div v-if="!TYPES_WITHOUT_TARGET.includes(form.check_type)">
    <label class="block text-sm font-medium text-(--text-2) mb-1">{{ currentType.urlLabel }} *</label>
    <input
      v-model="form.url"
      class="input w-full"
      :placeholder="currentType.urlPlaceholder"
      :type="HTTP_TYPES.includes(form.check_type) ? 'url' : 'text'"
      required
    />
  </div>

  <!-- Heartbeat options -->
  <template v-if="form.check_type === 'heartbeat'">
    <div>
      <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.heartbeat_slug') }} *</label>
      <input v-model="form.heartbeat_slug" class="input w-full" placeholder="mon-cron-backup"
        pattern="[a-z0-9\-]+" required />
      <!-- Le jeton n'existe qu'après création : la modale d'édition affiche
           l'URL de ping réelle, la création annonce qu'elle sera générée. -->
      <p v-if="form.heartbeat_token" class="text-xs text-(--text-3) mt-1">
        {{ t('create_monitor.heartbeat_ping_url') }}
        <code class="font-mono text-(--accent) break-all">POST /api/v1/ping/{{ form.heartbeat_token }}</code>
      </p>
      <p v-else class="text-xs text-(--text-3) mt-1">{{ t('create_monitor.heartbeat_slug_hint') }}</p>
    </div>
    <div class="grid grid-cols-2 gap-4">
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.heartbeat_interval') }} *</label>
        <input v-model.number="form.heartbeat_interval_seconds" type="number" min="60" class="input w-full"
          placeholder="86400" required />
      </div>
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.heartbeat_grace') }}</label>
        <input v-model.number="form.heartbeat_grace_seconds" type="number" min="30" class="input w-full"
          placeholder="300" />
      </div>
    </div>
  </template>

  <!-- TCP port -->
  <div v-if="form.check_type === 'tcp'">
    <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.port') }} *</label>
    <input v-model.number="form.tcp_port" class="input w-full" type="number" min="1" max="65535" placeholder="443" required />
  </div>

  <!-- UDP port -->
  <div v-if="form.check_type === 'udp'">
    <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.port') }} *</label>
    <input v-model.number="form.udp_port" class="input w-full" type="number" min="1" max="65535" placeholder="53" required />
    <p class="text-xs text-(--text-3) mt-1">{{ t('create_monitor.udp_hint') }}</p>
  </div>

  <!-- SMTP options -->
  <div v-if="form.check_type === 'smtp'" class="space-y-3">
    <div class="grid grid-cols-2 gap-4">
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.port') }}</label>
        <input v-model.number="form.smtp_port" class="input w-full" type="number" min="1" max="65535" placeholder="25" />
      </div>
      <div class="flex items-end pb-1">
        <div class="flex items-center gap-2">
          <input v-model="form.smtp_starttls" type="checkbox" id="smtp_starttls" />
          <label for="smtp_starttls" class="text-sm text-(--text-2)">STARTTLS</label>
        </div>
      </div>
    </div>
  </div>

  <!-- Domain expiry options -->
  <div v-if="form.check_type === 'domain_expiry'">
    <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.domain_expiry_threshold') }}</label>
    <input v-model.number="form.domain_expiry_warn_days" class="input w-full" type="number" min="1" max="365" placeholder="30" />
    <p class="text-xs text-(--text-3) mt-1">{{ t('create_monitor.domain_expiry_hint') }}</p>
  </div>

  <!-- DNS options -->
  <div v-if="form.check_type === 'dns'" class="space-y-4">
    <div class="grid grid-cols-2 gap-4">
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.dns_record_type') }}</label>
        <select v-model="form.dns_record_type" class="input w-full">
          <option v-for="r in DNS_RECORD_TYPES" :key="r" :value="r">{{ r }}</option>
        </select>
      </div>
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">
          {{ t('create_monitor.dns_expected_value') }} <span class="text-(--text-3)">({{ t('common.optional') }})</span>
        </label>
        <input v-model="form.dns_expected_value" class="input w-full" placeholder="1.2.3.4" />
      </div>
    </div>
    <div>
      <label class="block text-sm font-medium text-(--text-2) mb-1">
        {{ t('monitors.dns_nameservers.label') }} <span class="text-(--text-3)">({{ t('common.optional') }})</span>
      </label>
      <input v-model="form.dns_nameservers_raw" class="input w-full" :placeholder="t('monitors.dns_nameservers.placeholder')" />
      <p class="text-xs text-(--text-3) mt-1">{{ t('monitors.dns_nameservers.desc') }}</p>
    </div>
    <div class="rounded-lg border border-(--border) p-3 space-y-3">
      <p class="text-xs font-semibold text-(--text-2) uppercase tracking-wide">{{ t('monitors.dns_drift.label') }}</p>
      <div class="flex items-start gap-3">
        <input v-model="form.dns_drift_alert" type="checkbox" id="dns_drift_alert" class="mt-0.5" />
        <div>
          <label for="dns_drift_alert" class="text-sm text-(--text-2)">{{ t('monitors.dns_drift.label') }}</label>
          <p class="text-xs text-(--text-3)">{{ t('monitors.dns_drift.desc') }}</p>
        </div>
      </div>
      <div v-if="form.dns_drift_alert" class="flex items-start gap-3 pl-1">
        <input v-model="form.dns_split_enabled" type="checkbox" id="dns_split_enabled" class="mt-0.5" />
        <div>
          <label for="dns_split_enabled" class="text-sm text-(--text-2)">{{ t('monitors.dns_drift.split_horizon') }}</label>
          <p class="text-xs text-(--text-3)">{{ t('monitors.dns_drift.split_horizon_desc') }}</p>
        </div>
      </div>
    </div>
  </div>

  <!-- Composite options -->
  <div v-if="form.check_type === 'composite'" class="space-y-3">
    <div>
      <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('monitors.composite.aggregation') }}</label>
      <select v-model="form.composite_aggregation" class="input w-full">
        <option value="majority_up">{{ t('monitors.composite.aggregation_majority_up') }}</option>
        <option value="all_up">{{ t('monitors.composite.aggregation_all_up') }}</option>
        <option value="any_up">{{ t('monitors.composite.aggregation_any_up') }}</option>
        <option value="weighted_up">{{ t('monitors.composite.aggregation_weighted_up') }}</option>
      </select>
      <p class="text-xs text-(--text-3) mt-1">{{ t('monitors.composite.desc') }}</p>
    </div>
    <!-- À la création seulement : en édition, les membres se gèrent depuis la
         page de détail, l'astuce n'a plus lieu d'être. -->
    <p v-if="mode === 'create'" class="text-xs text-(--text-3) bg-(--bg-surface-2) rounded p-2">
      {{ t('create_monitor.composite_members_hint') }}
    </p>
  </div>

  <!-- Keyword options -->
  <div v-if="form.check_type === 'keyword'">
    <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.keyword_label') }} *</label>
    <input v-model="form.keyword" class="input w-full" placeholder="&quot;status&quot;: &quot;ok&quot;" required />
    <div class="flex items-center gap-2 mt-2">
      <input v-model="form.keyword_negate" type="checkbox" id="negate" />
      <label for="negate" class="text-sm text-(--text-2)">
        <i18n-t keypath="create_monitor.keyword_negate" tag="span">
          <template #strong><strong class="text-(--text-1)">{{ t('create_monitor.keyword_negate_strong') }}</strong></template>
        </i18n-t>
      </label>
    </div>
  </div>

  <!-- JSON path options -->
  <div v-if="form.check_type === 'json_path'" class="grid grid-cols-2 gap-4">
    <div>
      <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.json_path_label') }} *</label>
      <input v-model="form.expected_json_path" class="input w-full" placeholder="$.status" required />
    </div>
    <div>
      <label class="block text-sm font-medium text-(--text-2) mb-1">
        {{ t('create_monitor.json_expected_value') }} <span class="text-(--text-3)">({{ t('common.optional') }})</span>
      </label>
      <input v-model="form.expected_json_value" class="input w-full" placeholder="ok" />
    </div>
  </div>

  <!-- Scenario builder -->
  <div v-if="form.check_type === 'scenario'">
    <label class="block text-sm font-medium text-(--text-2) mb-2">{{ t('create_monitor.scenario_label') }}</label>
    <ScenarioBuilder
      v-model="form.scenario_steps"
      :variables="form.scenario_variables"
      @update:variables="form.scenario_variables = $event"
    />
  </div>

  <!-- Network scope (hidden for heartbeat and composite) -->
  <div v-if="hasProbeSettings">
    <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('monitors.network_scope.label') }}</label>
    <div class="grid grid-cols-3 gap-2">
      <button
        v-for="s in networkScopes" :key="s.value" type="button"
        @click="form.network_scope = s.value"
        class="py-2 px-2 rounded-lg border text-xs font-medium transition-colors text-center"
        :class="form.network_scope === s.value
          ? 'bg-(--accent-glow) border-(--accent-border) text-(--accent)'
          : 'border-(--border) text-(--text-2) hover:border-(--border-hover) hover:text-(--text-1)'"
      >
        <div class="text-base mb-0.5">{{ s.icon }}</div>
        {{ s.label }}
      </button>
    </div>
    <p class="text-xs text-(--text-3) mt-1">{{ networkScopes.find(s => s.value === form.network_scope)?.desc }}</p>
  </div>

  <!-- Interval / Timeout (hidden for heartbeat and composite — no physical probe) -->
  <div v-if="hasProbeSettings" class="grid grid-cols-2 gap-4">
    <div>
      <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.interval') }}</label>
      <input v-model.number="form.interval_seconds" class="input w-full" type="number" min="5" max="86400" />
    </div>
    <div>
      <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('create_monitor.timeout') }}</label>
      <input v-model.number="form.timeout_seconds" class="input w-full" type="number" min="1" max="60" />
    </div>
  </div>

  <!-- HTTP-only options -->
  <template v-if="HTTP_TYPES.includes(form.check_type)">
    <div class="flex items-center gap-3">
      <input v-model="form.follow_redirects" type="checkbox" id="redirects" />
      <label for="redirects" class="text-sm text-(--text-2)">{{ t('create_monitor.follow_redirects') }}</label>
    </div>
    <div class="flex items-center gap-3">
      <input v-model="form.ssl_check_enabled" type="checkbox" id="ssl" />
      <label for="ssl" class="text-sm text-(--text-2)">{{ t('create_monitor.ssl_check') }}</label>
    </div>
    <div v-if="form.ssl_check_enabled" class="ml-6 space-y-2 border-l-2 border-(--border) pl-3">
      <div>
        <label class="text-xs text-(--text-2) block mb-1">{{ t('monitors.sslAdvanced.pin') }}</label>
        <input v-model="form.ssl_pin_sha256" class="input w-full font-mono text-xs" :placeholder="t('monitors.sslAdvanced.pinPlaceholder')" maxlength="64" pattern="[a-f0-9]{64}" />
        <p class="text-xs text-(--text-3) mt-1">{{ t('monitors.sslAdvanced.pinHint') }}</p>
      </div>
      <div>
        <label class="text-xs text-(--text-2) block mb-1">{{ t('monitors.sslAdvanced.minChainDays') }}</label>
        <input v-model.number="form.ssl_min_chain_days" type="number" class="input w-32 text-xs" min="1" max="365" :placeholder="t('monitors.sslAdvanced.minChainPlaceholder')" />
        <p class="text-xs text-(--text-3) mt-1">{{ t('monitors.sslAdvanced.minChainHint') }}</p>
      </div>
    </div>

    <!-- Custom request headers accordion -->
    <div class="border border-(--border) rounded-lg overflow-hidden">
      <button
        type="button"
        @click="showCustomHeaders = !showCustomHeaders"
        class="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-(--text-2) hover:text-(--text-1) hover:bg-(--bg-surface-2) transition-colors"
      >
        <span>{{ t('monitors.customHeaders.title') }}</span>
        <span class="text-xs transition-transform" :class="showCustomHeaders ? 'rotate-180' : ''">▼</span>
      </button>
      <div v-if="showCustomHeaders" class="px-4 pb-4 pt-2 space-y-3 border-t border-(--border) bg-(--bg-surface-2)">
        <p class="text-xs text-(--text-3)">{{ t('monitors.customHeaders.desc') }}</p>
        <div class="flex items-center gap-2">
          <label class="text-xs text-(--text-2) shrink-0">{{ t('monitors.customHeaders.presets.label') }}</label>
          <select v-model="selectedUaPreset" @change="onUaPresetChange" class="input text-xs flex-1">
            <option value="">{{ t('monitors.customHeaders.presets.choose') }}</option>
            <option v-for="p in UA_PRESETS" :key="p.id" :value="p.id">{{ t(p.labelKey) }}</option>
          </select>
        </div>
        <div v-if="form.custom_headers_list.length" class="space-y-2">
          <div v-for="(h, idx) in form.custom_headers_list" :key="idx" class="flex gap-2 items-center">
            <input v-model="h.key" class="input flex-1 font-mono text-xs" :placeholder="t('monitors.customHeaders.namePlaceholder')" maxlength="100" />
            <input v-model="h.value" class="input flex-1 font-mono text-xs" :placeholder="t('monitors.customHeaders.valuePlaceholder')" maxlength="500" />
            <button type="button" @click="removeCustomHeader(idx)" class="text-(--down) text-xs px-1 shrink-0" :aria-label="t('a11y.remove')">✕</button>
          </div>
        </div>
        <p v-else class="text-xs text-(--text-3)">{{ t('monitors.customHeaders.empty') }}</p>
        <button
          type="button"
          @click="addCustomHeader"
          class="text-xs text-(--accent) flex items-center gap-1"
          :disabled="form.custom_headers_list.length >= 20"
        >+ {{ t('monitors.customHeaders.add') }}</button>
      </div>
    </div>

    <!-- Advanced assertions accordion -->
    <div class="border border-(--border) rounded-lg overflow-hidden">
      <button
        type="button"
        @click="showAdvanced = !showAdvanced"
        class="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-(--text-2) hover:text-(--text-1) hover:bg-(--bg-surface-2) transition-colors"
      >
        <span>{{ t('create_monitor.advanced_assertions') }}</span>
        <span class="text-xs transition-transform" :class="showAdvanced ? 'rotate-180' : ''">▼</span>
      </button>
      <div v-if="showAdvanced" class="px-4 pb-4 pt-2 space-y-4 border-t border-(--border) bg-(--bg-surface-2)">
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">
            {{ t('create_monitor.body_regex') }} <span class="text-(--text-3)">({{ t('common.optional') }})</span>
          </label>
          <input v-model="form.body_regex" class="input w-full font-mono text-sm" placeholder=".*&quot;status&quot;:&quot;ok&quot;.*" />
          <p class="text-xs text-(--text-3) mt-1">{{ t('create_monitor.body_regex_hint') }}</p>
        </div>

        <div>
          <div class="flex items-center justify-between mb-2">
            <label class="text-sm font-medium text-(--text-2)">{{ t('create_monitor.expected_headers') }}</label>
            <button type="button" @click="addExpectedHeader" class="text-xs text-(--accent) flex items-center gap-1">
              + {{ t('common.add') }}
            </button>
          </div>
          <div v-if="form.expected_headers_list.length" class="space-y-2">
            <div v-for="(h, idx) in form.expected_headers_list" :key="idx" class="flex gap-2 items-center">
              <input v-model="h.key" class="input flex-1 font-mono text-xs" placeholder="content-type" />
              <input v-model="h.value" class="input flex-1 font-mono text-xs" placeholder="application/json" />
              <button type="button" @click="removeExpectedHeader(idx)" class="text-(--down) text-xs px-1 shrink-0" :aria-label="t('a11y.remove')">✕</button>
            </div>
          </div>
          <p v-else class="text-xs text-(--text-3)">{{ t('create_monitor.no_headers') }}</p>
          <p class="text-xs text-(--text-3) mt-1">{{ t('create_monitor.headers_regex_hint') }}</p>
        </div>

        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">
            JSON Schema <span class="text-(--text-3)">({{ t('common.optional') }})</span>
          </label>
          <textarea
            v-model="form.json_schema_text"
            rows="4"
            class="input w-full font-mono text-xs"
            placeholder="{&quot;type&quot;:&quot;object&quot;}"
          ></textarea>
          <p v-if="jsonSchemaError" class="text-xs text-(--down) mt-1">{{ jsonSchemaError }}</p>
          <p class="text-xs text-(--text-3) mt-1">{{ t('create_monitor.json_schema_hint') }}</p>
        </div>
      </div>
    </div>
  </template>

  <!-- Blocs propres à une modale intercalés ici (le runbook de l'édition
       s'affiche avant ce panneau) — sans ce slot, l'extraction déplacerait
       ce bloc dans l'écran. -->
  <slot name="before-advanced-detection" />

  <!-- Auto-pause. Was also home to per-monitor flapping overrides
       (flap_threshold / flap_window_minutes) until plan Cap v2 4b: the
       Health Engine (only detection engine left) damps rapid oscillation via
       its quorum window + cooldown instead, so the per-monitor setting was
       retired rather than left inert (CLAUDE.md "Health Engine V2"). -->
  <div v-if="form.check_type !== 'heartbeat'" class="border border-(--border) rounded-lg overflow-hidden">
    <button
      type="button"
      @click="showAdvancedDetection = !showAdvancedDetection"
      class="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-(--text-2) hover:text-(--text-1) hover:bg-(--bg-surface-2) transition-colors"
    >
      <span>{{ t('monitors.advanced_detection_settings') }}</span>
      <span class="text-xs transition-transform" :class="showAdvancedDetection ? 'rotate-180' : ''">▼</span>
    </button>
    <div v-if="showAdvancedDetection" class="px-4 pb-4 pt-2 space-y-3 border-t border-(--border) bg-(--bg-surface-2)">
      <div>
        <label class="block text-xs text-(--text-2) mb-1">{{ t('monitors.auto_pause_after') }}</label>
        <input v-model.number="form.auto_pause_after" type="number" min="2" max="100" class="input w-full" />
        <p class="text-xs text-(--text-3) mt-1">{{ t('monitors.auto_pause_after_hint') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { TYPES_WITHOUT_TARGET, useCheckTypes } from '../../lib/checkTypeCatalog'
import { UA_PRESETS, applyUaPreset } from '../../lib/uaPresets'
import { MonitorFormKey } from './monitorFormKeys'
import ScenarioBuilder from './ScenarioBuilder.vue'

// Champs de formulaire partagés par CreateMonitorModal et EditMonitorModal.
// Les deux modales portaient ~300 lignes de markup identique, qui avaient
// divergé (libellés en anglais d'un côté, en français de l'autre).
//
// Le formulaire arrive par inject plutôt que par prop : les champs le mutent
// via v-model, ce que `vue/no-mutating-props` interdirait sur une prop. C'est
// la convention déjà retenue pour les sous-composants de MonitorDetailView
// (cf. `monitors/detail/injectionKeys.js`).
const props = defineProps({
  mode: {
    type: String,
    default: 'create',
    validator: (v) => ['create', 'edit'].includes(v),
  },
  jsonSchemaError: { type: String, default: '' },
})

const { t } = useI18n()
// `form` est le ref fourni par la modale parente. Vue le déballe
// automatiquement dans le template (binding de setup au premier niveau) ;
// dans ce script il faut passer par `.value`.
const form = inject(MonitorFormKey)
const { checkTypes, findType } = useCheckTypes()

const HTTP_TYPES = ['http', 'keyword', 'json_path']
const DNS_RECORD_TYPES = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS']

const currentType = computed(() => findType(form.value.check_type))

// Heartbeat et composite n'interrogent aucune cible réseau : ni portée de
// sonde, ni intervalle/timeout à régler.
const hasProbeSettings = computed(
  () => form.value.check_type !== 'heartbeat' && form.value.check_type !== 'composite',
)

const networkScopes = computed(() => [
  { value: 'all', icon: '🌍', label: t('monitors.network_scope.all'), desc: t('monitors.network_scope.all_desc') },
  { value: 'internal', icon: '🏠', label: t('monitors.network_scope.internal'), desc: t('monitors.network_scope.internal_desc') },
  { value: 'external', icon: '☁️', label: t('monitors.network_scope.external'), desc: t('monitors.network_scope.external_desc') },
])

// Les accordéons s'ouvrent d'emblée quand le monitor a déjà des valeurs à
// montrer — sinon, en édition, un réglage avancé déjà en place resterait
// invisible. Calculé ici (et non dans la modale) puisque l'état vit désormais
// dans ce composant ; à la création le formulaire est vide, donc fermé.
const showAdvanced = ref(
  Boolean(
    form.value.body_regex ||
      form.value.expected_headers_list?.length ||
      form.value.json_schema_text,
  ),
)
const showCustomHeaders = ref(Boolean(form.value.custom_headers_list?.length))
const showAdvancedDetection = ref(false)
const selectedUaPreset = ref('')

const jsonSchemaError = computed(() => props.jsonSchemaError)

function addExpectedHeader() {
  form.value.expected_headers_list.push({ key: '', value: '' })
}
function removeExpectedHeader(idx) {
  form.value.expected_headers_list.splice(idx, 1)
}
function addCustomHeader() {
  if (form.value.custom_headers_list.length >= 20) return
  form.value.custom_headers_list.push({ key: '', value: '' })
}
function removeCustomHeader(idx) {
  form.value.custom_headers_list.splice(idx, 1)
}
// applyUaPreset renvoie une nouvelle liste (il ne mute pas) et attend la
// *valeur* du preset, pas son id. Le garde-fou des 20 en-têtes est le même
// que celui du bouton « + Ajouter ».
function onUaPresetChange() {
  const preset = UA_PRESETS.find((p) => p.id === selectedUaPreset.value)
  if (!preset) return
  const next = applyUaPreset(form.value.custom_headers_list, preset.value)
  if (next.length > 20) return
  form.value.custom_headers_list = next
  selectedUaPreset.value = ''
}
</script>
