<template>
  <div class="diag-panel">
    <div v-if="loading" class="diag-loading">{{ t('diagnostic.loading') }}</div>
    <div v-else-if="error" class="diag-error">{{ error }}</div>
    <div v-else-if="!groups.length" class="diag-empty">{{ t('diagnostic.empty') }}</div>
    <div v-else class="diag-grid">
      <section v-for="group in groups" :key="group.probe_id || 'unknown'" class="diag-probe">
        <header class="diag-probe__head">
          <span class="diag-probe__name">{{ group.probe_name || t('diagnostic.unknown_probe') }}</span>
          <span class="diag-probe__count">{{ group.items.length }}</span>
        </header>
        <article
          v-for="item in group.items"
          :key="item.id"
          class="diag-card"
          :class="{ 'diag-card--err': item.error }"
        >
          <div class="diag-card__head">
            <span class="diag-card__kind">{{ kindLabel(item.kind) }}</span>
            <time class="diag-card__time">{{ formatTime(item.collected_at) }}</time>
          </div>
          <div v-if="item.error" class="diag-card__error">{{ item.error }}</div>
          <div v-else class="diag-card__body">
            <component :is="rendererFor(item.kind)" :payload="item.payload" />
          </div>
        </article>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, h, ref, watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'
import { incidentUpdatesApi } from '../../api/incidentUpdates'

const props = defineProps({ incidentId: { type: String, required: true } })
const { t } = useI18n()

const loading = ref(false)
const error = ref(null)
const items = ref([])

watchEffect(async () => {
  if (!props.incidentId) return
  loading.value = true
  error.value = null
  try {
    const { data } = await incidentUpdatesApi.diagnostics(props.incidentId)
    items.value = Array.isArray(data) ? data : []
  } catch (err) {
    error.value = err?.response?.data?.detail || err.message || 'error'
  } finally {
    loading.value = false
  }
})

const groups = computed(() => {
  const buckets = new Map()
  for (const it of items.value) {
    const key = it.probe_id || 'unknown'
    if (!buckets.has(key)) {
      buckets.set(key, { probe_id: it.probe_id, probe_name: it.probe_name, items: [] })
    }
    buckets.get(key).items.push(it)
  }
  return [...buckets.values()]
})

function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString()
}

function kindLabel(kind) {
  const map = {
    traceroute: t('diagnostic.kind_traceroute'),
    dig_trace: t('diagnostic.kind_dig_trace'),
    openssl_handshake: t('diagnostic.kind_openssl_handshake'),
    icmp_ping: t('diagnostic.kind_icmp_ping'),
    http_verbose: t('diagnostic.kind_http_verbose'),
  }
  return map[kind] || kind
}

function rendererFor(kind) {
  return {
    traceroute: TracerouteRenderer,
    dig_trace: DigTraceRenderer,
    openssl_handshake: OpensslRenderer,
    icmp_ping: PingRenderer,
    http_verbose: HttpVerboseRenderer,
  }[kind] || RawRenderer
}

const TracerouteRenderer = {
  props: ['payload'],
  setup(p) {
    return () => h('div', { class: 'diag-trace' }, [
      h('div', { class: 'diag-meta' }, `${p.payload?.total_hops ?? 0} hops · target ${p.payload?.target_ip || '—'}`),
      h('ol', { class: 'diag-hops' }, (p.payload?.hops || []).map(hop =>
        h('li', { class: 'diag-hop' }, [
          h('span', { class: 'diag-hop__n' }, `${hop.n}`),
          h('span', { class: 'diag-hop__ip' }, hop.ip || '*'),
          h('span', { class: 'diag-hop__rtt' }, hop.rtt_ms != null ? `${hop.rtt_ms} ms` : '—'),
        ])
      )),
    ])
  },
}

const DigTraceRenderer = {
  props: ['payload'],
  setup(p) {
    return () => h('pre', { class: 'diag-pre' }, (p.payload?.records || []).join('\n'))
  },
}

const OpensslRenderer = {
  props: ['payload'],
  setup(p) {
    const { cn, issuer, protocol, cipher, chain_depth } = p.payload || {}
    return () => h('div', { class: 'diag-tls' }, [
      h('div', { class: 'diag-meta' }, `CN ${cn || '—'} · issuer ${issuer || '—'}`),
      h('div', { class: 'diag-meta' }, `${protocol || '—'} · ${cipher || '—'} · chain ${chain_depth ?? 0}`),
    ])
  },
}

const PingRenderer = {
  props: ['payload'],
  setup(p) {
    const d = p.payload || {}
    return () => h('div', { class: 'diag-meta' },
      `${d.packets_received ?? 0}/${d.packets_sent ?? 0} · loss ${d.loss_pct ?? 0}% · rtt ${d.rtt_avg_ms ?? '—'} ms (min ${d.rtt_min_ms ?? '—'}, max ${d.rtt_max_ms ?? '—'})`
    )
  },
}

const HttpVerboseRenderer = {
  props: ['payload'],
  setup(p) {
    const d = p.payload || {}
    return () => h('div', { class: 'diag-http' }, [
      h('div', { class: 'diag-meta' }, `HTTP ${d.status_code ?? '—'} · ${d.ssl_protocol || 'plaintext'}`),
      d.response_headers?.length
        ? h('pre', { class: 'diag-pre' }, d.response_headers.join('\n'))
        : null,
    ])
  },
}

const RawRenderer = {
  props: ['payload'],
  setup(p) {
    return () => h('pre', { class: 'diag-pre' }, JSON.stringify(p.payload, null, 2))
  },
}
</script>

<style scoped>
.diag-panel { padding: 0.75rem 1rem; background: rgba(2, 6, 23, 0.4); border-top: 1px solid rgba(148, 163, 184, 0.15); }
.diag-loading, .diag-empty, .diag-error { font-size: 0.8rem; color: rgb(148, 163, 184); padding: 0.25rem 0; }
.diag-error { color: rgb(248, 113, 113); }
.diag-grid { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.diag-probe { background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 6px; padding: 0.5rem; }
.diag-probe__head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; font-size: 0.75rem; color: rgb(203, 213, 225); }
.diag-probe__count { font-variant-numeric: tabular-nums; opacity: 0.6; }
.diag-card { background: rgba(2, 6, 23, 0.6); border-radius: 4px; padding: 0.4rem 0.5rem; margin-bottom: 0.4rem; font-size: 0.75rem; }
.diag-card:last-child { margin-bottom: 0; }
.diag-card--err { border-left: 2px solid rgb(248, 113, 113); }
.diag-card__head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem; }
.diag-card__kind { font-weight: 600; color: rgb(148, 163, 184); text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.65rem; }
.diag-card__time { font-variant-numeric: tabular-nums; color: rgb(100, 116, 139); font-size: 0.65rem; }
.diag-card__error { color: rgb(248, 113, 113); font-family: ui-monospace, monospace; }
.diag-meta { color: rgb(203, 213, 225); margin-bottom: 0.25rem; }
.diag-pre { font-family: ui-monospace, "SFMono-Regular", monospace; font-size: 0.7rem; line-height: 1.3; white-space: pre-wrap; word-break: break-all; max-height: 220px; overflow: auto; color: rgb(148, 163, 184); margin: 0; padding: 0.25rem 0.4rem; background: rgba(15, 23, 42, 0.4); border-radius: 3px; }
.diag-hops { list-style: none; padding: 0; margin: 0; max-height: 220px; overflow: auto; }
.diag-hop { display: grid; grid-template-columns: 2.5ch 1fr auto; gap: 0.5rem; font-family: ui-monospace, monospace; font-size: 0.7rem; padding: 0.1rem 0; }
.diag-hop__n { color: rgb(100, 116, 139); text-align: right; }
.diag-hop__ip { color: rgb(203, 213, 225); }
.diag-hop__rtt { color: rgb(94, 234, 212); }
</style>
