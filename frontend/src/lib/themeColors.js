// VELOURS design system — couleurs lues à runtime depuis les CSS custom
// properties, pour que les couleurs construites en JavaScript (ApexCharts,
// marqueurs Leaflet, SVG) suivent le thème `data-theme`.
//
// Note jsdom : getComputedStyle ne résout pas les custom properties et
// retourne '' — chaque appelant DOIT prévoir un fallback (`cssVar(name) ||
// '#hex'`) pour ne pas casser les tests.

/** Couleur du design system lue à runtime (suit le thème data-theme). */
export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/** Variante translucide utilisable en fill/style inline (SVG + HTML). */
export function withAlpha(color, alpha) {
  return `color-mix(in srgb, ${color} ${Math.round(alpha * 100)}%, transparent)`
}
