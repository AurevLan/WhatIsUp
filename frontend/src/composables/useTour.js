import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const FLAG_KEY = 'whatisup_replay_tour'

/**
 * Lightweight tour replay hook.
 *
 * - `?tour=1` in the URL or a localStorage flag means "show the onboarding
 *   wizard again on next mount of a view that supports it" (e.g. DashboardView).
 * - `requestTour()` sets both signals and routes to `/`. Views that host the
 *   wizard read `shouldStartTour()` on mount and call `clearTour()` after
 *   handing control to the wizard.
 */
export function useTour() {
  const route = useRoute()
  const router = useRouter()

  const tourActive = computed(() => {
    const v = route?.query?.tour
    return v === '1' || v === 'true'
  })

  function shouldStartTour() {
    if (tourActive.value) return true
    try {
      return window.localStorage?.getItem(FLAG_KEY) === '1'
    } catch {
      return false
    }
  }

  function clearTour() {
    try {
      window.localStorage?.removeItem(FLAG_KEY)
    } catch {
      // ignore
    }
    if (tourActive.value && router) {
      const { tour, ...rest } = route.query
      void tour
      router.replace({ path: route.path, query: rest })
    }
  }

  function requestTour(target = '/') {
    try {
      window.localStorage?.setItem(FLAG_KEY, '1')
    } catch {
      // ignore
    }
    if (router) {
      router.push({ path: target, query: { tour: '1' } })
    }
  }

  return { tourActive, shouldStartTour, clearTour, requestTour }
}

export const TOUR_STORAGE_KEY = FLAG_KEY
