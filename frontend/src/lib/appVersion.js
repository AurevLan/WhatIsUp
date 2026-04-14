// Single source of truth for the displayed app version.
//
// `__APP_VERSION__` is a Vite compile-time define that reads
// `frontend/package.json#version` at build time (see vite.config.js).
// Visible in:
//   - the sidebar footer next to the user's role
//   - the "About" card in Settings
//   - any debug overlay
//
// Updating the version is therefore a one-line change to package.json —
// no more hardcoded constants drifting out of sync.

/* global __APP_VERSION__ */
export const APP_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'dev'
