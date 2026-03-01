<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <h1 class="text-2xl font-bold text-white">Groups</h1>
      <button @click="showCreate = true" class="btn-primary">+ New Group</button>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="group in groups" :key="group.id" class="card">
        <div class="flex items-start justify-between">
          <div>
            <h3 class="font-semibold text-white">{{ group.name }}</h3>
            <p class="text-sm text-gray-400 mt-1">{{ group.description || 'No description' }}</p>
          </div>
          <button @click="deleteGroup(group)" class="text-gray-600 hover:text-red-400 transition-colors">✕</button>
        </div>
        <div class="mt-4 flex items-center gap-2 flex-wrap">
          <span v-for="tag in group.tags" :key="tag.id"
            class="px-2 py-0.5 text-xs rounded-full bg-blue-900/50 text-blue-300"
            :style="tag.color ? `background-color: ${tag.color}22; color: ${tag.color}` : ''">
            {{ tag.name }}
          </span>
        </div>
        <div class="mt-4 pt-4 border-t border-gray-800 flex items-center justify-between">
          <span v-if="group.public_slug" class="text-xs text-gray-500 font-mono">/status/{{ group.public_slug }}</span>
          <span v-else class="text-xs text-gray-600">Private</span>
          <router-link :to="`/groups`" class="text-xs text-blue-400 hover:underline">Manage →</router-link>
        </div>
      </div>

      <div v-if="groups.length === 0" class="col-span-full text-center text-gray-500 py-16">
        No groups yet. Groups let you organize monitors and create public status pages.
      </div>
    </div>

    <CreateGroupModal v-if="showCreate" @close="showCreate = false" @created="loadGroups" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { groupsApi } from '../api/monitors'
import CreateGroupModal from '../components/monitors/CreateGroupModal.vue'

const groups = ref([])
const showCreate = ref(false)

async function loadGroups() {
  showCreate.value = false
  const { data } = await groupsApi.list()
  groups.value = data
}

async function deleteGroup(group) {
  if (confirm(`Delete group "${group.name}"?`)) {
    await groupsApi.delete(group.id)
    await loadGroups()
  }
}

onMounted(loadGroups)
</script>
