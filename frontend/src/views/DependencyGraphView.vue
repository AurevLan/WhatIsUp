<template>
  <div class="graph-view">
    <div class="graph-view__header">
      <h1 class="graph-view__title">{{ t('graph.title') }}</h1>
    </div>
    <div class="graph-view__canvas">
      <DependencyGraph />
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import DependencyGraph from '../components/monitors/DependencyGraph.vue'

const { t } = useI18n()
</script>

<style scoped>
.graph-view {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--topbar-h, 48px));
  padding: 16px;
  gap: 12px;
  box-sizing: border-box;
}

.graph-view__header {
  flex-shrink: 0;
}

.graph-view__title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-1);
  margin: 0;
}

.graph-view__canvas {
  flex: 1;
  min-height: 0;
}
</style>
