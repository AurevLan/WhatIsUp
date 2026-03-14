<template>
  <div class="space-y-4">

    <!-- Variables -->
    <div>
      <div class="flex items-center justify-between mb-2">
        <label class="text-sm font-medium text-gray-300">Variables <span class="text-gray-500 font-normal">(usable with {{NAME}})</span></label>
        <button type="button" @click="addVariable" class="text-xs text-blue-400 hover:text-blue-300">+ Add variable</button>
      </div>
      <div v-if="localVars.length" class="space-y-2 mb-2">
        <div v-for="(v, i) in localVars" :key="i" class="flex items-center gap-2">
          <input v-model="v.name" class="input flex-1" placeholder="NAME" @input="emitVars" style="font-family:monospace;text-transform:uppercase;" />
          <input
            v-model="v.value"
            :type="v.secret ? 'password' : 'text'"
            class="input flex-1"
            placeholder="value"
            @input="emitVars"
          />
          <button type="button" @click="v.secret = !v.secret; emitVars()"
            class="text-xs px-2 py-1.5 rounded border transition-colors flex-shrink-0"
            :class="v.secret ? 'border-amber-600 text-amber-400 bg-amber-900/20' : 'border-gray-700 text-gray-500'"
            title="Mark as secret (hidden)">
            {{ v.secret ? '🔒' : '👁' }}
          </button>
          <button type="button" @click="removeVar(i)" class="text-gray-600 hover:text-red-400 flex-shrink-0">✕</button>
        </div>
      </div>
    </div>

    <!-- Steps -->
    <div>
      <!-- Steps header -->
      <div class="flex items-center justify-between mb-2">
        <div class="flex items-center gap-3">
          <label class="text-sm font-medium text-gray-300">Steps</label>
          <span class="text-xs text-gray-500">{{ localSteps.length }} step(s)</span>
          <button type="button" @click="showTemplates = !showTemplates"
            class="text-xs px-2 py-0.5 rounded border border-gray-700 text-gray-400 hover:border-blue-600 hover:text-blue-400 transition-colors">
            📋 Templates
          </button>
        </div>
        <div class="flex items-center gap-2">
          <!-- Import JSON -->
          <button type="button" @click="$refs.importInput.click()"
            class="text-xs px-2 py-0.5 rounded border border-gray-700 text-gray-400 hover:border-blue-600 hover:text-blue-400 transition-colors"
            title="Import steps from a JSON file">
            ⬇ Import
          </button>
          <input ref="importInput" type="file" accept=".json" class="hidden" @change="importJSON" />
          <!-- Export JSON -->
          <button type="button" @click="exportJSON"
            class="text-xs px-2 py-0.5 rounded border border-gray-700 text-gray-400 hover:border-blue-600 hover:text-blue-400 transition-colors"
            title="Export steps as JSON">
            ⬆ Export
          </button>
        </div>
      </div>

      <!-- Templates panel -->
      <div v-if="showTemplates" class="mb-3 p-3 bg-gray-900/60 rounded-xl border border-gray-700 space-y-2">
        <p class="text-xs text-gray-400 font-medium mb-2">Choose a template to pre-fill steps:</p>
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div v-for="tmpl in templates" :key="tmpl.id"
            @click="applyTemplate(tmpl)"
            class="bg-gray-800/40 rounded-xl p-4 border border-gray-700 hover:border-blue-600 cursor-pointer transition-all">
            <div class="text-sm font-medium text-gray-200 mb-1">{{ tmpl.title }}</div>
            <div class="text-xs text-gray-500">{{ tmpl.description }}</div>
            <div class="mt-2 flex flex-wrap gap-1">
              <span v-for="varName in tmpl.vars" :key="varName"
                class="text-xs font-mono bg-gray-700/50 text-gray-400 px-1.5 py-0.5 rounded">
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
              ? 'bg-gradient-to-r from-gray-800 to-transparent rounded-lg px-4 py-2'
              : 'border rounded-xl p-3 bg-gray-800/50',
            dragIndex === i ? 'opacity-40' : '',
            dragOverIndex === i && dragIndex !== i ? 'border-blue-500 ring-1 ring-blue-500' : (step.type !== 'group' ? 'border-gray-700' : ''),
          ]"
        >
          <!-- Group step: section divider -->
          <template v-if="step.type === 'group'">
            <div class="flex items-center gap-2">
              <span class="text-xs text-gray-600 cursor-grab select-none">⠿</span>
              <input v-model="step.label" class="bg-transparent border-none outline-none text-sm font-semibold text-gray-300 flex-1 min-w-0"
                placeholder="Section title…" @input="emitSteps" />
              <button type="button" @click="moveStep(i, -1)" :disabled="i === 0"
                class="text-gray-600 hover:text-gray-300 disabled:opacity-20 flex-shrink-0 text-xs">▲</button>
              <button type="button" @click="moveStep(i, 1)" :disabled="i === localSteps.length - 1"
                class="text-gray-600 hover:text-gray-300 disabled:opacity-20 flex-shrink-0 text-xs">▼</button>
              <button type="button" @click="removeStep(i)" class="text-gray-600 hover:text-red-400 flex-shrink-0 text-sm">✕</button>
            </div>
          </template>

          <!-- Regular step -->
          <template v-else>
            <!-- Step header -->
            <div class="flex items-center gap-2 mb-2">
              <span class="text-xs text-gray-600 cursor-grab select-none flex-shrink-0">⠿</span>
              <span class="text-sm font-mono text-gray-500 flex-shrink-0 w-5 text-right">{{ i + 1 }}</span>
              <span class="text-base flex-shrink-0">{{ stepIcon(step.type) }}</span>

              <!-- Type selector -->
              <select v-model="step.type" class="input text-xs flex-shrink-0 w-36" @change="onTypeChange(step); emitSteps()">
                <optgroup label="Navigation">
                  <option value="navigate">🌐 Navigate</option>
                  <option value="click">🖱 Click</option>
                  <option value="fill">⌨ Fill</option>
                  <option value="select">📋 Select</option>
                  <option value="hover">🖱 Hover</option>
                  <option value="scroll">📜 Scroll</option>
                </optgroup>
                <optgroup label="Wait">
                  <option value="wait_element">👁 Wait element</option>
                  <option value="wait_time">⏱ Wait time</option>
                </optgroup>
                <optgroup label="Assertions">
                  <option value="assert_text">📝 Assert text</option>
                  <option value="assert_visible">✅ Assert visible</option>
                  <option value="assert_url">🔗 Assert URL</option>
                </optgroup>
                <optgroup label="Misc">
                  <option value="screenshot">📸 Screenshot</option>
                  <option value="extract">📤 Extract</option>
                </optgroup>
              </select>

              <!-- Label -->
              <input v-model="step.label" class="input text-xs flex-1 min-w-0" placeholder="Description (optional)"
                @input="step._labelEdited = true; emitSteps()" />

              <!-- Move up/down (accessibility) -->
              <button type="button" @click="moveStep(i, -1)" :disabled="i === 0"
                class="text-gray-600 hover:text-gray-300 disabled:opacity-20 flex-shrink-0 text-xs">▲</button>
              <button type="button" @click="moveStep(i, 1)" :disabled="i === localSteps.length - 1"
                class="text-gray-600 hover:text-gray-300 disabled:opacity-20 flex-shrink-0 text-xs">▼</button>
              <button type="button" @click="removeStep(i)" class="text-gray-600 hover:text-red-400 flex-shrink-0 text-sm">✕</button>
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
                  placeholder="CSS selector e.g. button#submit, .btn-login"
                  @input="updateAutoLabel(step); emitSteps()" />
              </template>

              <!-- fill -->
              <template v-else-if="step.type === 'fill'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  placeholder="CSS selector e.g. input[name=email], #password"
                  @input="updateAutoLabel(step); emitSteps()" />
                <input v-model="step.params.value" class="input text-xs w-full"
                  :placeholder="'Value — supports {{VARIABLE}}'"
                  @input="updateAutoLabel(step); emitSteps()" />
              </template>

              <!-- select -->
              <template v-else-if="step.type === 'select'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  placeholder="CSS selector"
                  @input="emitSteps()" />
                <input v-model="step.params.value" class="input text-xs w-full"
                  placeholder="Option value"
                  @input="emitSteps()" />
              </template>

              <!-- wait_element -->
              <template v-else-if="step.type === 'wait_element'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  placeholder="CSS selector"
                  @input="updateAutoLabel(step); emitSteps()" />
                <div class="grid grid-cols-2 gap-2">
                  <select v-model="step.params.state" class="input text-xs" @change="emitSteps">
                    <option value="visible">visible</option>
                    <option value="hidden">hidden</option>
                    <option value="attached">attached</option>
                    <option value="detached">detached</option>
                  </select>
                  <input v-model.number="step.params.timeout" class="input text-xs" type="number"
                    placeholder="Timeout ms (default: 5000)" @input="emitSteps" />
                </div>
              </template>

              <!-- wait_time -->
              <template v-else-if="step.type === 'wait_time'">
                <input v-model.number="step.params.duration_ms" class="input text-xs w-full"
                  type="number" min="100" max="30000"
                  placeholder="Duration in ms e.g. 1000"
                  @input="updateAutoLabel(step); emitSteps()" />
              </template>

              <!-- assert_text -->
              <template v-else-if="step.type === 'assert_text'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  placeholder="CSS selector" @input="emitSteps" />
                <div class="grid grid-cols-3 gap-2">
                  <select v-model="step.params.mode" class="input text-xs" @change="emitSteps">
                    <option value="contains">contains</option>
                    <option value="equals">equals</option>
                  </select>
                  <input v-model="step.params.expected" class="input text-xs col-span-2"
                    placeholder="Expected text"
                    @input="updateAutoLabel(step); emitSteps()" />
                </div>
              </template>

              <!-- assert_url -->
              <template v-else-if="step.type === 'assert_url'">
                <div class="grid grid-cols-3 gap-2">
                  <select v-model="step.params.mode" class="input text-xs" @change="emitSteps">
                    <option value="contains">contains</option>
                    <option value="equals">equals</option>
                  </select>
                  <input v-model="step.params.expected" class="input text-xs col-span-2"
                    placeholder="Expected URL"
                    @input="updateAutoLabel(step); emitSteps()" />
                </div>
              </template>

              <!-- scroll -->
              <template v-else-if="step.type === 'scroll'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  placeholder="CSS selector (leave empty to scroll by position)" @input="emitSteps" />
                <div v-if="!step.params.selector" class="grid grid-cols-2 gap-2">
                  <input v-model.number="step.params.x" class="input text-xs" type="number" placeholder="X px" @input="emitSteps" />
                  <input v-model.number="step.params.y" class="input text-xs" type="number" placeholder="Y px" @input="emitSteps" />
                </div>
              </template>

              <!-- screenshot -->
              <template v-else-if="step.type === 'screenshot'">
                <input v-model="step.params.name" class="input text-xs w-full"
                  placeholder="Name e.g. after-login"
                  @input="updateAutoLabel(step); emitSteps()" />
              </template>

              <!-- extract -->
              <template v-else-if="step.type === 'extract'">
                <input v-model="step.params.selector" class="input text-xs w-full font-mono"
                  placeholder="CSS selector"
                  @input="emitSteps" />
                <div class="grid grid-cols-2 gap-2">
                  <select v-model="step.params.attribute" class="input text-xs" @change="emitSteps">
                    <option value="text">text (content)</option>
                    <option value="value">value (input)</option>
                    <option value="href">href</option>
                    <option value="src">src</option>
                    <option value="data-*">custom attribute</option>
                  </select>
                  <input v-model="step.params.variable" class="input text-xs font-mono uppercase"
                    placeholder="NOM_VARIABLE"
                    @input="updateAutoLabel(step); emitSteps()" />
                </div>
              </template>

            </div>

            <!-- Per-step advanced options -->
            <div class="ml-7 mt-1">
              <button type="button"
                @click="step._showOpts = !step._showOpts"
                class="text-xs text-gray-600 hover:text-gray-400 transition-colors">
                ⚙ Options{{ (step.timeout_ms || step.continue_on_fail) ? ' ●' : '' }}
              </button>
              <div v-if="step._showOpts" class="mt-2 grid grid-cols-2 gap-2">
                <input v-model.number="step.timeout_ms" class="input text-xs" type="number" min="0"
                  placeholder="Timeout ms (inherits global if empty)"
                  @input="emitSteps" />
                <label class="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
                  <input type="checkbox" v-model="step.continue_on_fail" @change="emitSteps"
                    class="rounded border-gray-600 bg-gray-700 text-blue-500" />
                  Continue if this step fails
                </label>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- Visual step type palette -->
      <div class="mt-4 p-3 bg-gray-900/40 rounded-xl border border-gray-700/60">
        <p class="text-xs text-gray-500 font-medium mb-2">Add a step</p>
        <div class="grid grid-cols-5 gap-2">
          <button
            v-for="t in paletteTypes"
            :key="t.type"
            type="button"
            @click="addStep(t.type)"
            class="bg-gray-800/60 hover:bg-gray-700/80 rounded-xl p-3 text-center cursor-pointer border border-gray-700 hover:border-blue-600 transition-all flex flex-col items-center gap-1"
          >
            <span class="text-2xl leading-none">{{ t.icon }}</span>
            <span class="text-xs text-gray-400 leading-tight">{{ t.label }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

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
        alert('The JSON file must contain an array of steps.')
        return
      }
      localSteps.value = parsed.map(hydrateStep)
      emitSteps()
    } catch {
      alert('Could not read the JSON file.')
    }
  }
  reader.readAsText(file)
  // Reset so the same file can be re-imported
  event.target.value = ''
}

// --- Templates ---
const templates = [
  {
    id: 'login',
    title: '🔐 Login form',
    description: 'Opens a login page, fills email + password, verifies redirect.',
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
    title: '🔍 Search + verify',
    description: 'Performs a search and verifies the presence of results.',
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
    title: '📝 Contact form',
    description: 'Fills and submits a contact form, verifies the confirmation.',
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
    title: '🛒 Shopping cart',
    description: 'Adds a product to the cart and verifies its contents.',
    vars: ['PRODUCT_URL', 'BASE_URL'],
    steps: [
      { type: 'navigate',       label: 'Product page',      params: { url: '{{PRODUCT_URL}}' } },
      { type: 'click',          label: 'Add to cart',       params: { selector: '.add-to-cart' } },
      { type: 'assert_visible', label: 'Cart updated',      params: { selector: '.cart-count' } },
      { type: 'navigate',       label: 'View cart',         params: { url: '{{BASE_URL}}/cart' } },
      { type: 'assert_text',    label: 'Product in cart',   params: { selector: '.cart-items', expected: '1', mode: 'contains' } },
    ],
  },
]

function applyTemplate(tmpl) {
  const hasSteps = localSteps.value.length > 0
  if (hasSteps && !confirm('Replace existing steps?')) return

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
const paletteTypes = [
  { type: 'navigate',       icon: '🌐', label: 'Navigate'    },
  { type: 'click',          icon: '🖱',  label: 'Click'       },
  { type: 'fill',           icon: '⌨',  label: 'Fill'        },
  { type: 'select',         icon: '📋', label: 'Select'      },
  { type: 'hover',          icon: '🖱',  label: 'Hover'       },
  { type: 'scroll',         icon: '📜', label: 'Scroll'      },
  { type: 'wait_element',   icon: '👁',  label: 'Wait elem.'  },
  { type: 'wait_time',      icon: '⏱',  label: 'Wait'        },
  { type: 'assert_text',    icon: '📝', label: 'Assert text' },
  { type: 'assert_visible', icon: '✅', label: 'Visible'     },
  { type: 'assert_url',     icon: '🔗', label: 'Assert URL'  },
  { type: 'screenshot',     icon: '📷', label: 'Screenshot'  },
  { type: 'extract',        icon: '📤', label: 'Extract'     },
  { type: 'group',          icon: '━━', label: 'Group'       },
]
</script>
