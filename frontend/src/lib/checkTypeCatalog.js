import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

// Catalogue unique des types de check pour les formulaires monitor.
//
// Il vivait en double dans CreateMonitorModal (chaînes en anglais codées en
// dur) et EditMonitorModal (chaînes en français codées en dur) : selon qu'on
// créait ou éditait un monitor, la même sonde était décrite dans une langue
// différente, sans rapport avec la locale choisie. Les libellés viennent
// désormais de `monitors.check_type.*` (déjà traduits) et les textes longs de
// `create_monitor.types.*`.
//
// `keyword` et `json_path` ont disparu (plan cap v2, 6f-2) : ce n'étaient pas
// des façons différentes de surveiller un service, mais des assertions sur
// une réponse HTTP — elles vivent désormais dans le bloc « Assertions » du
// formulaire http (cf. MonitorFormFields.vue), pas comme tuiles séparées.
//
// Seuls `value` et `icon` restent en dur : ce sont des identifiants et des
// emoji, rien à traduire. `advanced: true` déclasse visuellement une tuile
// (domain_expiry) sans la retirer — elle reste pleinement disponible.
const TYPES = [
  { value: 'http', icon: '🌐' },
  { value: 'tcp', icon: '🔌' },
  { value: 'dns', icon: '📡' },
  { value: 'scenario', icon: '🎭' },
  { value: 'heartbeat', icon: '⏰' },
  { value: 'smtp', icon: '✉️' },
  { value: 'ping', icon: '🏓' },
  { value: 'domain_expiry', icon: '🔑', advanced: true },
]

// Types sans cible saisissable : le champ URL/hôte est masqué (heartbeat est
// piloté par un slug de ping).
export const TYPES_WITHOUT_TARGET = ['scenario', 'heartbeat']

/** Catalogue des types de check, traduit selon la locale courante. */
export function useCheckTypes() {
  const { t } = useI18n()

  const checkTypes = computed(() =>
    TYPES.map(({ value, icon, advanced }) => ({
      value,
      icon,
      advanced: Boolean(advanced),
      label: t(`monitors.check_type.${value}`),
      description: t(`create_monitor.types.${value}.description`),
      urlLabel: t(`create_monitor.types.${value}.url_label`),
      urlPlaceholder: t(`create_monitor.types.${value}.url_placeholder`),
      namePlaceholder: t(`create_monitor.types.${value}.name_placeholder`),
    })),
  )

  /** Entrée courante du catalogue ; retombe sur le premier type si inconnu. */
  function findType(value) {
    return checkTypes.value.find((ct) => ct.value === value) || checkTypes.value[0]
  }

  return { checkTypes, findType }
}
