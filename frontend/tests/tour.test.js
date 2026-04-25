import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useTour, TOUR_STORAGE_KEY } from '../src/composables/useTour'

let mockRoute = { query: {}, path: '/' }
const mockRouter = { push: vi.fn(), replace: vi.fn() }

vi.mock('vue-router', () => ({
  useRoute: () => mockRoute,
  useRouter: () => mockRouter,
}))

beforeEach(() => {
  mockRoute = { query: {}, path: '/' }
  mockRouter.push.mockReset()
  mockRouter.replace.mockReset()
  try { window.localStorage.clear() } catch { /* ignore */ }
})

describe('useTour', () => {
  it('tourActive is false on plain URL', () => {
    const { tourActive } = useTour()
    expect(tourActive.value).toBe(false)
  })

  it('tourActive picks up ?tour=1', () => {
    mockRoute = { query: { tour: '1' }, path: '/' }
    const { tourActive } = useTour()
    expect(tourActive.value).toBe(true)
  })

  it('tourActive accepts ?tour=true', () => {
    mockRoute = { query: { tour: 'true' }, path: '/' }
    const { tourActive } = useTour()
    expect(tourActive.value).toBe(true)
  })

  it('shouldStartTour returns true when storage flag set', () => {
    window.localStorage.setItem(TOUR_STORAGE_KEY, '1')
    const { shouldStartTour } = useTour()
    expect(shouldStartTour()).toBe(true)
  })

  it('shouldStartTour returns false when nothing set', () => {
    const { shouldStartTour } = useTour()
    expect(shouldStartTour()).toBe(false)
  })

  it('requestTour writes flag and routes to / with ?tour=1', () => {
    const { requestTour } = useTour()
    requestTour()
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBe('1')
    expect(mockRouter.push).toHaveBeenCalledWith({ path: '/', query: { tour: '1' } })
  })

  it('requestTour respects target argument', () => {
    const { requestTour } = useTour()
    requestTour('/monitors')
    expect(mockRouter.push).toHaveBeenCalledWith({ path: '/monitors', query: { tour: '1' } })
  })

  it('clearTour removes flag and strips ?tour=1 from query', () => {
    window.localStorage.setItem(TOUR_STORAGE_KEY, '1')
    mockRoute = { query: { tour: '1', other: 'x' }, path: '/foo' }
    const { clearTour } = useTour()
    clearTour()
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBeNull()
    expect(mockRouter.replace).toHaveBeenCalledWith({ path: '/foo', query: { other: 'x' } })
  })

  it('clearTour does not call replace when no tour query', () => {
    window.localStorage.setItem(TOUR_STORAGE_KEY, '1')
    const { clearTour } = useTour()
    clearTour()
    expect(mockRouter.replace).not.toHaveBeenCalled()
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBeNull()
  })
})
