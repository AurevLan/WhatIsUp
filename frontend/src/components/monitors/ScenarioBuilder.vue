<template>
  <div class="space-y-4">

    <!-- Variables -->
    <div>
      <div class="flex items-center justify-between mb-2">
        <label class="text-sm font-medium text-(--text-2)">{{ t('scenario.variables') }} <span class="text-(--text-3) font-normal">({{ t('scenario.variables_hint') }} {{ NAME }})</span></label>
        <button type="button" @click="addVariable" class="text-xs text-(--accent)">+ {{ t('scenario.add_variable') }}</button>
      </div>
      <div v-if="localVars.length" class="space-y-2 mb-2">
        <div v-for="(v, i) in localVars" :key="i" class="flex items-center gap-2">
          <input v-model="v.name" class="input flex-1" :placeholder="t('scenario.variable_name_placeholder')" @input="emitVars" style="font-family:monospace;text-transform:uppercase;" />
          <input
            v-model="v.value"
            :type="v.secret ? 'password' : 'text'"
            class="input flex-1"
            :placeholder="t('scenario.variable_value_placeholder')"
            @input="emitVars"
          />
          <button type="button" @click="v.secret = !v.secret; emitVars()"
            class="text-xs px-2 py-1.5 rounded border transition-colors flex-shrink-0"
            :class="v.secret ? 'border-(--warn) text-(--warn) bg-[color-mix(in_srgb,var(--warn)_20%,transparent)]' : 'border-(--border) text-(--text-3)'"
            :title="t('scenario.mark_secret')">
            {{ v.secret ? '🔒' : '👁' }}
          </button>
          <button type="button" @click="removeVar(i)" class="text-(--text-3) hover:text-(--down) flex-shrink-0" :aria-label="t('scenario.remove_variable')">✕</button>
        </div>
      </div>
    </div>

    <!-- Steps -->
    <div>
      <!-- Steps header -->
      <div class="flex items-center justify-between mb-2">
        <div class="flex items-center gap-3">
          <label class="text-sm font-medium text-(--text-2)">{{ t('scenario.steps') }}</label>
          <span class="text-xs text-(--text-3)">{{ t('scenario.step_count', { n: localSteps.length }) }}</span>
          <button type="button" @click="showTemplates = !showTemplates"
            class="text-xs px-2 py-0.5 rounded border border-(--border) text-(--text-2) hover:border-(--accent-border) hover:text-(--accent) transition-colors">
            📋 {{ t('scenario.templates') }}
          </button>
        </div>
        <div class="flex items-center gap-2">
          <!-- Import JSON -->
          <button type="button" @click="$refs.importInput.click()"
            class="text-xs px-2 py-0.5 rounded border border-(--border) text-(--text-2) hover:border-(--accent-border) hover:text-(--accent) transition-colors"
            :title="t('scenario.import_title')">
            ⬇ {{ t('scenario.import') }}
          </button>
          <input ref="importInput" type="file" accept=".json" class="hidden" @change="importJSON" />
          <!-- Export JSON -->
          <button type="button" @click="exportJSON"
            class="text-xs px-2 py-0.5 rounded border border-(--border) text-(--text-2) hover:border-(--accent-border) hover:text-(--accent) transition-colors"
            :title="t('scenario.export_title')">
            ⬆ {{ t('scenario.export') }}
          </button>
        </div>
      </div>

      <!-- Templates panel -->
      <div v-if="showTemplates" class="mb-3 p-3 bg-(--bg-surface) rounded-xl border border-(--border) space-y-2">
        <p class="text-xs text-(--text-2) font-medium mb-2">{{ t('scenario.choose_template') }}</p>
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div v-for="tmpl in templates" :key="tmpl.id"
            @click="applyTemplate(tmpl)"
            class="bg-(--bg-surface-2) rounded-xl p-4 border border-(--border) hover:border-(--accent-border) cursor-pointer transition-all">
            <div class="text-sm font-medium text-(--text-1) mb-1">{{ tmpl.title }}</div>
            <div class="text-xs text-(--text-3)">{{ tmpl.description }}</div>
            <div class="mt-2 flex flex-wrap gap-1">
              <span v-for="varName in tmpl.vars" :key="varName"
                class="text-xs font-mono bg-(--bg-surface-2) text-(--text-2) px-1.5 py-0.5 rounded">
                <span v-text="'{{' + varName + '}}'"></span>
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Step list (drag & drop) -->
      <div class="space-y-2">
        <div
          v-for="(step, i) in localSteps"
          :key="step._id"
          :draggable="true"
          @dragstart="onDragStart(i)"
          @dragover.prevent="onDragOver(i)"
          @dragleave="dragOverIndex = null"
          @drop="onDrop(i)"
          @dragend="dragIndex = null; dragOverIndex = null"
          :class="[
            step.type === 'group'
              ? 'bg-gradient-to-r from-(--bg-surface-2) to-transparent rounded-lg px-4 py-2'
              : 'border rounded-xl p-3 bg-(--bg-surface-2)',
            dragIndex === i ? 'opacity-40' : '',
            dragOverIndex === i && dragIndex !== i ? 'border-(--accent-border) ring-1 ring-(--accent-border)' : (step.type !== 'group' ? 'border-(--border)' : ''),
          ]"
        >
          <!-- Group step: section divider -->
          <template v-if="step.type === 'group'">
            <div class="flex items-center gap-2">
              <span class="text-xs text-(--text-3) cursor-grab select-none">⠿</span>
              <input v-model="step.label" class="bg-transparent border-none outline-none text-sm font-semibold text-(--text-2) flex-1 min-w-0"
                :placeholder="t('scenario.section_title_placeholder')" @input="emitSteps" />
              <button type="button" @click="moveStep(i, -1)" :disabled="i === 0" :aria-label="t('scenario.move_step_up')"
                class="text-(--text-3) hover:text-(--text-1) disabled:opacity-20 flex-shrink-0 text-xs">▲</button>
              <button type="button" @click="moveStep(i, 1)" :disabled="i === localSteps.length - 1" :aria-label="t('scenario.move_step_down')"
                class="text-(--text-3) hover:text-(--text-1) disabled:opacity-20 flex-shrink-0 text-xs">▼</button>
              <button type="button" @click="removeStep(i)" class="text-(--text-3) hover:text-(--down) flex-shrink-0 text-sm" :aria-label="t('scenario.remove_step')">✕</button>
            </div>
          </template>

          <!-- Regular step -->
          <template v-else>
            <!-- Step header -->
            <div class="flex items-center gap-2 mb-2">
              <span class="text-xs text-(--text-3) cursor-grab select-none flex-shrink-0">⠿</span>
              <span class="text-sm font-mono text-(--text-3) flex-shrink-0 w-5 text-right">{{ i + 1 }}</span>
              <span class="text-base flex-shrink-0">{{ stepIcon(step.type) }}</span>

              <!-- Type selector -->
              <select v-model="step.type" class="input text-xs flex-shrink-0 w-36" @change="onTypeChange(step); emitSteps()">
                <optgroup :label="t('scenario.group_navigation')">
                  <option value="navigate">🌐 {{ t('scenario.type.navigate') }}</option>
                  <option value="click">🖱 {{ t('scenario.type.click') }}</option>
                  <option value="fill">⌨ {{ t('scenario.type.fill') }}</option>
                  <option value="press">⌨ {{ t('scenario.type.press') }}</option>
                  <option value="type">⌨ {{ t('scenario.type.type') }}</option>
                  <option value="select">📋 {{ t('scenario.type.select') }}</option>
                  <option value="hover">🖱 {{ t('scenario.type.hover') }}</option>
                  <option value="scroll">📜 {{ t('scenario.type.scroll') }}</option>
                </optgroup>
                <optgroup :label="t('scenario.group_wait')">
                  <option value="wait_element">👁 {{ t('scenario.type.wait_element') }}</option>
                  <option value="wait_time">⏱ {{ t('scenario.type.wait_time') }}</option>
                </optgroup>
                <optgroup :label="t('scenario.group_assertions')">
                  <option value="assert_text">📝 {{ t('scenario.type.assert_text') }}</option>
                  <option value="assert_visible">✅ {{ t('scenario.type.assert_visible') }}</option>
                  <option value="assert_url">🔗 {{ t('scenario.type.assert_url') }}</option>
                </optgroup>
                <optgroup :label="t('scenario.group_misc')">
                  <option value="screenshot">📸 {{ t('scenario.type.screenshot') }}</option>
                  <option value="extract">📤 {{ t('scenario.type.extract') }}</option>
                </optgroup>
              </select>

              <!-- Label -->
              <input v-model="step.label" class="input text-xs flex-1 min-w-0" :placeholder="t('scenario.step_label_placeholder')"
                @input="step._labelEdited = true; emitSteps()" />

              <!-- Move up/down (accessibility) -->
              <button type="button" @click="moveStep(i, -1)" :disabled="i === 0" :aria-label="t('scenario.move_step_up')"
                class="text-(--text-3) hover:text-(--text-1) disabled:opacity-20 flex-shrink-0 text-xs">▲</button>
              <button type="button" @click="moveStep(i, 1)" :disabled="i === localSteps.length - 1" :aria-label="t('scenario.move_step_down')"
                class="text-(--text-3) hover:text-(--text-1) disabled:opacity-20 flex-shrink-0 text-xs">▼</button>
              <button type="button" @click="removeStep(i)" class="text-(--text-3) hover:text-(--down) flex-shrink-0 text-sm" :aria-label="t('scenario.remove_step')">✕</button>
            </div>

            <!-- Step params -->
            <div class="ml-7 grid grid-cols-1 gap-2">

              <!-- navigate -->
              <template v-if="step.type === 'navigate'">
                <input v-model="step.params.url" class="input text-xs w-full font-mono"
                  placeholder="https://example.com or {{BASE_URL}}/login"
                  @input="updateAutoLabel(step); emitSteps()" />
              </template>

              <!-- click / hover / assert_visible -->
              <template v-else-if="['click','hover','assert_visible'].includes(step.type)">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  :placeholder="t('scenario.selector_click_placeholder')"
                  @input="updateAutoLabel(step); emitSteps()" />
              </template>

              <!-- fill -->
              <template v-else-if="step.type === 'fill'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  :placeholder="t('scenario.selector_fill_placeholder')"
                  @input="updateAutoLabel(step); emitSteps()" />
                <input v-model="step.params.value" class="input text-xs w-full"
                  :placeholder="'Value — supports {{VARIABLE}}'"
                  @input="updateAutoLabel(step); emitSteps()" />
              </template>

              <!-- select -->
              <template v-else-if="step.type === 'select'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  :placeholder="t('scenario.selector_placeholder')"
                  @input="emitSteps()" />
                <input v-model="step.params.value" class="input text-xs w-full"
                  :placeholder="t('scenario.option_value_placeholder')"
                  @input="emitSteps()" />
              </template>

              <!-- wait_element -->
              <template v-else-if="step.type === 'wait_element'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  :placeholder="t('scenario.selector_placeholder')"
                  @input="updateAutoLabel(step); emitSteps()" />
                <div class="grid grid-cols-2 gap-2">
                  <select v-model="step.params.state" class="input text-xs" @change="emitSteps">
                    <option value="visible">{{ t('scenario.state_visible') }}</option>
                    <option value="hidden">{{ t('scenario.state_hidden') }}</option>
                    <option value="attached">{{ t('scenario.state_attached') }}</option>
                    <option value="detached">{{ t('scenario.state_detached') }}</option>
                  </select>
                  <input v-model.number="step.params.timeout" class="input text-xs" type="number"
                    :placeholder="t('scenario.timeout_placeholder')" @input="emitSteps" />
                </div>
              </template>

              <!-- wait_time -->
              <template v-else-if="step.type === 'wait_time'">
                <input v-model.number="step.params.duration_ms" class="input text-xs w-full"
                  type="number" min="100" max="30000"
                  :placeholder="t('scenario.duration_placeholder')"
                  @input="updateAutoLabel(step); emitSteps()" />
              </template>

              <!-- assert_text -->
              <template v-else-if="step.type === 'assert_text'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  :placeholder="t('scenario.selector_placeholder')" @input="emitSteps" />
                <div class="grid grid-cols-3 gap-2">
                  <select v-model="step.params.mode" class="input text-xs" @change="emitSteps">
                    <option value="contains">{{ t('scenario.mode_contains') }}</option>
                    <option value="equals">{{ t('scenario.mode_equals') }}</option>
                  </select>
                  <input v-model="step.params.expected" class="input text-xs col-span-2"
                    :placeholder="t('scenario.expected_text_placeholder')"
                    @input="updateAutoLabel(step); emitSteps()" />
                </div>
              </template>

              <!-- assert_url -->
              <template v-else-if="step.type === 'assert_url'">
                <div class="grid grid-cols-3 gap-2">
                  <select v-model="step.params.mode" class="input text-xs" @change="emitSteps">
                    <option value="contains">{{ t('scenario.mode_contains') }}</option>
                    <option value="equals">{{ t('scenario.mode_equals') }}</option>
                  </select>
                  <input v-model="step.params.expected" class="input text-xs col-span-2"
                    :placeholder="t('scenario.expected_url_placeholder')"
                    @input="updateAutoLabel(step); emitSteps()" />
                </div>
              </template>

              <!-- scroll -->
              <template v-else-if="step.type === 'scroll'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  :placeholder="t('scenario.selector_scroll_placeholder')" @input="emitSteps" />
                <div v-if="!step.params.selector" class="grid grid-cols-2 gap-2">
                  <input v-model.number="step.params.x" class="input text-xs" type="number" placeholder="X px" @input="emitSteps" />
                  <input v-model.number="step.params.y" class="input text-xs" type="number" placeholder="Y px" @input="emitSteps" />
                </div>
              </template>

              <!-- press -->
              <template v-else-if="step.type === 'press'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  :placeholder="t('scenario.selector_press_placeholder')"
                  @input="updateAutoLabel(step); emitSteps()" />
                <div class="grid grid-cols-2 gap-2">
                  <select v-model="step.params.key" class="input text-xs" @change="updateAutoLabel(step); emitSteps()">
                    <option value="Tab">Tab</option>
                    <option value="Enter">Enter</option>
                    <option value="Escape">Escape</option>
                    <option value="Space">Space</option>
                    <option value="Backspace">Backspace</option>
                    <option value="Delete">Delete</option>
                    <option value="ArrowDown">Arrow ↓</option>
                    <option value="ArrowUp">Arrow ↑</option>
                    <option value="ArrowLeft">Arrow ←</option>
                    <option value="ArrowRight">Arrow →</option>
                    <option value="Home">Home</option>
                    <option value="End">End</option>
                    <option value="PageDown">Page Down</option>
                    <option value="PageUp">Page Up</option>
                  </select>
                  <input v-model="step.params.key" class="input text-xs font-mono"
                    :placeholder="t('scenario.custom_key_placeholder')"
                    @input="updateAutoLabel(step); emitSteps()" />
                </div>
              </template>

              <!-- type -->
              <template v-else-if="step.type === 'type'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  :placeholder="t('scenario.selector_type_placeholder')"
                  @input="updateAutoLabel(step); emitSteps()" />
                <input v-model="step.params.text" class="input text-xs w-full"
                  :placeholder="'Text to type — supports {{VARIABLE}}'"
                  @input="updateAutoLabel(step); emitSteps()" />
              </template>

              <!-- screenshot -->
              <template v-else-if="step.type === 'screenshot'">
                <input v-model="step.params.name" class="input text-xs w-full"
                  :placeholder="t('scenario.screenshot_name_placeholder')"
                  @input="updateAutoLabel(step); emitSteps()" />
              </template>

              <!-- extract -->
              <template v-else-if="step.type === 'extract'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  :placeholder="t('scenario.selector_placeholder')"
                  @input="emitSteps" />
                <div class="grid grid-cols-2 gap-2">
                  <select v-model="step.params.attribute" class="input text-xs" @change="emitSteps">
                    <option value="text">{{ t('scenario.attr_text') }}</option>
                    <option value="value">{{ t('scenario.attr_value') }}</option>
                    <option value="href">href</option>
                    <option value="src">src</option>
                    <option value="data-*">{{ t('scenario.attr_custom') }}</option>
                  </select>
                  <input v-model="step.params.variable" class="input text-xs font-mono uppercase"
                    :placeholder="t('scenario.extract_variable_placeholder')"
                    @input="updateAutoLabel(step); emitSteps()" />
                </div>
              </template>

            </div>

            <!-- Per-step advanced options -->
            <div class="ml-7 mt-1">
              <button type="button"
                @click="step._showOpts = !step._showOpts"
                class="text-xs text-(--text-3) hover:text-(--text-2) transition-colors">
                ⚙ {{ t('scenario.options') }}{{ (step.timeout_ms || step.continue_on_fail) ? ' ●' : '' }}
              </button>
              <div v-if="step._showOpts" class="mt-2 grid grid-cols-2 gap-2">
                <input v-model.number="step.timeout_ms" class="input text-xs" type="number" min="0"
                  :placeholder="t('scenario.step_timeout_placeholder')"
                  @input="emitSteps" />
                <label class="flex items-center gap-1.5 text-xs text-(--text-2) cursor-pointer">
                  <input type="checkbox" v-model="step.continue_on_fail" @change="emitSteps"
                    class="rounded border-(--border) bg-(--bg-surface-2) text-(--accent)" />
                  {{ t('scenario.continue_on_fail') }}
                </label>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- Visual step type palette -->
      <div class="mt-4 p-3 bg-(--bg-surface) rounded-xl border border-(--border)">
        <p class="text-xs text-(--text-3) font-medium mb-2">{{ t('scenario.add_step') }}</p>
        <div class="grid grid-cols-3 sm:grid-cols-5 gap-2">
          <button
            v-for="pt in paletteTypes"
            :key="pt.type"
            type="button"
            @click="addStep(pt.type)"
            class="bg-(--bg-surface-2) hover:bg-(--bg-surface-3) rounded-xl p-3 text-center cursor-pointer border border-(--border) hover:border-(--accent-border) transition-all flex flex-col items-center gap-1"
          >
            <span class="text-2xl leading-none">{{ pt.icon }}</span>
            <span class="text-xs text-(--text-2) leading-tight">{{ pt.label }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '../../composables/useToast'

const { t } = useI18n()
const { error: toastError } = useToast()

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  variables: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'update:variables'])

// --- Internal state ---
let _uid = 0
function uid() { return ++_uid }

const showTemplates = ref(false)
const dragIndex = ref(null)
const dragOverIndex = ref(null)

// --- Helpers ---
function defaultParams(type) {
  const d = {
    navigate:       { url: '' },
    click:          { selector: '' },
    fill:           { selector: '', value: '' },
    select:         { selector: '', value: '' },
    hover:          { selector: '' },
    scroll:         { selector: '', x: 0, y: 500 },
    wait_element:   { selector: '', state: 'visible', timeout: 5000 },
    wait_time:      { duration_ms: 1000 },
    assert_text:    { selector: '', expected: '', mode: 'contains' },
    assert_visible: { selector: '' },
    assert_url:     { expected: '', mode: 'contains' },
    press:          { selector: '', key: 'Tab' },
    type:           { selector: '', text: '' },
    screenshot:     { name: '' },
    extract:        { selector: '', attribute: 'text', variable: '' },
    group:          {},
  }
  return d[type] || {}
}

function stepIcon(type) {
  const m = {
    navigate: '🌐', click: '🖱', fill: '⌨', select: '📋', hover: '🖱',
    scroll: '📜', wait_element: '👁', wait_time: '⏱',
    assert_text: '📝', assert_visible: '✅', assert_url: '🔗',
    press: '⌨', type: '⌨',
    screenshot: '📸', extract: '📤', group: '━━',
  }
  return m[type] || '•'
}

function autoLabel(step) {
  const p = step.params || {}
  switch (step.type) {
    case 'navigate': {
      if (!p.url) return ''
      try {
        const path = new URL(p.url).pathname
        return '→ ' + path
      } catch {
        // Not a full URL — could be a template like {{BASE_URL}}/login
        const match = p.url.match(/}}(.*)$/)
        return '→ ' + (match ? match[1] || p.url : p.url)
      }
    }
    case 'click':        return p.selector ? `Click ${p.selector}` : ''
    case 'fill':         return (p.value && p.selector) ? `Fill '${p.value}' in ${p.selector}` : ''
    case 'hover':        return p.selector ? `Hover ${p.selector}` : ''
    case 'assert_text':  return p.expected ? `Assert '${p.expected}'` : ''
    case 'assert_url':   return p.expected ? `URL contains '${p.expected}'` : ''
    case 'assert_visible': return p.selector ? `Visible: ${p.selector}` : ''
    case 'wait_element': return p.selector ? `Wait for ${p.selector}` : ''
    case 'wait_time':    return p.duration_ms ? `Wait ${p.duration_ms}ms` : ''
    case 'press':        return p.key ? `Press ${p.key}${p.selector ? ` on ${p.selector}` : ''}` : ''
    case 'type':         return p.text ? `Type '${p.text}'${p.selector ? ` in ${p.selector}` : ''}` : ''
    case 'screenshot':   return `📸 ${p.name || 'capture'}`
    case 'extract':      return p.variable ? `Extract → {{${p.variable}}}` : ''
    default:             return ''
  }
}

function updateAutoLabel(step) {
  if (step._labelEdited) return
  const generated = autoLabel(step)
  if (generated) step.label = generated
}

function hydrateStep(s) {
  return {
    ...s,
    _id: uid(),
    _labelEdited: !!(s.label),  // treat existing labels as user-typed
    _showOpts: false,
    params: { ...defaultParams(s.type), ...(s.params || {}) },
  }
}

function strip(s) {
  // Remove internal UI fields; keep timeout_ms and continue_on_fail
  const { _id, _labelEdited, _showOpts, ...rest } = s
  return rest
}

// --- Reactive data ---
const localSteps = ref(props.modelValue.map(hydrateStep))
const localVars   = ref(props.variables.map(v => ({ ...v })))

watch(() => props.modelValue, (v) => {
  if (JSON.stringify(v) !== JSON.stringify(localSteps.value.map(strip)))
    localSteps.value = v.map(hydrateStep)
}, { deep: true })

watch(() => props.variables, (v) => {
  if (JSON.stringify(v) !== JSON.stringify(localVars.value))
    localVars.value = v.map(x => ({ ...x }))
}, { deep: true })

// --- Emit helpers ---
function emitSteps() {
  emit('update:modelValue', localSteps.value.map(strip))
}

function emitVars() {
  emit('update:variables', localVars.value.map(v => ({ ...v })))
}

// --- Step management ---
function onTypeChange(step) {
  step.params = defaultParams(step.type)
  step._labelEdited = false
  const generated = autoLabel(step)
  if (generated) step.label = generated
}

function addStep(type) {
  const step = { _id: uid(), type, label: '', _labelEdited: false, _showOpts: false, params: defaultParams(type) }
  const generated = autoLabel(step)
  if (generated) step.label = generated
  localSteps.value.push(step)
  emitSteps()
}

function removeStep(i) {
  localSteps.value.splice(i, 1)
  emitSteps()
}

function moveStep(i, dir) {
  const j = i + dir
  if (j < 0 || j >= localSteps.value.length) return
  const tmp = localSteps.value[i]
  localSteps.value[i] = localSteps.value[j]
  localSteps.value[j] = tmp
  emitSteps()
}

// --- Drag & Drop ---
function onDragStart(i) {
  dragIndex.value = i
}

function onDragOver(i) {
  dragOverIndex.value = i
}

function onDrop(i) {
  if (dragIndex.value === null || dragIndex.value === i) return
  const steps = [...localSteps.value]
  const [moved] = steps.splice(dragIndex.value, 1)
  steps.splice(i, 0, moved)
  localSteps.value = steps
  dragIndex.value = null
  dragOverIndex.value = null
  emitSteps()
}

// --- Variables ---
function addVariable() {
  localVars.value.push({ name: '', value: '', secret: false })
  emitVars()
}

function removeVar(i) {
  localVars.value.splice(i, 1)
  emitVars()
}

// --- Import / Export ---
function exportJSON() {
  const data = JSON.stringify(localSteps.value.map(strip), null, 2)
  const blob = new Blob([data], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = 'scenario-steps.json'
  a.click()
  URL.revokeObjectURL(url)
}

function importJSON(event) {
  const file = event.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const parsed = JSON.parse(e.target.result)
      if (!Array.isArray(parsed)) {
        toastError('The JSON file must contain an array of steps.')
        return
      }
      localSteps.value = parsed.map(hydrateStep)
      emitSteps()
    } catch {
      toastError('Could not read the JSON file.')
    }
  }
  reader.readAsText(file)
  // Reset so the same file can be re-imported
  event.target.value = ''
}

// --- Templates ---
const templates = computed(() => [
  {
    id: 'login',
    title: '🔐 ' + t('scenario.tmpl.login_title'),
    description: t('scenario.tmpl.login_desc'),
    vars: ['BASE_URL', 'EMAIL', 'PASSWORD'],
    steps: [
      { type: 'navigate',   label: 'Open login page',   params: { url: '{{BASE_URL}}/login' } },
      { type: 'fill',       label: 'Enter email',       params: { selector: 'input[type=email]',    value: '{{EMAIL}}' } },
      { type: 'fill',       label: 'Enter password',    params: { selector: 'input[type=password]', value: '{{PASSWORD}}' } },
      { type: 'click',      label: 'Click Sign in',     params: { selector: 'button[type=submit]' } },
      { type: 'assert_url', label: 'Verify redirect',   params: { expected: '/dashboard', mode: 'contains' } },
    ],
  },
  {
    id: 'search',
    title: '🔍 ' + t('scenario.tmpl.search_title'),
    description: t('scenario.tmpl.search_desc'),
    vars: ['BASE_URL', 'SEARCH_TERM'],
    steps: [
      { type: 'navigate',    label: 'Open page',          params: { url: '{{BASE_URL}}' } },
      { type: 'fill',        label: 'Enter search term',  params: { selector: 'input[type=search]', value: '{{SEARCH_TERM}}' } },
      { type: 'click',       label: 'Submit search',      params: { selector: 'button[type=submit]' } },
      { type: 'assert_text', label: 'Verify results',     params: { selector: 'body', expected: 'result', mode: 'contains' } },
    ],
  },
  {
    id: 'contact',
    title: '📝 ' + t('scenario.tmpl.contact_title'),
    description: t('scenario.tmpl.contact_desc'),
    vars: ['BASE_URL'],
    steps: [
      { type: 'navigate',    label: 'Open form',          params: { url: '{{BASE_URL}}/contact' } },
      { type: 'fill',        label: 'Name',               params: { selector: 'input[name=name]',  value: 'Test Monitor' } },
      { type: 'fill',        label: 'Email',              params: { selector: 'input[name=email]', value: 'test@example.com' } },
      { type: 'fill',        label: 'Message',            params: { selector: 'textarea',          value: 'Automated test' } },
      { type: 'click',       label: 'Submit',             params: { selector: 'button[type=submit]' } },
      { type: 'assert_text', label: 'Confirmation',       params: { selector: 'body', expected: 'sent', mode: 'contains' } },
    ],
  },
  {
    id: 'cart',
    title: '🛒 ' + t('scenario.tmpl.cart_title'),
    description: t('scenario.tmpl.cart_desc'),
    vars: ['PRODUCT_URL', 'BASE_URL'],
    steps: [
      { type: 'navigate',       label: 'Product page',      params: { url: '{{PRODUCT_URL}}' } },
      { type: 'click',          label: 'Add to cart',       params: { selector: '.add-to-cart' } },
      { type: 'assert_visible', label: 'Cart updated',      params: { selector: '.cart-count' } },
      { type: 'navigate',       label: 'View cart',         params: { url: '{{BASE_URL}}/cart' } },
      { type: 'assert_text',    label: 'Product in cart',   params: { selector: '.cart-items', expected: '1', mode: 'contains' } },
    ],
  },
])

function applyTemplate(tmpl) {
  const hasSteps = localSteps.value.length > 0
  if (hasSteps && !confirm(t('scenario.replace_steps_confirm'))) return

  localSteps.value = tmpl.steps.map(hydrateStep)

  // Pre-populate variables (only add missing ones)
  for (const varName of tmpl.vars) {
    if (!localVars.value.some(v => v.name === varName)) {
      localVars.value.push({ name: varName, value: '', secret: false })
    }
  }

  showTemplates.value = false
  emitSteps()
  emitVars()
}

// --- Visual palette definition ---
// La palette réutilise les libellés du sélecteur de type, avec quelques
// variantes courtes (scenario.palette.*) pour tenir dans les tuiles.
const paletteTypes = computed(() => [
  { type: 'navigate',       icon: '🌐', label: t('scenario.type.navigate')      },
  { type: 'click',          icon: '🖱',  label: t('scenario.type.click')         },
  { type: 'fill',           icon: '⌨',  label: t('scenario.type.fill')          },
  { type: 'press',          icon: '⌨',  label: t('scenario.type.press')         },
  { type: 'type',           icon: '⌨',  label: t('scenario.type.type')          },
  { type: 'select',         icon: '📋', label: t('scenario.type.select')        },
  { type: 'hover',          icon: '🖱',  label: t('scenario.type.hover')         },
  { type: 'scroll',         icon: '📜', label: t('scenario.type.scroll')        },
  { type: 'wait_element',   icon: '👁',  label: t('scenario.palette.wait_element') },
  { type: 'wait_time',      icon: '⏱',  label: t('scenario.palette.wait_time')  },
  { type: 'assert_text',    icon: '📝', label: t('scenario.type.assert_text')   },
  { type: 'assert_visible', icon: '✅', label: t('scenario.palette.assert_visible') },
  { type: 'assert_url',     icon: '🔗', label: t('scenario.type.assert_url')    },
  { type: 'screenshot',     icon: '📷', label: t('scenario.type.screenshot')    },
  { type: 'extract',        icon: '📤', label: t('scenario.type.extract')       },
  { type: 'group',          icon: '━━', label: t('scenario.type.group')         },
])
</script>
