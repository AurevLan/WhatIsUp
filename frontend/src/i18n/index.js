import { createI18n } from 'vue-i18n'
import en from './en.js'
import fr from './fr.js'

const savedLang = localStorage.getItem('whatisup_lang') || 'en'

export const i18n = createI18n({
  legacy: false,        // Composition API mode
  locale: savedLang,
  fallbackLocale: 'en',
  messages: { en, fr },
})

// Keep <html lang> in sync from the very first paint (WCAG 3.1.1) — setLocale
// only covers later switches.
document.documentElement.lang = savedLang

export function setLocale(lang) {
  i18n.global.locale.value = lang
  localStorage.setItem('whatisup_lang', lang)
  document.documentElement.lang = lang
}

export function getLocale() {
  return i18n.global.locale.value
}
