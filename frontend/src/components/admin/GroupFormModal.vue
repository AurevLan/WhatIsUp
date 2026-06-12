<template>
  <!-- ===== MODAL CREATE GROUP ===== -->
  <BaseModal
    :model-value="modelValue && !group"
    :title="t('admin.create_group_title')"
    @update:model-value="$event || close()"
  >
        <form @submit.prevent="submitCreateGroup" class="space-y-4">
          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('admin.label_group_name') }}</label>
            <input v-model="groupForm.name" type="text" class="input w-full" required maxlength="255" />
          </div>
          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('admin.label_description') }}</label>
            <input v-model="groupForm.description" type="text" class="input w-full" />
          </div>
          <div v-if="groupError" class="text-(--down) text-sm">{{ groupError }}</div>
          <div class="flex justify-end gap-3 pt-2">
            <button type="button" @click="close" class="btn-secondary">{{ t('common.cancel') }}</button>
            <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? t('admin.creating') : t('admin.create_btn') }}</button>
          </div>
        </form>
  </BaseModal>

  <!-- ===== MODAL EDIT GROUP ===== -->
  <BaseModal
    :model-value="modelValue && !!group"
    :title="group ? t('admin.edit_group_title', { name: group.name }) : ''"
    @update:model-value="$event || close()"
  >
        <form @submit.prevent="submitEditGroup" class="space-y-4">
          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('common.name') }}</label>
            <input v-model="groupForm.name" type="text" class="input w-full" maxlength="255" />
          </div>
          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('admin.label_description') }}</label>
            <input v-model="groupForm.description" type="text" class="input w-full" />
          </div>
          <div v-if="groupError" class="text-(--down) text-sm">{{ groupError }}</div>
          <div class="flex justify-end gap-3 pt-2">
            <button type="button" @click="close" class="btn-secondary">{{ t('common.cancel') }}</button>
            <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? t('admin.saving') : t('admin.save_btn') }}</button>
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
  // null = mode création ; objet = mode édition
  group: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const { t } = useI18n()

const submitting = ref(false)
const groupError = ref('')
const groupForm = ref({ name: '', description: '' })

watch(() => props.modelValue, (open) => {
  if (open) {
    groupForm.value = props.group
      ? { name: props.group.name, description: props.group.description || '' }
      : { name: '', description: '' }
    groupError.value = ''
  }
})

function close() {
  emit('update:modelValue', false)
}

async function submitCreateGroup() {
  submitting.value = true
  groupError.value = ''
  try {
    const payload = { name: groupForm.value.name }
    if (groupForm.value.description) payload.description = groupForm.value.description
    await adminApi.createProbeGroup(payload)
    emit('update:modelValue', false)
    emit('saved')
  } catch (e) {
    groupError.value = e.response?.data?.detail || t('admin.error_create')
  } finally {
    submitting.value = false
  }
}

async function submitEditGroup() {
  submitting.value = true
  groupError.value = ''
  try {
    const payload = {}
    if (groupForm.value.name) payload.name = groupForm.value.name
    if (groupForm.value.description !== undefined) payload.description = groupForm.value.description || null
    await adminApi.updateProbeGroup(props.group.id, payload)
    emit('update:modelValue', false)
    emit('saved')
  } catch (e) {
    groupError.value = e.response?.data?.detail || t('admin.error_edit')
  } finally {
    submitting.value = false
  }
}
</script>
