<template>
  <div class="page-body">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold" style="color:var(--text-1)">{{ t('nav.groups') }}</h1>
        <p class="mt-1 text-sm" style="color:var(--text-3)">{{ t('groups.subtitle') }}</p>
      </div>
      <button @click="showCreate = true" class="btn-primary">+ {{ t('groups.create') }}</button>
    </div>

    <!-- Skeleton loader -->
    <div v-if="loading" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="i in 6" :key="i" class="card">
        <div class="space-y-3">
          <div class="skeleton-line w-2/3" />
          <div class="skeleton-line w-full" style="height:.5rem" />
          <div class="flex gap-2 mt-4">
            <div class="skeleton-line w-16" style="border-radius:99px;height:1.25rem" />
            <div class="skeleton-line w-12" style="border-radius:99px;height:1.25rem" />
          </div>
        </div>
      </div>
    </div>

    <EmptyState
      v-else-if="groups.length === 0"
      :title="t('groups.empty')"
      :text="t('empty.groups_text')"
      :cta-label="t('groups.create')"
      doc-href="https://github.com/AurevLan/whatisup#groups"
      @cta="showCreate = true"
    >
      <template #icon><Layers :size="22" /></template>
    </EmptyState>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="(group, idx) in groups" :key="group.id"
        class="card stagger-item"
        :style="{ animationDelay: idx * 40 + 'ms' }">
        <div class="flex items-start justify-between">
          <div>
            <h3 class="font-semibold" style="color:var(--text-1)">{{ group.name }}</h3>
            <p class="text-sm mt-1" style="color:var(--text-3)">{{ group.description || t('groups.no_description') }}</p>
          </div>
          <button @click="deleteGroup(group)" class="btn-ghost px-2 py-1 text-xs" style="color:var(--text-3)">
            <Trash2 :size="14" />
          </button>
        </div>
        <div class="mt-4 flex items-center gap-2 flex-wrap">
          <span v-for="tag in group.tags" :key="tag.id"
            class="px-2 py-0.5 text-xs rounded-full bg-blue-900/50 text-blue-300"
            :style="tag.color ? `background-color: ${tag.color}22; color: ${tag.color}` : ''">
            {{ tag.name }}
          </span>
        </div>
        <div class="mt-4 pt-4 flex items-center justify-between" style="border-top: 1px solid var(--border)">
          <span v-if="group.public_slug" class="text-xs font-mono" style="color:var(--text-3)">/status/{{ group.public_slug }}</span>
          <span v-else class="text-xs" style="color:var(--text-3)">{{ t('groups.private') }}</span>
          <router-link :to="`/groups/${group.id}`" class="text-xs" style="color:var(--accent)">{{ t('groups.manage') }} →</router-link>
        </div>
      </div>
    </div>

    <CreateGroupModal v-if="showCreate" @close="showCreate = false" @created="loadGroups" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Layers, Trash2 } from 'lucide-vue-next'
import { groupsApi } from '../api/monitors'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import CreateGroupModal from '../components/monitors/CreateGroupModal.vue'
import EmptyState from '../components/shared/EmptyState.vue'

const { t } = useI18n()
const { success } = useToast()
const { confirm } = useConfirm()

const groups = ref([])
const loading = ref(true)
const showCreate = ref(false)

async function loadGroups() {
  showCreate.value = false
  try {
    const { data } = await groupsApi.list()
    groups.value = data
  } finally {
    loading.value = false
  }
}

async function deleteGroup(group) {
  const ok = await confirm({
    title: t('groups.confirm_delete', { name: group.name }),
    confirmLabel: t('common.delete'),
  })
  if (!ok) return
  await groupsApi.delete(group.id)
  success(t('groups.deleted'))
  await loadGroups()
}

onMounted(loadGroups)
</script>
