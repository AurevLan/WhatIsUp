// Clé provide/inject entre les modales monitor (création / édition) et
// `MonitorFormFields`. Passer le formulaire par inject plutôt que par prop
// permet aux champs de le muter via v-model sans déclencher
// `vue/no-mutating-props` — même parti pris que
// `monitors/detail/injectionKeys.js`.

export const MonitorFormKey = Symbol('MonitorForm')
