// Plan cap v2, 6b — replacement for the browser extension recorder:
// `playwright codegen` + import in ScenarioBuilder. This is the parser that
// turns a codegen script into ScenarioBuilder steps.
import { describe, it, expect } from 'vitest'
import { parsePlaywrightScript } from '../src/lib/playwrightImport'

describe('parsePlaywrightScript', () => {
  it('parses a typical codegen script end to end', () => {
    const src = `
import { test, expect } from '@playwright/test';

test('test', async ({ page }) => {
  await page.goto('https://example.com/login');
  await page.getByRole('textbox', { name: 'Email' }).click();
  await page.getByRole('textbox', { name: 'Email' }).fill('user@example.com');
  await page.getByRole('textbox', { name: 'Password' }).fill('hunter2');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL('https://example.com/dashboard');
  await expect(page.getByText('Welcome back')).toBeVisible();
});
`
    const { steps, warnings, statementCount } = parsePlaywrightScript(src)
    expect(statementCount).toBe(7)
    expect(warnings).toEqual([])
    expect(steps.map((s) => s.type)).toEqual([
      'navigate', 'click', 'fill', 'fill', 'click', 'assert_url', 'assert_visible',
    ])
    expect(steps[0].params.url).toBe('https://example.com/login')
    expect(steps[2].params.value).toBe('user@example.com')
    expect(steps[5].params).toEqual({ expected: 'https://example.com/dashboard', mode: 'equals' })
    expect(steps[6].params.selector).toBe('text=Welcome back')
  })

  it('translates getByRole with a name into a CSS selector with :has-text()', () => {
    const src = `await page.getByRole('button', { name: 'Submit' }).click();`
    const { steps } = parsePlaywrightScript(src)
    expect(steps).toHaveLength(1)
    expect(steps[0].type).toBe('click')
    expect(steps[0].params.selector).toContain(':has-text("Submit")')
    expect(steps[0].params.selector).toContain('button')
  })

  it('translates getByTestId into a data-testid attribute selector', () => {
    const src = `await page.getByTestId('submit-btn').click();`
    const { steps } = parsePlaywrightScript(src)
    expect(steps[0].params.selector).toBe('[data-testid="submit-btn"]')
  })

  it('handles direct page.fill(selector, value) calls (no locator chain)', () => {
    const src = `await page.fill('#email', 'user@example.com');`
    const { steps } = parsePlaywrightScript(src)
    expect(steps[0]).toEqual({ type: 'fill', params: { selector: '#email', value: 'user@example.com' } })
  })

  it('handles page.press and page.selectOption', () => {
    const src = `
await page.press('#search', 'Enter');
await page.selectOption('#country', 'FR');
`
    const { steps } = parsePlaywrightScript(src)
    expect(steps[0]).toEqual({ type: 'press', params: { selector: '#search', key: 'Enter' } })
    expect(steps[1]).toEqual({ type: 'select', params: { selector: '#country', value: 'FR' } })
  })

  it('handles page.waitForTimeout', () => {
    const { steps } = parsePlaywrightScript(`await page.waitForTimeout(500);`)
    expect(steps[0]).toEqual({ type: 'wait_time', params: { duration_ms: 500 } })
  })

  it('reports a warning and drops the step for unsupported calls, without throwing', () => {
    const src = `
await page.goto('https://example.com');
await page.setInputFiles('#upload', 'photo.png');
`
    const { steps, warnings, statementCount } = parsePlaywrightScript(src)
    expect(statementCount).toBe(2)
    expect(steps).toHaveLength(1)
    expect(steps[0].type).toBe('navigate')
    expect(warnings.length).toBeGreaterThan(0)
  })

  it('ignores .first()/.last()/.nth() but notes it as a warning', () => {
    const src = `await page.getByRole('listitem').first().click();`
    const { steps, warnings } = parsePlaywrightScript(src)
    expect(steps).toHaveLength(1)
    expect(steps[0].type).toBe('click')
    expect(warnings.some((w) => w.includes('.first()'))).toBe(true)
  })

  it('returns statementCount 0 for a file with no await statements (not a codegen script)', () => {
    const { steps, warnings, statementCount } = parsePlaywrightScript('const x = 1;\nfunction f() {}\n')
    expect(statementCount).toBe(0)
    expect(steps).toEqual([])
    expect(warnings).toEqual([])
  })

  it('does not throw on malformed input', () => {
    expect(() => parsePlaywrightScript('await page.((((;')).not.toThrow()
    expect(() => parsePlaywrightScript('')).not.toThrow()
    expect(() => parsePlaywrightScript(undefined)).not.toThrow()
  })
})
