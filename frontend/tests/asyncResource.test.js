import { describe, it, expect } from 'vitest'

import { useAsyncResource } from '../src/composables/useAsyncResource'

// B3 — le composable existe pour une seule raison : empêcher qu'une réponse
// lente issue d'un filtre précédent n'écrase le résultat du filtre courant.
// Ces tests reproduisent l'inversion en contrôlant l'ordre de résolution.

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('useAsyncResource', () => {
  it('applies the result of a single request', async () => {
    const { loading, run } = useAsyncResource()
    let applied = null
    expect(loading.value).toBe(false)

    await run(
      async () => 'data',
      (d) => { applied = d },
    )

    expect(applied).toBe('data')
    expect(loading.value).toBe(false)
  })

  it('ignores a stale response that lands after a newer one', async () => {
    const { run } = useAsyncResource()
    const slow = deferred()
    const fast = deferred()
    const applied = []

    const first = run(() => slow.promise, (d) => applied.push(d))
    const second = run(() => fast.promise, (d) => applied.push(d))

    // La seconde requête répond d'abord, la première (périmée) ensuite.
    fast.resolve('30 days')
    await second
    slow.resolve('7 days')
    await first

    expect(applied).toEqual(['30 days'])
  })

  it('returns undefined for the superseded call', async () => {
    const { run } = useAsyncResource()
    const slow = deferred()
    const fast = deferred()

    const first = run(() => slow.promise)
    const second = run(() => fast.promise)

    fast.resolve('fresh')
    slow.resolve('stale')

    expect(await first).toBeUndefined()
    expect(await second).toBe('fresh')
  })

  it('keeps loading true while a newer request is still in flight', async () => {
    const { loading, run } = useAsyncResource()
    const slow = deferred()
    const fast = deferred()

    const first = run(() => slow.promise)
    const second = run(() => fast.promise)
    expect(loading.value).toBe(true)

    // La requête dépassée se termine : elle ne doit pas éteindre le spinner
    // de celle qui l'a remplacée.
    slow.resolve('stale')
    await first
    expect(loading.value).toBe(true)

    fast.resolve('fresh')
    await second
    expect(loading.value).toBe(false)
  })

  it('clears loading when the request fails, and lets the error through', async () => {
    const { loading, run } = useAsyncResource()
    const boom = new Error('network down')

    await expect(run(async () => { throw boom })).rejects.toBe(boom)
    expect(loading.value).toBe(false)
  })

  it('does not apply the result when the fetcher rejects', async () => {
    const { run } = useAsyncResource()
    let applied = null

    await run(async () => { throw new Error('nope') }, (d) => { applied = d }).catch(() => {})

    expect(applied).toBeNull()
  })
})
