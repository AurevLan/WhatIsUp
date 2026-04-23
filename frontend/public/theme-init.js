// Apply theme before first paint to prevent flash of wrong theme.
// Loaded as an external script so the nginx CSP can stay strict
// (script-src 'self' — no 'unsafe-inline').
(function () {
  var t = localStorage.getItem('whatisup_theme')
  if (!t) {
    t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  }
  document.documentElement.setAttribute('data-theme', t)
})()
