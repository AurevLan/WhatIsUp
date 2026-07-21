# Plan — Refonte design « VELOURS » (doux/premium)

> Feu vert utilisateur 2026-06-13 (fin de l'exclusivité stabilisation pour ce chantier).
> Direction choisie après comparaison de 2 protos (branche locale `proto/dashboard-redesign`) : voir mémoire `project_design_direction_velours.md`.
> Référence visuelle : `frontend/src/views/proto/DashboardProtoSoft.vue` (branche proto).

## Identité

- **Typo display** : Fraunces (variable, roman+italic, OFL) — hero, gros chiffres, h1/h2. Corps : Plus Jakarta Sans (inchangé). Données chiffrées : tabular-nums.
- **Palette light (défaut clair)** : ivoire `#f6f2ea`, cartes `#fffdf9`, encre `#211f1a`, or `#a87b1f`, sauge `#4e7d5b` (up), terracotta `#b9543e` (down).
- **Palette dark (variant « encre »)** : fonds bruns chauds (`#15130e` → `#2c2719`), texte ivoire, accents éclaircis pour AA.
- **Matière** : radius 18px cartes / 12px contrôles, ombres douces réelles double-couche, voiles radiaux or/sauge + grain léger sur le fond, entrée en cascade `vel-rise`.
- Le dégradé bleu-violet et l'accent bleu disparaissent.

## Contraintes dures

- Ratios AA (≥4.5:1 petit texte) vérifiés par script sur chaque token texte×fond, documentés en commentaire dans style.css (comme A11Y-5).
- Gate axe + garde-fou BaseModal + parité i18n restent verts.
- Fraunces auto-hébergée (`frontend/public/fonts/`, licence OFL) — pas de CDN tiers.
- Les deux thèmes restent fonctionnels (toggle existant `data-theme` conservé).

## Phases

### V-0 — Fondation — FAIT (PR #182)
- [x] Fraunces woff2 variable (roman + italic) self-hosted + `@font-face` + OFL.txt
- [x] Tokens `:root` (dark encre) + `[data-theme="light"]` (ivoire) redéfinis dans style.css, ratios AA calculés et commentés
- [x] Classes composants ajustées : `.card`, `.btn-*`, `.badge-*`, `.input`, `.modal-panel`, scrollbars, focus ring
- [x] Overrides light existants (badges, boutons) re-palettés

### V-1 — Dashboard — FAIT (PR #182)
- [x] Port du proto en `DashboardView.vue` réel : hero verdict + ruban stats + incidents + sondes offline + grille services (sparklines SVG) + ProbeMap dans une carte VELOURS
- [x] Onboarding wizard conservé tel quel
- [x] Clés i18n EN + FR (hero, pills, libellés) — pas de FR en dur
- [x] Fonctionne dans les 2 thèmes + DashboardView ajouté au gate axe

### V-2 — Sweep des vues — FAIT (PR #182, commit 3a8c2df)
- [x] ~2300 occurrences converties (24 vues + ~70 composants, scoped CSS inclus) — le thème clair fonctionne enfin partout
- [x] font-display : h1 des 22 vues, grades TLS, hero status page, stats/SLO/metrics
- [x] PublicPageView alignée (accent_color custom runtime préservé)

### V-3 — Polish — FAIT (PR #182, commit f231b76)
- [x] Compteurs animés dashboard (reduced-motion respecté) ; hover lift homogène (V-0) ; transitions directionnelles abandonnées (gadget)
- [x] Favicon SVG (barres uptime sauge/or sur encre) + fallback .ico
- [ ] FEATURES.md §7 + captures README → après merge (reste le seul item ouvert)

## Hors scope
- Refonte mobile/responsive (chantier séparé du plan ergonomie)
- Changement de structure des vues (le redesign est visuel, pas IA/UX flows)

## Reliquats identifiés en V-2 (→ V-3)
- Couleurs JS runtime : ApexCharts (`SparklineCell`, `MetricsDashboard`, `useMonitorCharts.PROBE_COLORS`), marqueurs/popups Leaflet (`ProbeMap.statusFill/buildPopup`, `IncidentPlaybackMap`, `ProbesView`), `DependencyGraph.STATUS_COLORS`, marques canaux `ChannelChip` (légitimes, à garder).
- Pas de token `--error` (orange) : états error fusionnés sur `--down`/`--warn` — créer le token ou assumer la fusion.
- Popup Leaflet : wrapper thémé mais textes inline encore slate (pâles en ivoire).

### V-3 — complément livré
- [x] Couleurs JS runtime → tokens via `lib/themeColors.js` (cssVar/withAlpha, fallbacks jsdom) : ApexCharts, Leaflet (markers/popups/divIcons), DependencyGraph, useMonitorCharts, useMonitorMap
- [x] PROBE_COLORS : palette chaude 8 teintes
- [x] Filtre tuiles Leaflet scoped à .leaflet-tile-pane (chaud en sombre, aucun en clair)
- [x] Token `--error` (orange brûlé AA 6.9/4.9:1) → .badge-error + CommandPalette
