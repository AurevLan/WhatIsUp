# Plan — Responsive / mobile des vues (post-VELOURS)

> Feu vert utilisateur 2026-06-15 (prolongement naturel de la refonte VELOURS v1.13.0).
> Le redesign VELOURS était **visuel uniquement** (tokens, typo, matière) ; il n'a pas touché le layout.
> Cible double : navigateur mobile **et** app native Android (Capacitor 7, `io.github.aurevlan.whatisup`).

## Constat de départ (audit 2026-06-15)

- **Shell déjà responsive** ✅ : `AppLayout` a drawer off-canvas (`< 1024px`), hamburger, overlay cliquable, body scroll-lock (`watch(sidebarOpen)`), FAB masqué ≥640px. Topbar (lang/thème/statut) OK. → **hors scope, ne pas retoucher**.
- **Tailwind v4** (`@import "tailwindcss"`, `@tailwindcss/vite`) : breakpoints par défaut `sm:640 / md:768 / lg:1024 / xl:1280`. Pas de `tailwind.config.js`. Approche = **mobile-first** (base = mobile, `md:`/`lg:` pour élargir).
- **12 vues sur 23 sans aucun breakpoint** : `AuditView`, `DashboardView`, `DependencyGraphView`, `IncidentGroupsView`, `IncidentsView`, `LoginView`, `MaintenanceView`, `OidcCallbackView`, `ProbeTimelineView`, `PublicPageView`, `ServerSetupView`, `SettingsView`, `SilencesView`.
- **Points de casse identifiés (grep)** :
  - Tables larges → débordent : `TlsFleetView`, `GroupDetailView`, `AuditView`, `AdminView`, `MonitorsView`.
  - Grilles à colonnes fixes : `IncidentsView:526` (`grid-template-columns: 100px 1fr 80px 150px 80px 40px`), `EditMonitorModal`/`CreateMonitorModal`/`ScenarioBuilder` (`grid-cols-3/5`), `OnboardingWizard` (`repeat(3,1fr)`).
  - `MaintenanceView` calendrier `grid-cols-7` (= semaine, légitime, mais cellules à vérifier en largeur).
  - **Spécifique VELOURS** : gros chiffres Fraunces (hero verdict, ruban stats dashboard, grades TLS) `tabular-nums` → risque d'overflow / scale à clamp sur viewport étroit.

## Contraintes dures

- **Mobile-first** : modifier la base, ajouter `md:`/`lg:` pour le desktop ; ne jamais régresser le rendu desktop (≥1024px identique au pixel près sauf intention).
- Gates CI verts : **axe `tests/a11y.test.js`**, **anti-overlay `tests/a11yModals.test.js`**, **parité i18n** EN+FR.
- Tests **vitest dans la foulée** (Node 22 via Docker, cf. CLAUDE.md).
- Touch targets ≥ 44px en mobile (déjà acquis A11Y-5 — ne pas casser).
- `prefers-reduced-motion` respecté (règle globale style.css déjà là).
- Les **2 thèmes** restent fonctionnels à tous les breakpoints.
- Commits `fix(frontend):` ou `feat(frontend):` selon ampleur ; PATCH/MINOR par release-please.

## Fondations transverses (R-0) — FAIT (branche `feat/responsive-r0-r1`)

> **Audit corrigé en cours de route** : l'audit initial ne comptait que les utilitaires Tailwind `md:` et ratait les `@media` CSS scopés. Réalité : le code est déjà largement responsive. `MonitorsView` (cartes `md:hidden` + `table hidden md:table`) et `IncidentsView` (reflow `@media`) sont des implémentations de référence ; `.filter-bar` est globalement `flex-wrap` ; `DashboardView` est fluide (clamp + auto-fill).
- [x] Convention breakpoints + checklist documentée dans **`CLAUDE.md` § Responsive (mobile-first)** (à côté des conventions i18n/WebSocket).
- [x] **Pattern « table → cartes »** : décision = **pas de composant `ResponsiveTable`**. On codifie le duo existant de `MonitorsView` (`<div class="md:hidden">` cartes + `<table class="hidden md:table">` colonnes dégressives) comme pattern de référence — évite la churn, colle au code en place.
- [x] Pas de `useBreakpoint()` : tout se fait en CSS pur (clamp, auto-fill, `@media`, utilitaires Tailwind). Composable inutile pour l'instant.
- [x] Vérif largeurs fixes < 360px : grilles auto-fill `minmax(230px,1fr)` se replient en 1 colonne ≤320px (OK).

## Phases (1 PR par phase, ~2-4 vues chacune)

### R-1 — Vues haute fréquence (dashboard & monitoring) — FAIT (branche `feat/responsive-r0-r1`)
> Constat : ces 3 vues étaient déjà majoritairement responsive. Seuls 2 vrais points de casse subsistaient.
- [x] `DashboardView` : **vérifié, aucun changement requis** — hero `clamp(34px,5.5vw,64px)`, ruban stats `flex-wrap` (`flex:1 1 140px`), grille services `auto-fill minmax(230px,1fr)` → 1 col ≤320px. Déjà fluide.
- [x] `MonitorsView` : table → cartes déjà en place (`md:hidden` + `hidden md:table`). **Fix** : rangée d'actions du header (recherche + 4 boutons) débordait < 360px → `flex flex-wrap` + `min-w-[12rem]` sur la recherche.
- [x] `IncidentsView` : reflow `@media 640px` déjà présent. **Fix** : les incidents standalone (jusqu'à 5 boutons d'action) débordaient la piste de 44px → colonne actions passée en **ligne pleine largeur** (`grid-column: 1 / -1`, `flex-wrap`, touch 44px).
- [x] Garde-fous verts : lint OK, **273/273 vitest** (dont gate axe + anti-overlay), Node 22 Docker.

### R-2 — Tables & listes — FAIT (branche `feat/responsive-r0-r1`)
> Décision : **deux tiers** (documenté CLAUDE.md). Cartes↔tableau réservé au contenu primaire (MonitorsView, déjà fait R-1) ; pour les tables denses secondaires/admin, **scroll horizontal** (`overflow-x-auto` + `min-w`) — préserve les colonnes sans dupliquer le markup.
- [x] `AuditView` : table 4 col → `overflow-x-auto` + `min-w-[34rem]` ; panneau diff before/after `grid-cols-2` → `grid-cols-1 sm:grid-cols-2`.
- [x] `AdminView` : 2 tables (users 7 col, monitors ~6 col) → `overflow-x-auto` + `min-w-[52/48rem]`. Les grilles de cartes (teams/probe-groups) étaient déjà responsive.
- [x] `TlsFleetView` : table 6 col → `overflow-x-auto` + `min-w-[44rem]` (bordure/rounded déplacés sur le wrapper).
- [x] `GroupDetailView` : table monitors 6 col → `overflow-x-auto` + `min-w-[40rem]`.
- [x] `SilencesView` : pas de table (`.silence-row` flex déjà fluide) ; modale dates `grid-cols-2` → `grid-cols-1 sm:grid-cols-2`.
- [x] `IncidentGroupsView` : pas de table ; header `flex-wrap` + colonnes stats `grid-cols-2` → `grid-cols-1 sm:grid-cols-2`.
- [x] Garde-fous : lint OK, **273/273 vitest** (gate axe + anti-overlay), Node 22 Docker.

### R-3 — Formulaires, modales & calendrier — FAIT (branche `feat/responsive-r0-r1`)
> Constat clé : `.modal-panel` est `width:100%` (cappé par viewport − 1rem), donc **toutes les modales s'adaptent déjà** sur mobile. La plupart des grilles internes (`cols-2` paires d'inputs, `cols-3` boutons compacts, `cols-3` select+input 1/3-2/3) sont utilisables à ~328px → vérifiées, pas touchées. Seuls les vrais points serrés corrigés.
- [x] `ScenarioBuilder` : palette « Add a step » `grid-cols-5` (≈55px/cellule) → `grid-cols-3 sm:grid-cols-5`. Les `cols-3`/`cols-2` (mode+valeur, scroll x/y) vérifiés OK.
- [x] `CreateMonitorModal` / `EditMonitorModal` : vérifiés OK — `cols-3` = boutons toggle compacts (network scope), `cols-2` = paires interval/timeout/json_path utilisables ; sélecteur check-type déjà `grid-cols-4 sm:grid-cols-6`.
- [x] `OnboardingWizard` : presets `repeat(3,1fr)` → `repeat(auto-fit, minmax(90px,1fr))` (se replie sur appareils très étroits, 3 cols conservées au-delà).
- [x] `MaintenanceView` : modale dates `grid-cols-2` → `grid-cols-1 sm:grid-cols-2`. Calendrier `grid-cols-7` laissé tel quel (7 colonnes inhérentes, cellules `1fr`+`truncate` ne débordent pas ; vue liste alternative dispo).
- [x] `SettingsView` : vérifié OK — stack vertical de cartes, seule grille = codes de récupération `cols-2` (chaînes courtes, OK).
- [x] Garde-fous : lint OK, **273/273 vitest** (gate axe + anti-overlay), Node 22 Docker.

### R-4 — Vues secondaires & charts — FAIT (branche `feat/responsive-r0-r1`)
> Constat : ces vues étaient quasi toutes déjà fluides (flex + `max-w` + truncation). Seul ProbeTimelineView avait des rangées flex non-wrap qui débordaient.
- [x] `ProbeTimelineView` : header (breadcrumbs + titre + select sur une ligne) et lignes d'incidents (plusieurs dates `whitespace-nowrap`) débordaient → `flex-wrap` sur les deux.
- [x] `PublicPageView` : vérifié OK — header centré, lignes monitors en `min-w-0 flex-1` + `shrink-0` (truncation propre), form abonnement déjà `flex-wrap`.
- [x] `LoginView` / `ServerSetupView` / `OidcCallbackView` : vérifiés OK — cartes centrées `.login__container` (`width:100%; max-width:380px`), inputs/boutons pleine largeur. Couvre l'écran de 1er lancement de l'app native.
- [x] `DependencyGraphView` : vérifié OK — conteneur flex pleine hauteur ; le graphe gère son propre canvas (visualisation power-user, non optimisée pour très petits écrans, acceptable).
- [x] **ApexCharts** : vérifié OK — pas de width/height fixés (rendu à la largeur du conteneur), toolbar + legend masqués → responsive nativement. (Note hors-scope : `theme: {mode:'dark'}` hardcodé = dette thème, pas responsive.)
- [x] Garde-fous : lint OK, **273/273 vitest** (gate axe + anti-overlay), Node 22 Docker.

### R-5 — Validation — PARTIEL (PR #188 ouverte)
- [x] Gates automatisés re-run : lint OK, **273/273 vitest** (axe + anti-overlay), **build prod OK** (Node 22 Docker).
- [x] Revue responsive **statique** finale : aucun débordement horizontal résiduel (tables toutes wrappées scroll-x/cartes, `BulkActionBar` + `.filter-bar` en `flex-wrap`, aucune largeur fixe > viewport, `MonitorRow` responsive en interne).
- [ ] **Validation visuelle device — à faire côté mainteneur** (non automatisable ici, pas de browser headless) : DevTools 360/390/768/1024px × 2 thèmes ; APK debug (`mobile/build.sh apk`) sur device physique (drawer, scroll, touch) ; captures avant/après si souhaité.

> **PR #188 MERGÉE** sur main (`1b61071`, 2026-06-15) après resync (merge de main : seul conflit = CLAUDE.md, sections Responsive + Design system gardées ; .vue auto-mergés proprement). Gate complet revérifié sur l'arbre fusionné (lint strict + vitest + build). **Validation device R-5 jamais faite (impossible ici) — reste à faire côté mainteneur en post-merge.**

## Hors scope

- Refonte IA/UX des flows (le travail est responsive, pas restructuration de navigation).
- Shell `AppLayout` (déjà responsive — ne pas retoucher).
- Refonte visuelle (déjà fait par VELOURS).
- Composants mobile-natifs spécifiques Capacitor (gestes, haptique) → plan séparé si besoin.

## Suivi

| Phase | PR | Statut |
|---|---|---|
| R-0 fondations | `feat/responsive-r0-r1` | **fait** (convention CLAUDE.md, audit corrigé) |
| R-1 haute fréquence | `feat/responsive-r0-r1` | **fait** (2 fixes ; Dashboard déjà OK) |
| R-2 tables | `feat/responsive-r0-r1` | **fait** (scroll-x sur 4 tables denses + 2 grids stack) |
| R-3 formulaires | `feat/responsive-r0-r1` | **fait** (3 fixes ciblés ; modales déjà fluides) |
| R-4 secondaires + charts | `feat/responsive-r0-r1` | **fait** (ProbeTimeline flex-wrap ; reste vérifié OK) |
| R-5 validation | PR #188 | **partiel** (gates + revue statique OK ; device → mainteneur) |
