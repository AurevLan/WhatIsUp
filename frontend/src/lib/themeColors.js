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

// ── Échelle de santé partagée ────────────────────────────────────────────
// Un uptime se lit partout avec les mêmes paliers (≥99 sain, ≥90 dégradé,
// sinon en panne). Le barème vivait en double dans useMonitorDisplay et en
// triple dans ProbeMap (classe de pastille, classe de texte, fill Leaflet).

/** Palier de santé d'un pourcentage d'uptime : up / warn / down / unknown. */
export function uptimeLevel(percent) {
  if (percent == null) return 'unknown'
  if (percent >= 99) return 'up'
  if (percent >= 90) return 'warn'
  return 'down'
}

// Classes littérales (jamais construites par concaténation) : le scanner
// Tailwind v4 ne détecte que les noms de classe présents tels quels dans les
// sources — une interpolation produirait du CSS manquant à la compilation.
const LEVEL_TEXT = {
  up: 'text-(--up)',
  warn: 'text-(--warn)',
  down: 'text-(--down)',
  unknown: 'text-(--text-3)',
}
const LEVEL_BG = {
  up: 'bg-(--up)',
  warn: 'bg-(--warn)',
  down: 'bg-(--down)',
  unknown: 'bg-(--text-3)',
}
// Fallbacks hex requis pour jsdom (cf. note en tête de fichier).
const LEVEL_HEX = {
  up: ['--up', '#8fc09e'],
  warn: ['--warn', '#dcab4a'],
  down: ['--down', '#e8876b'],
  unknown: ['--text-3', '#9a8e76'],
}

/** Classe texte tokenisée pour un palier de santé. */
export function levelTextClass(level) {
  return LEVEL_TEXT[level] ?? LEVEL_TEXT.unknown
}

/** Classe de fond tokenisée (pastilles) pour un palier de santé. */
export function levelBgClass(level) {
  return LEVEL_BG[level] ?? LEVEL_BG.unknown
}

/** Couleur résolue (SVG / marqueurs Leaflet) pour un palier de santé. */
export function levelColor(level) {
  const [token, fallback] = LEVEL_HEX[level] ?? LEVEL_HEX.unknown
  return cssVar(token) || fallback
}
