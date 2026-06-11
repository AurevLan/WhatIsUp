<template>
  <Teleport to="body">
    <div v-if="modelValue" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="close">
      <div class="card w-full max-w-md" @click.stop>
        <div class="flex justify-between items-center mb-6">
          <h2 class="text-lg font-semibold text-white">{{ t('admin.create_user_title') }}</h2>
          <button @click="close" class="text-gray-500 hover:text-gray-300">
            <X class="w-5 h-5" />
          </button>
        </div>

        <form @submit.prevent="submitCreate" class="space-y-4">
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('admin.label_email') }}</label>
            <input v-model="createForm.email" type="email" class="input w-full" required />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('admin.label_username') }}</label>
            <input v-model="createForm.username" type="text" class="input w-full" :placeholder="t('admin.placeholder_username')" />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('admin.label_full_name') }}</label>
            <input v-model="createForm.full_name" type="text" class="input w-full" />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('admin.label_password') }}</label>
            <input v-model="createForm.password" type="password" class="input w-full" required minlength="8" />
          </div>
          <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/60 border border-gray-700/50">
            <div>
              <div class="text-sm text-gray-300 font-medium">{{ t('admin.perm_can_create_monitors') }}</div>
              <div class="text-xs text-gray-500">{{ t('admin.perm_can_create_monitors_desc') }}</div>
            </div>
            <button
              type="button"
              @click="createForm.can_create_monitors = !createForm.can_create_monitors"
              :class="createForm.can_create_monitors ? 'bg-blue-600' : 'bg-gray-700'"
              class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
            >
              <span
                :class="createForm.can_create_monitors ? 'translate-x-5' : 'translate-x-1'"
                class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
              />
            </button>
          </div>

          <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/60 border border-gray-700/50">
            <div>
              <div class="text-sm text-gray-300 font-medium">{{ t('admin.perm_is_admin') }}</div>
              <div class="text-xs text-gray-500">{{ t('admin.perm_is_admin_desc') }}</div>
            </div>
            <button
              type="button"
              @click="createForm.is_superadmin = !createForm.is_superadmin"
              :class="createForm.is_superadmin ? 'bg-purple-600' : 'bg-gray-700'"
              class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
            >
              <span
                :class="createForm.is_superadmin ? 'translate-x-5' : 'translate-x-1'"
                class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
              />
            </button>
          </div>

          <div v-if="createError" class="text-red-400 text-sm">{{ createError }}</div>

          <div class="flex justify-end gap-3 pt-2">
            <button type="button" @click="close" class="btn-secondary">{{ t('common.cancel') }}</button>
            <button type="submit" class="btn-primary" :disabled="submitting">
              {{ submitting ? t('admin.creating') : t('admin.create_btn') }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { adminApi } from '../../api/admin'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const { t } = useI18n()

const submitting = ref(false)
const createError = ref('')
const createForm = ref({
  email: '',
  username: '',
  full_name: '',
  password: '',
  can_create_monitors: false,
  is_superadmin: false,
})

watch(() => props.modelValue, (open) => {
  if (open) {
    createForm.value = { email: '', username: '', full_name: '', password: '', can_create_monitors: false, is_superadmin: false }
    createError.value = ''
  }
})

function close() {
  emit('update:modelValue', false)
}

async function submitCreate() {
  submitting.value = true
  createError.value = ''
  try {
    const payload = { ...createForm.value }
    if (!payload.username) delete payload.username
    if (!payload.full_name) delete payload.full_name
    await adminApi.createUser(payload)
    emit('update:modelValue', false)
    emit('saved')
  } catch (e) {
    createError.value = e.response?.data?.detail || t('admin.error_create')
  } finally {
    submitting.value = false
  }
}
</script>
