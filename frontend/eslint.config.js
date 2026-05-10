// ESLint flat config (v9+). The legacy .eslintrc format is not supported by
// ESLint 10. Tailored for a Vue 3 + Vite + Pinia stack — no TypeScript.

import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'android/**',
      'public/**',
      'src/sw/**',
      'coverage/**',
    ],
  },
  js.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node,
        // Vite-injected at build time
        __APP_VERSION__: 'readonly',
      },
    },
    rules: {
      // Vue 3 conventions: single-word file names are fine for views/composables.
      'vue/multi-word-component-names': 'off',
      // Project style: keep self-closing freedom for now.
      'vue/html-self-closing': 'off',
      // Disable Vue's stylistic formatting rules — they would force a massive
      // cosmetic diff across 77 existing files. Prettier or a dedicated
      // formatting pass should own this, not the lint pre-commit.
      'vue/max-attributes-per-line': 'off',
      'vue/first-attribute-linebreak': 'off',
      'vue/html-closing-bracket-newline': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/multiline-html-element-content-newline': 'off',
      'vue/html-indent': 'off',
      'vue/attributes-order': 'off',
      'vue/order-in-components': 'off',
      // Allow leading-underscore unused vars (e.g. `_unused`).
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // Empty catch blocks are intentional in many places (best-effort flows).
      // Downgrade so they don't fail the lint; review case-by-case if needed.
      'no-empty': ['warn', { allowEmptyCatch: true }],
      // v-html on component is used for rendered markdown — accepted with care.
      'vue/no-v-text-v-html-on-component': 'warn',
      // Detail tabs receive `:state="composableReturn"` and mutate state.x.value
      // by design — disable the strict mutating-props check for that pattern.
      'vue/no-mutating-props': 'warn',
      // We don't yet wire ES2025 Error.cause everywhere — downgrade for now.
      'preserve-caught-error': 'warn',
      // Console is fine (we silence error/warn manually elsewhere).
      'no-console': 'off',
    },
  },
  {
    // Test files: relax a few rules.
    files: ['tests/**/*.{js,vue}'],
    languageOptions: {
      globals: {
        ...globals.jest,
        ...globals.node,
      },
    },
    rules: {
      'no-unused-vars': 'off',
      'vue/one-component-per-file': 'off',
    },
  },
]
