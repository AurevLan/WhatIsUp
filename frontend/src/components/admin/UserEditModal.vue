<template>
  <BaseModal
    :model-value="modelValue && !!user"
    :title="user ? t('admin.edit_user_title', { name: user.username }) : ''"
    @update:model-value="$event || close()"
  >
        <form @submit.prevent="submitEdit" class="space-y-4">
          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('admin.col_email') }}</label>
            <input v-model="editForm.email" type="email" class="input w-full" />
          </div>
          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('admin.label_full_name') }}</label>
            <input v-model="editForm.full_name" type="text" class="input w-full" />
          </div>
          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('admin.label_new_password') }}</label>
            <input v-model="editForm.password" type="password" class="input w-full" minlength="8" />
          </div>

          <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-(--bg-surface-2) border border-(--border)">
            <div>
              <div class="text-sm text-(--text-2) font-medium">{{ t('admin.toggle_active') }}</div>
            </div>
            <button
              type="button"
              @click="editForm.is_active = !editForm.is_active"
              :aria-label="t('admin.toggle_active')"
              :class="editForm.is_active ? 'bg-(--up)' : 'bg-(--bg-surface-3)'"
              class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
            >
              <span
                :class="editForm.is_active ? 'translate-x-5' : 'translate-x-1'"
                class="absolute top-0.5 w-5 h-5 bg-(--text-1) rounded-full shadow transition-transform"
              />
            </button>
          </div>

          <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-(--bg-surface-2) border border-(--border)">
            <div>
              <div class="text-sm text-(--text-2) font-medium">{{ t('admin.perm_can_create_monitors') }}</div>
            </div>
            <button
              type="button"
              @click="editForm.can_create_monitors = !editForm.can_create_monitors"
              :aria-label="t('admin.perm_can_create_monitors')"
              :class="editForm.can_create_monitors ? 'bg-(--accent)' : 'bg-(--bg-surface-3)'"
              class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
            >
              <span
                :class="editForm.can_create_monitors ? 'translate-x-5' : 'translate-x-1'"
                class="absolute top-0.5 w-5 h-5 bg-(--text-1) rounded-full shadow transition-transform"
              />
            </button>
          </div>

          <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-(--bg-surface-2) border border-(--border)">
            <div>
              <div class="text-sm text-(--text-2) font-medium">{{ t('admin.perm_is_admin') }}</div>
              <div class="text-xs text-(--text-3)">{{ t('admin.perm_is_admin_desc_short') }}</div>
            </div>
            <button
              type="button"
              @click="editForm.is_superadmin = !editForm.is_superadmin"
              :aria-label="t('admin.perm_is_admin')"
              :class="editForm.is_superadmin ? 'bg-(--accent)' : 'bg-(--bg-surface-3)'"
              class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
            >
              <span
                :class="editForm.is_superadmin ? 'translate-x-5' : 'translate-x-1'"
                class="absolute top-0.5 w-5 h-5 bg-(--text-1) rounded-full shadow transition-transform"
              />
            </button>
          </div>

          <div v-if="editError" class="text-(--down) text-sm">{{ editError }}</div>

          <div class="flex justify-end gap-3 pt-2">
            <button type="button" @click="close" class="btn-secondary">{{ t('common.cancel') }}</button>
            <button type="submit" class="btn-primary" :disabled="submitting">
              {{ submitting ? t('admin.saving') : t('admin.save_btn') }}
            </button>
          </div>
        </form>
  </BaseModal>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { adminApi } from '../../api/admin'
import BaseModal from '../BaseModal.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  user: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const { t } = useI18n()

const submitting = ref(false)
const editError = ref('')
const editForm = ref({
  email: '',
  full_name: '',
  password: '',
  is_active: true,
  can_create_monitors: false,
  is_superadmin: false,
})

watch(() => props.modelValue, (open) => {
  if (open && props.user) {
    editForm.value = {
      email: props.user.email,
      full_name: props.user.full_name || '',
      password: '',
      is_active: props.user.is_active,
      can_create_monitors: props.user.can_create_monitors,
      is_superadmin: props.user.is_superadmin,
    }
    editError.value = ''
  }
})

function close() {
  emit('update:modelValue', false)
}

async function submitEdit() {
  submitting.value = true
  editError.value = ''
  try {
    const payload = { ...editForm.value }
    if (!payload.password) delete payload.password
    if (!payload.full_name) delete payload.full_name
    await adminApi.updateUser(props.user.id, payload)
    emit('update:modelValue', false)
    emit('saved')
  } catch (e) {
    editError.value = e.response?.data?.detail || t('admin.error_edit')
  } finally {
    submitting.value = false
  }
}
</script>
