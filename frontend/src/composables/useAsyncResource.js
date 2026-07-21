import { ref } from 'vue'

/**
 * Chargement asynchrone protégé contre les réponses périmées.
 *
 * Ce composable n'existe pas pour raccourcir le `try / finally` — le motif
 * `loading.value = true … finally { loading.value = false }` est lisible et,
 * sur les 75 sites du frontend, aucun n'oublie de remettre le drapeau à zéro.
 * Il existe pour un défaut que la répétition ne corrige pas : les vues dont un
 * filtre relance le chargement peuvent recevoir leurs réponses dans le
 * désordre.
 *
 * Concrètement, sur `watch([statusFilter, daysFilter], load)` : l'utilisateur
 * passe de « 7 jours » à « 30 jours », la première requête est plus lente que
 * la seconde et arrive après elle — la liste affiche alors les 7 jours alors
 * que le filtre indique 30. Rien dans le code appelant ne le détecte, et le
 * bug est d'autant plus difficile à reproduire qu'il dépend du réseau.
 *
 * `run()` numérote les appels et n'applique le résultat que si aucun appel
 * plus récent n'a démarré entre-temps. Le drapeau `loading` suit la même
 * règle : seule la requête encore en tête a le droit de l'éteindre, sinon une
 * réponse périmée masquerait le spinner d'une requête toujours en vol.
 *
 * ```js
 * const { loading, run } = useAsyncResource()
 * const load = () => run(
 *   () => api.get('/incidents/', { params }),
 *   ({ data }) => { incidents.value = data },
 * )
 * ```
 */
export function useAsyncResource({ initialLoading = false } = {}) {
  // `initialLoading: true` pour les vues qui affichent leur squelette dès le
  // premier rendu, avant même que le chargement monté ne démarre.
  const loading = ref(initialLoading)
  let sequence = 0

  /**
   * @param fetcher  Fonction asynchrone effectuant la requête.
   * @param apply    Appliqué au résultat, seulement si la requête est toujours
   *                 la plus récente. Omettre pour un simple suivi de `loading`.
   * @returns        Le résultat du fetcher, ou `undefined` s'il est périmé.
   */
  async function run(fetcher, apply) {
    const mine = ++sequence
    loading.value = true
    try {
      const result = await fetcher()
      if (mine !== sequence) return undefined
      if (apply) apply(result)
      return result
    } finally {
      // Une requête dépassée ne doit pas éteindre le spinner de sa remplaçante.
      if (mine === sequence) loading.value = false
    }
  }

  return { loading, run }
}
