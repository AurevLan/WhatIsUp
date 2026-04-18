<template>
  <div class="dep-graph" ref="containerRef">
    <!-- Loading -->
    <div v-if="loading" class="dep-graph__loading">
      <span class="dep-graph__spinner" />
      {{ t('common.loading') }}
    </div>

    <!-- Empty -->
    <div v-else-if="!loading && graph.nodes.length === 0" class="dep-graph__empty">
      {{ t('graph.no_dependencies') }}
    </div>

    <!-- SVG canvas -->
    <svg
      v-else
      ref="svgRef"
      class="dep-graph__svg"
      :viewBox="`0 0 ${width} ${height}`"
      @mousedown.self="onBgMousedown"
    >
      <defs>
        <!-- Arrowhead marker per status color -->
        <marker
          v-for="color in markerColors"
          :key="color.id"
          :id="color.id"
          markerWidth="8"
          markerHeight="8"
          refX="18"
          refY="3"
          orient="auto"
        >
          <path d="M0,0 L0,6 L8,3 z" :fill="color.fill" />
        </marker>
      </defs>

      <!-- Edges -->
      <g class="dep-graph__edges">
        <line
          v-for="edge in edges"
          :key="`${edge.source}-${edge.target}`"
          :x1="nodeById(edge.source)?.x ?? 0"
          :y1="nodeById(edge.source)?.y ?? 0"
          :x2="nodeById(edge.target)?.x ?? 0"
          :y2="nodeById(edge.target)?.y ?? 0"
          :stroke="edgeColor(edge)"
          stroke-width="1.5"
          stroke-opacity="0.55"
          :stroke-dasharray="edge.suppress_on_parent_down ? '5,3' : 'none'"
          :marker-end="`url(#arrow-${statusKey(edge)})`"
        />
      </g>

      <!-- Nodes -->
      <g
        v-for="node in simNodes"
        :key="node.id"
        class="dep-graph__node"
        :transform="`translate(${node.x},${node.y})`"
        @mousedown.stop="startDrag($event, node)"
        @touchstart.prevent.stop="startDragTouch($event, node)"
        @click="onNodeClick(node)"
        @mouseenter="showTooltip($event, node)"
        @mouseleave="hideTooltip"
        style="cursor: pointer"
      >
        <circle
          :r="NODE_R"
          :fill="nodeColor(node)"
          :stroke="nodeStroke(node)"
          stroke-width="2"
          class="dep-graph__circle"
        />
        <text
          dy="0.35em"
          text-anchor="middle"
          class="dep-graph__label"
          :font-size="11"
          fill="var(--text-1)"
        >{{ truncate(node.name, 14) }}</text>
      </g>
    </svg>

    <!-- Tooltip -->
    <Teleport to="body">
      <div
        v-if="tooltip.visible"
        class="dep-graph__tooltip"
        :style="{ top: tooltip.y + 'px', left: tooltip.x + 'px' }"
      >
        <div class="dep-graph__tooltip-name">{{ tooltip.node?.name }}</div>
        <div class="dep-graph__tooltip-row">
          <span class="dep-graph__tooltip-label">{{ t('graph.tooltip_type') }}</span>
          {{ tooltip.node?.check_type }}
        </div>
        <div class="dep-graph__tooltip-row">
          <span class="dep-graph__tooltip-label">{{ t('graph.tooltip_status') }}</span>
          <span :class="`dep-graph__status dep-graph__status--${tooltip.node?.status ?? 'pending'}`">
            {{ tooltip.node?.status ?? t('status.pending') }}
          </span>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { monitorsApi } from '../../api/monitors'

const { t } = useI18n()
const router = useRouter()

// ── Layout constants ────────────────────────────────────────────────────
const NODE_R = 22
const REPULSION = 4500
const ATTRACTION = 0.045
const DAMPING = 0.82
const MIN_VELOCITY = 0.08

// ── Reactive state ──────────────────────────────────────────────────────
const containerRef = ref(null)
const svgRef = ref(null)
const loading = ref(true)
const width = ref(800)
const height = ref(600)

const graph = reactive({ nodes: [], edges: [] })
const simNodes = ref([])  // { id, name, status, check_type, x, y, vx, vy }

// ── Colors ──────────────────────────────────────────────────────────────
const STATUS_COLORS = {
  up:       '#34d399',
  down:     '#f87171',
  degraded: '#fbbf24',
  pending:  '#6b7280',
  paused:   '#6b7280',
  null:     '#6b7280',
}

function nodeColor(node) {
  return STATUS_COLORS[node.status] ?? STATUS_COLORS.pending
}
function nodeStroke(node) {
  const c = STATUS_COLORS[node.status] ?? STATUS_COLORS.pending
  // Lighten the stroke slightly
  return c
}
function statusKey(edge) {
  const src = simNodes.value.find(n => n.id === edge.source)
  return src?.status ?? 'pending'
}
function edgeColor(edge) {
  return STATUS_COLORS[statusKey(edge)] ?? STATUS_COLORS.pending
}

// Precompute marker defs for each status
const markerColors = computed(() => {
  const seen = new Set()
  const result = []
  for (const node of simNodes.value) {
    const key = node.status ?? 'pending'
    if (!seen.has(key)) {
      seen.add(key)
      result.push({ id: `arrow-${key}`, fill: STATUS_COLORS[key] ?? STATUS_COLORS.pending })
    }
  }
  // Always include pending as fallback
  if (!seen.has('pending')) result.push({ id: 'arrow-pending', fill: STATUS_COLORS.pending })
  return result
})

// ── Helpers ──────────────────────────────────────────────────────────────
const edges = computed(() => graph.edges)

function nodeById(id) {
  return simNodes.value.find(n => n.id === id)
}

function truncate(str, max) {
  return str.length > max ? str.slice(0, max - 1) + '…' : str
}

// ── Fetch graph data ─────────────────────────────────────────────────────
async function fetchGraph() {
  loading.value = true
  try {
    const res = await monitorsApi.getDependencyGraph()
    graph.nodes = res.data.nodes
    graph.edges = res.data.edges
    initSimulation()
  } finally {
    loading.value = false
  }
}

// ── Simulation ───────────────────────────────────────────────────────────
let rafId = null

function initSimulation() {
  const cx = width.value / 2
  const cy = height.value / 2
  const n = graph.nodes.length
  simNodes.value = graph.nodes.map((node, i) => {
    // Place nodes in a circle initially
    const angle = (2 * Math.PI * i) / n
    const r = Math.min(cx, cy) * 0.55
    return {
      ...node,
      x: cx + r * Math.cos(angle) + (Math.random() - 0.5) * 20,
      y: cy + r * Math.sin(angle) + (Math.random() - 0.5) * 20,
      vx: 0,
      vy: 0,
    }
  })
  startAnimation()
}

function tick() {
  const nodes = simNodes.value
  const cx = width.value / 2
  const cy = height.value / 2
  const n = nodes.length

  // Reset forces
  const fx = new Array(n).fill(0)
  const fy = new Array(n).fill(0)

  // Repulsion between nodes
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const dx = nodes[j].x - nodes[i].x || 0.01
      const dy = nodes[j].y - nodes[i].y || 0.01
      const dist2 = dx * dx + dy * dy
      const dist = Math.sqrt(dist2) || 0.01
      const force = REPULSION / dist2
      const fx_ = (force * dx) / dist
      const fy_ = (force * dy) / dist
      fx[i] -= fx_
      fy[i] -= fy_
      fx[j] += fx_
      fy[j] += fy_
    }
  }

  // Attraction along edges
  for (const edge of graph.edges) {
    const si = nodes.findIndex(n => n.id === edge.source)
    const ti = nodes.findIndex(n => n.id === edge.target)
    if (si < 0 || ti < 0) continue
    const dx = nodes[ti].x - nodes[si].x
    const dy = nodes[ti].y - nodes[si].y
    fx[si] += ATTRACTION * dx
    fy[si] += ATTRACTION * dy
    fx[ti] -= ATTRACTION * dx
    fy[ti] -= ATTRACTION * dy
  }

  // Weak center gravity
  for (let i = 0; i < n; i++) {
    fx[i] += (cx - nodes[i].x) * 0.008
    fy[i] += (cy - nodes[i].y) * 0.008
  }

  // Update velocities and positions
  let maxV = 0
  for (let i = 0; i < n; i++) {
    if (nodes[i]._pinned) continue
    nodes[i].vx = (nodes[i].vx + fx[i]) * DAMPING
    nodes[i].vy = (nodes[i].vy + fy[i]) * DAMPING

    // Clamp velocity
    const speed = Math.sqrt(nodes[i].vx ** 2 + nodes[i].vy ** 2)
    if (speed > 12) {
      nodes[i].vx = (nodes[i].vx / speed) * 12
      nodes[i].vy = (nodes[i].vy / speed) * 12
    }
    maxV = Math.max(maxV, speed)

    nodes[i].x = Math.max(NODE_R + 5, Math.min(width.value - NODE_R - 5, nodes[i].x + nodes[i].vx))
    nodes[i].y = Math.max(NODE_R + 18, Math.min(height.value - NODE_R - 5, nodes[i].y + nodes[i].vy))
  }

  return maxV
}

function startAnimation() {
  if (rafId) cancelAnimationFrame(rafId)
  let stableFrames = 0
  function loop() {
    const maxV = tick()
    if (maxV < MIN_VELOCITY) {
      stableFrames++
      if (stableFrames > 30) return  // stable — stop animating
    } else {
      stableFrames = 0
    }
    rafId = requestAnimationFrame(loop)
  }
  rafId = requestAnimationFrame(loop)
}

// ── Drag ────────────────────────────────────────────────────────────────
let dragging = null
let dragOffset = { x: 0, y: 0 }

function getSVGPoint(evt) {
  const svg = svgRef.value
  const pt = svg.createSVGPoint()
  pt.x = evt.clientX
  pt.y = evt.clientY
  return pt.matrixTransform(svg.getScreenCTM().inverse())
}

function startDrag(evt, node) {
  dragging = node
  node._pinned = true
  const pt = getSVGPoint(evt)
  dragOffset = { x: pt.x - node.x, y: pt.y - node.y }
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', endDrag)
  // Resume animation while dragging
  startAnimation()
}

function startDragTouch(evt, node) {
  const touch = evt.touches[0]
  dragging = node
  node._pinned = true
  const pt = getSVGPoint(touch)
  dragOffset = { x: pt.x - node.x, y: pt.y - node.y }
  window.addEventListener('touchmove', onTouchMove, { passive: false })
  window.addEventListener('touchend', endDrag)
  startAnimation()
}

function onMouseMove(evt) {
  if (!dragging || !svgRef.value) return
  const pt = getSVGPoint(evt)
  dragging.x = Math.max(NODE_R + 5, Math.min(width.value - NODE_R - 5, pt.x - dragOffset.x))
  dragging.y = Math.max(NODE_R + 18, Math.min(height.value - NODE_R - 5, pt.y - dragOffset.y))
}

function onTouchMove(evt) {
  evt.preventDefault()
  if (!dragging || !svgRef.value) return
  const pt = getSVGPoint(evt.touches[0])
  dragging.x = Math.max(NODE_R + 5, Math.min(width.value - NODE_R - 5, pt.x - dragOffset.x))
  dragging.y = Math.max(NODE_R + 18, Math.min(height.value - NODE_R - 5, pt.y - dragOffset.y))
}

function endDrag() {
  if (dragging) {
    dragging._pinned = false
    dragging = null
  }
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', endDrag)
  window.removeEventListener('touchmove', onTouchMove)
  window.removeEventListener('touchend', endDrag)
}

function onBgMousedown() {
  // nothing — just stop propagation from background clicks
}

// ── Node click → navigate ─────────────────────────────────────────────
function onNodeClick(node) {
  if (dragging) return
  router.push(`/monitors/${node.id}`)
}

// ── Tooltip ──────────────────────────────────────────────────────────────
const tooltip = reactive({ visible: false, node: null, x: 0, y: 0 })

function showTooltip(evt, node) {
  tooltip.node = node
  tooltip.x = evt.clientX + 14
  tooltip.y = evt.clientY + 14
  tooltip.visible = true
}
function hideTooltip() {
  tooltip.visible = false
}

// ── Resize observer ──────────────────────────────────────────────────────
let ro = null

function updateSize() {
  if (!containerRef.value) return
  width.value = containerRef.value.clientWidth || 800
  height.value = containerRef.value.clientHeight || 600
}

// ── Lifecycle ────────────────────────────────────────────────────────────
onMounted(async () => {
  updateSize()
  ro = new ResizeObserver(() => {
    updateSize()
    if (simNodes.value.length) startAnimation()
  })
  ro.observe(containerRef.value)
  await fetchGraph()
})

onUnmounted(() => {
  if (rafId) cancelAnimationFrame(rafId)
  if (ro) ro.disconnect()
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', endDrag)
  window.removeEventListener('touchmove', onTouchMove)
  window.removeEventListener('touchend', endDrag)
})
</script>

<style scoped>
.dep-graph {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 480px;
  background: var(--bg-surface);
  border-radius: var(--radius);
  border: 1px solid var(--border);
  overflow: hidden;
}

.dep-graph__loading,
.dep-graph__empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 13px;
}

.dep-graph__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.dep-graph__svg {
  display: block;
  width: 100%;
  height: 100%;
}

.dep-graph__node {
  user-select: none;
  -webkit-user-select: none;
}

.dep-graph__circle {
  transition: filter 0.15s;
  filter: drop-shadow(0 1px 4px rgba(0,0,0,0.25));
}
.dep-graph__node:hover .dep-graph__circle {
  filter: drop-shadow(0 2px 8px rgba(0,0,0,0.45)) brightness(1.12);
}

.dep-graph__label {
  pointer-events: none;
  font-family: inherit;
  font-weight: 500;
  text-shadow: 0 1px 3px rgba(0,0,0,0.6);
  fill: white;
}

/* Tooltip */
.dep-graph__tooltip {
  position: fixed;
  z-index: 9999;
  background: var(--bg-surface-2, #1e2330);
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: 8px 12px;
  min-width: 160px;
  pointer-events: none;
  box-shadow: 0 4px 20px rgba(0,0,0,0.35);
  font-size: 12px;
}

.dep-graph__tooltip-name {
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}

.dep-graph__tooltip-row {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-2);
  line-height: 1.7;
}

.dep-graph__tooltip-label {
  color: var(--text-3);
  min-width: 42px;
}

.dep-graph__status {
  font-weight: 600;
  text-transform: capitalize;
}
.dep-graph__status--up      { color: #34d399; }
.dep-graph__status--down    { color: #f87171; }
.dep-graph__status--degraded{ color: #fbbf24; }
.dep-graph__status--pending,
.dep-graph__status--paused  { color: #6b7280; }
</style>
