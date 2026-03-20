import { reactive } from 'vue'

const state = reactive({
  visible: false,
  title: '',
  message: '',
  confirmLabel: 'Confirm',
  danger: true,
  resolve: null,
})

export function useConfirm() {
  function confirm({ title, message, confirmLabel = 'Confirm', danger = true } = {}) {
    return new Promise((resolve) => {
      state.visible = true
      state.title = title ?? ''
      state.message = message ?? ''
      state.confirmLabel = confirmLabel
      state.danger = danger
      state.resolve = resolve
    })
  }

  function answer(value) {
    state.visible = false
    state.resolve?.(value)
    state.resolve = null
  }

  return { confirmState: state, confirm, answer }
}
