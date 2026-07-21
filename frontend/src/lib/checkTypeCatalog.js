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
// Seuls `value` et `icon` restent en dur : ce sont des identifiants et des
// emoji, rien à traduire.
const TYPES = [
  { value: 'http', icon: '🌐' },
  { value: 'keyword', icon: '🔍' },
  { value: 'json_path', icon: '{ }' },
  { value: 'tcp', icon: '🔌' },
  { value: 'dns', icon: '📡' },
  { value: 'scenario', icon: '🎭' },
  { value: 'heartbeat', icon: '⏰' },
  { value: 'udp', icon: '📦' },
  { value: 'smtp', icon: '✉️' },
  { value: 'ping', icon: '🏓' },
  { value: 'domain_expiry', icon: '🔑' },
  { value: 'composite', icon: '🔗' },
]

// Types sans cible saisissable : le champ URL/hôte est masqué (heartbeat est
// piloté par un slug de ping, composite agrège d'autres monitors).
export const TYPES_WITHOUT_TARGET = ['scenario', 'heartbeat', 'composite']

/** Catalogue des types de check, traduit selon la locale courante. */
export function useCheckTypes() {
  const { t } = useI18n()

  const checkTypes = computed(() =>
    TYPES.map(({ value, icon }) => ({
      value,
      icon,
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
