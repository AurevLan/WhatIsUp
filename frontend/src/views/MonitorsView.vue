<template>
  <div class="page-body max-w-6xl">

    <!-- Header -->
    <div class="flex items-start justify-between mb-4">
      <div>
        <h1 class="text-xl font-bold" style="color:var(--text-1)">{{ t('monitors.title') }}</h1>
        <p class="mt-0.5 text-xs" style="color:var(--text-3)">
          {{ monitors.length }} {{ t('nav.monitors').toLowerCase() }}<template v-if="downCount > 0"> — <span style="color:var(--down)">{{ downCount }} {{ t('status.down').toLowerCase() }}</span></template><template v-if="errorCount > 0">, <span style="color:#fb923c">{{ errorCount }} {{ t('common.error').toLowerCase() }}</span></template>
        </p>
      </div>
    </div>

    <!-- Barre d'actions contextuelles (bulk) -->
    <BulkActionBar :count="selectedIds.size" @clear="clearSelection">
      <button @click="bulkEnable" class="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5">
        <Play class="w-3.5 h-3.5" /> {{ t('monitors.bulk_enable') }}
      </button>
      <button @click="bulkPause" class="btn-secondary text-xs flex items-center gap-1.5">
        <Pause class="w-3.5 h-3.5" /> {{ t('monitors.bulk_pause') }}
      </button>

      <!-- Move to group (T1-12) -->
      <select
        :value="''"
        @change="onBulkSetGroup($event.target.value); $event.target.value = ''"
        class="input h-8 text-xs"
        style="max-width:11rem"
        :title="t('monitors.bulk_move_group')"
      >
        <option value="" disabled>{{ t('monitors.bulk_move_group') }}…</option>
        <option value="__none__">— {{ t('groups.private') }} —</option>
        <option v-for="g in availableGroups" :key="g.id" :value="g.id">{{ g.name }}</option>
      </select>

      <!-- Add tag (T1-12) -->
      <select
        :value="''"
        @change="onBulkAddTag($event.target.value); $event.target.value = ''"
        class="input h-8 text-xs"
        style="max-width:9rem"
        :title="t('monitors.bulk_add_tag')"
      >
        <option value="" disabled>{{ t('monitors.bulk_add_tag') }}…</option>
        <option v-for="tag in availableTags" :key="tag.id" :value="tag.id">{{ tag.name }}</option>
      </select>

      <button @click="bulkExportCsv" class="btn-secondary text-xs flex items-center gap-1">
        <Download class="w-3.5 h-3.5" /> {{ t('monitors.bulk_export') }}
      </button>
      <button @click="confirmBulkDelete" class="btn-danger text-xs flex items-center gap-1.5">
        <Trash2 class="w-3.5 h-3.5" /> {{ t('monitors.bulk_delete') }}
      </button>
    </BulkActionBar>

    <!-- Filter bar -->
    <div class="space-y-1.5 mb-4">
      <!-- Row 1: search + view toggle + add -->
      <div class="flex gap-2 items-center">
        <div class="relative flex-1">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
          <input ref="searchInput" :value="searchInput_" @input="onSearchInput($event.target.value)" class="input pl-9 h-8 text-xs" :placeholder="t('common.search') + '…'" />
        </div>
        <div class="flex gap-0.5 bg-gray-800/60 p-0.5 rounded-lg border border-gray-700/80">
          <button @click="setViewMode('list')"
            :class="viewMode === 'list' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'"
            class="px-2.5 py-1.5 rounded-md transition-colors" :title="t('monitors.view_list')"
            :aria-label="t('monitors.view_list')">
            <List class="w-4 h-4" />
          </button>
          <button @click="setViewMode('board')"
            :class="viewMode === 'board' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'"
            class="px-2.5 py-1.5 rounded-md transition-colors" :title="t('monitors.view_board')"
            :aria-label="t('monitors.view_board')">
            <LayoutGrid class="w-4 h-4" />
          </button>
        </div>
        <button @click="exportMonitors" class="btn-secondary h-8 text-xs flex items-center gap-1">
          <Download class="w-4 h-4" />
          {{ t('monitors.export_json') }}
        </button>
        <button @click="triggerImport" class="btn-secondary h-8 text-xs flex items-center gap-1">
          <Upload class="w-4 h-4" />
          {{ t('monitors.import_json') }}
        </button>
        <input ref="importFileInput" type="file" accept=".json" class="hidden" :aria-label="t('monitors.import_json')" @change="handleImportFile" />
        <button @click="showCreate = true" class="btn-primary h-8 text-xs">
          <Plus class="w-4 h-4" />
          {{ t('monitors.add') }}
        </button>
      </div>

      <!-- Row 2: filters -->
      <div class="flex flex-wrap gap-2 items-center">
        <!-- Status chips -->
        <div class="flex gap-1">
          <button v-for="s in statusFilters" :key="s.val"
            @click="filterStatus = s.val"
            :class="filterStatus === s.val ? s.active : 'border-gray-700/80 text-gray-500 hover:border-gray-600 hover:text-gray-400'"
            class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs border transition-colors font-medium">
            <span v-if="s.dot" class="w-1.5 h-1.5 rounded-full flex-shrink-0" :class="s.dot" />
            {{ s.label }}
          </button>
        </div>

        <div class="w-px h-4 bg-gray-700/60" />

        <!-- Type dropdown -->
        <select v-model="filterType"
          :aria-label="t('monitors.filter_type')"
          class="h-7 px-2 pr-6 rounded-lg border border-gray-700/80 bg-gray-900 text-xs text-gray-400 focus:outline-none focus:border-blue-600 transition-colors appearance-none cursor-pointer"
          :class="filterType ? 'border-blue-600/60 text-blue-300' : ''">
          <option value="">{{ t('monitors.all_types') }}</option>
          <option v-for="typ in checkTypes" :key="typ" :value="typ">{{ typ }}</option>
        </select>

        <!-- Active filter count badge -->
        <span v-if="activeFilterCount > 0"
          class="text-xs px-2 py-0.5 rounded-full bg-blue-600/20 border border-blue-500/40 text-blue-300 font-semibold">
          {{ activeFilterCount }} filtre{{ activeFilterCount > 1 ? 's' : '' }}
        </span>

        <!-- Clear -->
        <button v-if="hasActiveFilters"
          @click="clearFilters"
          class="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400 ml-auto transition-colors">
          <X class="w-3 h-3" /> {{ t('monitors.clear_filters') }}
        </button>
      </div>
    </div>

    <!-- Table (mode liste) -->
    <div v-if="viewMode === 'list'" class="card p-0 overflow-hidden">
      <div v-if="loading" class="p-4 space-y-3">
        <SkeletonRow v-for="i in 6" :key="i" :trailing-width="'5rem'" />
      </div>

      <EmptyState
        v-else-if="filteredMonitors.length === 0"
        :title="hasActiveFilters ? t('monitors.no_results') : t('monitors.no_monitors')"
        :text="hasActiveFilters ? t('empty.monitors_filtered_text') : t('empty.monitors_text')"
        :cta-label="hasActiveFilters ? t('monitors.clear_filters') : t('monitors.add')"
        :cta-icon="!hasActiveFilters"
        :doc-href="hasActiveFilters ? '' : 'https://github.com/AurevLan/whatisup#monitors'"
        :replay-tour="!hasActiveFilters"
        @cta="hasActiveFilters ? clearFilters() : (showCreate = true)"
      >
        <template #icon><Monitor :size="22" /></template>
      </EmptyState>

      <!-- Mobile: stacked cards (visible < 768px) -->
      <div v-else>
      <div class="md:hidden flex flex-col divide-y divide-gray-800/60">
        <router-link
          v-for="monitor in paginatedMonitors"
          :key="'m-' + monitor.id"
          :to="`/monitors/${monitor.id}`"
          class="block px-4 py-4 min-h-[64px] active:bg-white/[0.03] transition-colors no-underline"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 mb-1">
                <span class="w-2 h-2 rounded-full flex-shrink-0" :class="dotClass(monitor._lastStatus)" />
                <span class="font-semibold text-gray-100 truncate">{{ monitor.name }}</span>
              </div>
              <p class="text-xs text-gray-500 truncate font-mono">
                <span class="uppercase mr-1.5">{{ monitor.check_type }}</span>· {{ formatTarget(monitor) }}
              </p>
            </div>
            <span :class="badgeClass(monitor._lastStatus)" class="flex-shrink-0">
              {{ statusLabel(monitor._lastStatus) }}
            </span>
          </div>
          <div class="flex items-center justify-between mt-3 text-xs">
            <div>
              <span class="text-gray-500">{{ t('monitors.uptime_24h') }}: </span>
              <span class="font-semibold" :class="uptimeColor(monitor._uptime24h)">
                {{ monitor._uptime24h != null ? monitor._uptime24h.toFixed(1) + '%' : '—' }}
              </span>
            </div>
            <div v-if="monitor._lastResponseTimeMs != null" class="font-mono" :class="responseTimeColor(monitor._lastResponseTimeMs, monitor)">
              {{ monitor._lastResponseTimeMs < 1000
                ? monitor._lastResponseTimeMs + 'ms'
                : (monitor._lastResponseTimeMs / 1000).toFixed(2) + 's' }}
            </div>
            <p v-if="!monitor.enabled" class="text-gray-600">{{ t('status.paused') }}</p>
          </div>
        </router-link>
      </div>

      <!-- Desktop: dense table (visible >= 768px) -->
      <table class="hidden md:table w-full">
        <thead class="border-b border-gray-800">
          <tr class="px-6">
            <th class="th pl-4 w-8">
              <input
                type="checkbox"
                class="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-500 cursor-pointer"
                :checked="allVisibleSelected"
                :indeterminate="someVisibleSelected"
                @change="toggleSelectAll"
              />
            </th>
            <th class="th pl-2">{{ t('common.status') }}</th>
            <th class="th cursor-pointer select-none hover:text-gray-300 transition-colors" @click="setSortKey('name')">
              <span class="inline-flex items-center gap-0.5">{{ t('common.name') }} <component v-if="isSorted('name')" :is="sortIcon('name')" :size="11" /></span>
            </th>
            <th class="th hidden md:table-cell">{{ t('monitors.col_target') }}</th>
            <th class="th hidden lg:table-cell">{{ t('monitors.col_interval') }}</th>
            <th class="th hidden sm:table-cell cursor-pointer select-none hover:text-gray-300 transition-colors" @click="setSortKey('uptime')">
              <span class="inline-flex items-center gap-0.5">{{ t('monitors.uptime_24h') }} <component v-if="isSorted('uptime')" :is="sortIcon('uptime')" :size="11" /></span>
            </th>
            <th class="th hidden lg:table-cell cursor-pointer select-none hover:text-gray-300 transition-colors" @click="setSortKey('rt')">
              <span class="inline-flex items-center gap-0.5">{{ t('monitors.col_response') }} <component v-if="isSorted('rt')" :is="sortIcon('rt')" :size="11" /></span>
            </th>
            <th class="th hidden lg:table-cell">{{ t('monitors.col_trend') }}</th>
            <th class="th pr-6 text-right">{{ t('common.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(monitor, idx) in paginatedMonitors"
            :key="monitor.id"
            class="table-row stagger-item group"
            :style="{ animationDelay: idx * 20 + 'ms' }"
            :class="selectedIds.has(monitor.id) ? 'bg-blue-950/20' : ''"
          >
            <!-- Checkbox -->
            <td class="td pl-4 w-8">
              <input
                type="checkbox"
                class="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-500 cursor-pointer"
                :checked="selectedIds.has(monitor.id)"
                @change="toggleSelect(monitor.id)"
              />
            </td>

            <!-- Status -->
            <td class="td pl-2">
              <span :class="badgeClass(monitor._lastStatus)">
                <span class="w-1.5 h-1.5 rounded-full" :class="dotClass(monitor._lastStatus)" />
                {{ statusLabel(monitor._lastStatus) }}
              </span>
            </td>

            <!-- Name -->
            <td class="td">
              <router-link :to="`/monitors/${monitor.id}`" class="font-semibold text-gray-200 hover:text-white transition-colors">
                {{ monitor.name }}
              </router-link>
              <p v-if="!monitor.enabled" class="text-xs text-gray-600 mt-0.5">{{ t('status.paused') }}</p>
            </td>

            <!-- Cible -->
            <td class="td hidden md:table-cell">
              <div class="flex items-center gap-2">
                <span class="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 font-mono uppercase flex-shrink-0">{{ monitor.check_type }}</span>
                <span class="font-mono text-xs text-gray-500 truncate max-w-[180px]">{{ formatTarget(monitor) }}</span>
              </div>
            </td>

            <!-- Interval -->
            <td class="td hidden lg:table-cell text-gray-500">
              {{ monitor.interval_seconds < 60 ? monitor.interval_seconds + 's' : Math.round(monitor.interval_seconds / 60) + 'm' }}
            </td>

            <!-- Uptime -->
            <td class="td hidden sm:table-cell">
              <span class="font-semibold" :class="uptimeColor(monitor._uptime24h)">
                {{ monitor._uptime24h != null ? monitor._uptime24h.toFixed(2) + '%' : '—' }}
              </span>
            </td>

            <!-- Temps de réponse -->
            <td class="td hidden lg:table-cell">
              <span v-if="monitor._lastResponseTimeMs != null" class="font-mono text-xs" :class="responseTimeColor(monitor._lastResponseTimeMs, monitor)">
                {{ monitor._lastResponseTimeMs < 1000
                  ? monitor._lastResponseTimeMs + 'ms'
                  : (monitor._lastResponseTimeMs / 1000).toFixed(2) + 's' }}
              </span>
              <span v-else class="text-gray-700 text-xs">—</span>
            </td>

            <!-- Sparkline -->
            <td class="td hidden lg:table-cell">
              <SparklineCell :data="monitor._sparkline" />
            </td>

            <!-- Actions -->
            <td class="td pr-6">
              <div class="flex items-center justify-end gap-1.5">
                <router-link :to="`/monitors/${monitor.id}`"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-400 hover:text-blue-400 hover:bg-blue-500/10 transition-colors"
                  :title="t('common.view')" :aria-label="t('common.view')">
                  <Eye class="w-3.5 h-3.5" />
                </router-link>
                <button @click.stop="editingMonitor = monitor"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-400 hover:text-amber-400 hover:bg-amber-500/10 transition-colors"
                  :title="t('common.edit')" :aria-label="t('common.edit')">
                  <PencilLine class="w-3.5 h-3.5" />
                </button>
                <button @click.stop="toggleEnabled(monitor)"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs transition-colors"
                  :class="monitor.enabled
                    ? 'text-gray-400 hover:text-orange-400 hover:bg-orange-500/10'
                    : 'text-emerald-600 hover:text-emerald-400 hover:bg-emerald-500/10'"
                  :title="monitor.enabled ? t('monitors.bulk_pause') : t('monitors.bulk_enable')"
                  :aria-label="monitor.enabled ? t('monitors.bulk_pause') : t('monitors.bulk_enable')">
                  <Pause v-if="monitor.enabled" class="w-3.5 h-3.5" />
                  <Play v-else class="w-3.5 h-3.5" />
                </button>
                <button @click.stop="handleDelete(monitor)"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                  :title="t('common.delete')" :aria-label="t('common.delete')">
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      </div>

      <!-- Pagination (list mode) -->
      <div v-if="totalPages > 1" class="flex items-center justify-center gap-1 mt-3 px-4 pb-3">
        <button @click="currentPage--" :disabled="currentPage === 1" class="btn-ghost text-xs disabled:opacity-30 px-1.5" :aria-label="t('common.prev_page')">←</button>
        <template v-for="p in pageNumbers" :key="p">
          <span v-if="p === '...'" class="text-xs px-1" style="color:var(--text-3)">...</span>
          <button v-else @click="currentPage = p"
            class="text-xs w-7 h-7 rounded flex items-center justify-center transition-colors"
            :class="p === currentPage ? 'font-bold' : 'hover:bg-white/5'"
            :style="p === currentPage ? 'background:var(--accent-glow);color:var(--accent);border:1px solid var(--accent-border)' : 'color:var(--text-3)'">
            {{ p }}
          </button>
        </template>
        <button @click="currentPage++" :disabled="currentPage === totalPages" class="btn-ghost text-xs disabled:opacity-30 px-1.5" :aria-label="t('common.next_page')">→</button>
      </div>
    </div>

    <!-- Big Board (mode NOC) -->
    <div v-else>
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        <router-link
          v-for="(monitor, idx) in paginatedMonitors" :key="monitor.id"
          :to="`/monitors/${monitor.id}`"
          class="stagger-item group relative rounded-xl border p-4 transition-all duration-200 hover:scale-[1.02]"
          :style="{ animationDelay: idx * 30 + 'ms' }"
          :class="{
            'border-emerald-700/50 bg-emerald-950/20 hover:border-emerald-600': monitor._lastStatus === 'up',
            'border-red-700/60 bg-red-950/30 hover:border-red-600': monitor._lastStatus === 'down',
            'border-amber-700/50 bg-amber-950/20 hover:border-amber-600': monitor._lastStatus === 'timeout',
            'border-orange-700/50 bg-orange-950/20 hover:border-orange-600': monitor._lastStatus === 'error',
            'border-gray-700 bg-gray-900/30 hover:border-gray-600': !monitor._lastStatus,
          }"
        >
          <!-- Status indicator -->
          <div class="flex items-start justify-between mb-3">
            <span class="w-3 h-3 rounded-full mt-0.5 flex-shrink-0"
              :class="{
                'bg-emerald-400 shadow-lg shadow-emerald-500/30': monitor._lastStatus === 'up',
                'bg-red-500 shadow-lg shadow-red-500/40 animate-pulse': monitor._lastStatus === 'down',
                'bg-amber-400': monitor._lastStatus === 'timeout',
                'bg-orange-500': monitor._lastStatus === 'error',
                'bg-gray-600': !monitor._lastStatus,
              }"
            />
            <span class="text-xs font-mono text-gray-600 bg-gray-800/60 px-1.5 py-0.5 rounded uppercase">
              {{ monitor.check_type }}
            </span>
          </div>

          <!-- Name -->
          <p class="text-sm font-semibold text-gray-200 truncate group-hover:text-white mb-1">
            {{ monitor.name }}
          </p>

          <!-- URL (truncated) -->
          <p class="text-xs text-gray-600 truncate font-mono mb-3">
            {{ monitor.url?.replace(/^https?:\/\//, '') || '—' }}
          </p>

          <!-- Uptime + réponse + paused badge -->
          <div class="flex items-end justify-between">
            <div>
              <p class="text-xs text-gray-600">{{ t('monitors.uptime_24h') }}</p>
              <p class="text-base font-bold" :class="uptimeColor(monitor._uptime24h)">
                {{ monitor._uptime24h != null ? monitor._uptime24h.toFixed(1) + '%' : '—' }}
              </p>
            </div>
            <div class="text-right">
              <p v-if="monitor._lastResponseTimeMs != null" class="text-xs font-mono" :class="responseTimeColor(monitor._lastResponseTimeMs, monitor)">
                {{ monitor._lastResponseTimeMs < 1000
                  ? monitor._lastResponseTimeMs + 'ms'
                  : (monitor._lastResponseTimeMs / 1000).toFixed(1) + 's' }}
              </p>
              <p v-if="!monitor.enabled" class="text-xs text-gray-700 bg-gray-800 px-1.5 py-0.5 rounded">{{ t('status.paused') }}</p>
            </div>
          </div>

          <!-- Sparkline -->
          <div class="mt-2">
            <SparklineCell :data="monitor._sparkline" />
          </div>

          <!-- Card actions -->
          <div class="mt-3 pt-2 border-t border-gray-700/50 flex items-center justify-end gap-1"
            @click.prevent @mousedown.prevent>
            <button @click.prevent="editingMonitor = monitor"
              class="p-1.5 rounded-md text-gray-500 hover:text-amber-400 hover:bg-amber-500/10 transition-colors"
              :title="t('common.edit')" :aria-label="t('common.edit')">
              <PencilLine class="w-3.5 h-3.5" />
            </button>
            <button @click.prevent="toggleEnabled(monitor)"
              class="p-1.5 rounded-md transition-colors"
              :class="monitor.enabled
                ? 'text-gray-500 hover:text-orange-400 hover:bg-orange-500/10'
                : 'text-emerald-600 hover:text-emerald-400 hover:bg-emerald-500/10'"
              :title="monitor.enabled ? t('monitors.bulk_pause') : t('monitors.bulk_enable')"
              :aria-label="monitor.enabled ? t('monitors.bulk_pause') : t('monitors.bulk_enable')">
              <Pause v-if="monitor.enabled" class="w-3.5 h-3.5" />
              <Play v-else class="w-3.5 h-3.5" />
            </button>
            <button @click.prevent="handleDelete(monitor)"
              class="p-1.5 rounded-md text-gray-600 hover:text-red-400 hover:bg-red-500/10 transition-colors"
              :title="t('common.delete')" :aria-label="t('common.delete')">
              <Trash2 class="w-3.5 h-3.5" />
            </button>
          </div>
        </router-link>

        <!-- Empty state -->
        <div v-if="filteredMonitors.length === 0" class="col-span-full">
          <EmptyState
            :title="hasActiveFilters ? t('monitors.no_results') : t('monitors.no_monitors')"
            :text="hasActiveFilters ? t('empty.monitors_filtered_text') : t('empty.monitors_text')"
            :cta-label="hasActiveFilters ? t('monitors.clear_filters') : t('monitors.add')"
            :cta-icon="!hasActiveFilters"
            :replay-tour="!hasActiveFilters"
            @cta="hasActiveFilters ? clearFilters() : (showCreate = true)"
          >
            <template #icon><Monitor :size="22" /></template>
          </EmptyState>
        </div>
      </div>

      <!-- Pagination (board mode) -->
      <div v-if="totalPages > 1" class="flex items-center justify-center gap-1 mt-3">
        <button @click="currentPage--" :disabled="currentPage === 1" class="btn-ghost text-xs disabled:opacity-30 px-1.5" :aria-label="t('common.prev_page')">←</button>
        <template v-for="p in pageNumbers" :key="p">
          <span v-if="p === '...'" class="text-xs px-1" style="color:var(--text-3)">...</span>
          <button v-else @click="currentPage = p"
            class="text-xs w-7 h-7 rounded flex items-center justify-center transition-colors"
            :class="p === currentPage ? 'font-bold' : 'hover:bg-white/5'"
            :style="p === currentPage ? 'background:var(--accent-glow);color:var(--accent);border:1px solid var(--accent-border)' : 'color:var(--text-3)'">
            {{ p }}
          </button>
        </template>
        <button @click="currentPage++" :disabled="currentPage === totalPages" class="btn-ghost text-xs disabled:opacity-30 px-1.5" :aria-label="t('common.next_page')">→</button>
      </div>
    </div>

    <!-- Mobile FAB -->
    <button class="fab" @click="showCreate = true" :title="t('monitors.add')" :aria-label="t('monitors.add')">
      <Plus class="w-6 h-6" />
    </button>

    <CreateMonitorWizard
      v-if="showCreate && !forceLegacyCreate"
      @close="showCreate = false"
      @created="onCreated"
      @switch-advanced="(type) => { advancedInitialType = type ?? null; forceLegacyCreate = true }"
    />
    <CreateMonitorModal
      v-if="showCreate && forceLegacyCreate"
      :initial-type="advancedInitialType"
      @close="() => { showCreate = false; forceLegacyCreate = false; advancedInitialType = null }"
      @created="onCreated"
    />
    <EditMonitorModal v-if="editingMonitor" :monitor="editingMonitor" @close="editingMonitor = null" @updated="onUpdated" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Download, Eye, LayoutGrid, List, Monitor, Pause, PencilLine, Play, Plus, Search, Trash2, Upload, X } from 'lucide-vue-next'
import { useMonitorStore } from '../stores/monitors'
import { useToast } from '../composables/useToast'
import { useMonitorFilters } from '../composables/useMonitorFilters'
import { useMonitorSelection } from '../composables/useMonitorSelection'
import { useMonitorImportExport } from '../composables/useMonitorImportExport'
import { useMonitorDisplay } from '../composables/useMonitorDisplay'
import CreateMonitorModal from '../components/monitors/CreateMonitorModal.vue'
import CreateMonitorWizard from '../components/monitors/CreateMonitorWizard.vue'
import EditMonitorModal from '../components/monitors/EditMonitorModal.vue'
import SparklineCell from '../components/monitors/SparklineCell.vue'
import SkeletonRow from '../components/shared/SkeletonRow.vue'
import EmptyState from '../components/shared/EmptyState.vue'
import BulkActionBar from '../components/shared/BulkActionBar.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const monitorStore = useMonitorStore()
const { success } = useToast()

const monitors = computed(() => monitorStore.monitors)
const loading  = computed(() => monitorStore.loading)
const downCount  = computed(() => monitors.value.filter(m => m._lastStatus === 'down').length)
const errorCount = computed(() => monitors.value.filter(m => ['error', 'timeout'].includes(m._lastStatus)).length)

const showCreate        = ref(false)
const forceLegacyCreate = ref(false)
const advancedInitialType = ref(null)
const editingMonitor = ref(null)
const searchInput   = ref(null)

// ── Search / filters / sorting / pagination / view mode (composable) ─────────
const {
  searchInput_, search, onSearchInput, filterStatus, filterType, filterGroup,
  checkTypes, statusFilters, hasActiveFilters, activeFilterCount, clearFilters,
  viewMode, setViewMode, setSortKey, isSorted, sortIcon,
  currentPage, totalPages, pageNumbers, filteredMonitors, paginatedMonitors,
} = useMonitorFilters(monitors)

// ── Sélection multiple + bulk / per-row actions (composable) ─────────────────
const {
  selectedIds, allVisibleSelected, someVisibleSelected, toggleSelect,
  toggleSelectAll, clearSelection, availableGroups, availableTags,
  onBulkSetGroup, onBulkAddTag, bulkEnable, bulkPause, confirmBulkDelete,
  bulkExportCsv, toggleEnabled, handleDelete,
} = useMonitorSelection(monitors, filteredMonitors)

// Any filter change clears the current selection (the composable already
// resets pagination on its side).
watch([search, filterStatus, filterType, filterGroup], () => {
  clearSelection()
})

// ── Import / export JSON (composable) ────────────────────────────────────────
const { importFileInput, exportMonitors, triggerImport, handleImportFile } =
  useMonitorImportExport()

// ── Row display helpers (composable) ─────────────────────────────────────────
const { dotClass, badgeClass, statusLabel, formatTarget, uptimeColor, responseTimeColor } =
  useMonitorDisplay()

// ── Keyboard shortcuts ─────────────────────────────────────────────────────────
function onKeydown(e) {
  const tag = e.target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

  if (e.key === '/') {
    e.preventDefault()
    searchInput.value?.focus()
  } else if ((e.key === 'n' || e.key === 'N') && !e.ctrlKey && !e.metaKey) {
    showCreate.value = true
  } else if (e.key === 'Escape') {
    if (showCreate.value) showCreate.value = false
    else if (editingMonitor.value) editingMonitor.value = null
  }
}

function onCreated() {
  showCreate.value = false
  monitorStore.fetchAll()
  success(t('monitors.created_success'))
}

function onUpdated() {
  editingMonitor.value = null
  monitorStore.fetchAll()
  success(t('monitors.updated_success'))
}

onMounted(() => {
  monitorStore.fetchAll()
  document.addEventListener('keydown', onKeydown)
  // T1-15: deep-link to create modal via ?create=true (used by `c` hotkey).
  if (route.query.create === 'true') {
    showCreate.value = true
    router.replace({ path: route.path, query: { ...route.query, create: undefined } })
  }
})

watch(() => route.query.create, (v) => {
  if (v === 'true') {
    showCreate.value = true
    router.replace({ path: route.path, query: { ...route.query, create: undefined } })
  }
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>
