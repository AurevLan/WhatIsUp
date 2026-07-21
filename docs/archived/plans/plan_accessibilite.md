# Plan d'action — Accessibilité frontend (A11Y)

> Créé le 2026-06-12 (post-v1.12.0). Reliquat d'audit PR #171 (« ARIA/focus-trap frontend »).
> S'inscrit dans la phase **stabilisation** : consolidation de l'existant, pas de feature.
> Tenir ce fichier à jour à chaque phase livrée (ligne barrée + SHA commit).

## État des lieux (mesuré 2026-06-12)

**Acquis — baseline `b421f1d` (v1.11)** :
- `BaseModal.vue` : focus trap complet (focus initial, cycle Tab/Shift+Tab, restitution au déclencheur) + `aria-labelledby` — couvert par 14 tests
- 14 modales/vues passent par `BaseModal` (wizard, create/edit monitor, probes, maintenance, silences, alert-matrix…)
- `aria-label` posés sur MonitorsView (14), AlertsView (5), pagination, FAB
- `DependencyGraph` navigable clavier (`role=button`, Enter/Space) ; `ToastContainer` `role=status`
- Skeletons : ARIA + `prefers-reduced-motion` (déjà fait)

**Manques mesurés** :
| Gap | Mesure |
|---|---|
| Overlays `fixed inset-0` hors BaseModal | 7 modales `admin/*` + overlays inline dans 8 vues (dont SettingsView : modales 2FA/recovery codes/sessions de v1.12) |
| Boutons sans `aria-label` | ~10 vues à 0 aria-label (AdminView 12 btns, SettingsView 18, IncidentsView 13, MaintenanceView 10, TemplatesView 11…) — cible réelle = icon-only uniquement |
| `aria-live` / `role="alert"` | 2 fichiers seulement — erreurs formulaires et updates temps réel non annoncés |
| `document.title` + focus par route | absents (`router/index.js` : aucun `afterEach`) |
| Garde-fou CI | aucun (pas d'axe-core dans package.json) |

**Corrections post-inventaire (2026-06-12)** : le skip-link, le `<main id="main-content">`, l'`aria-label` nav et un **toggle thème clair/sombre** (`data-theme` CSS vars, pas Tailwind `dark:`) existaient déjà dans `views/layouts/AppLayout.vue` (pas App.vue). Le chantier « thème » du plan ergonomie est donc déjà livré ; A11Y-3 se réduit à : i18n du skip-link, `tabindex="-1"` sur main, `document.title` + focus par route.

---

## A11Y-0 — Outillage & garde-fou CI — ~~FAIT~~ (PR #179, `b238652`)

- [x] `axe-core` en devDependency (pas `vitest-axe` : 2023, incompatible vitest 4 — helper maison dans le test)
- [x] `tests/a11y.test.js` : 6 vues principales montées (mock api/client, Pinia, memory router, stubs charts/maps), échec sur toute violation critical/serious ; règles page-level + color-contrast désactivées (fragments jsdom)
- [x] Gate CI : automatique (tests/** déjà exécutés par le job Frontend tests)
- [x] Bonus : 6 violations réelles trouvées et corrigées (0 baseline restante) — selects sans nom (filtre type, statut update ×2, parent monitor), input import caché, dates SLA sans `for`/`id`
- [ ] Optionnel (reporté) : `eslint-plugin-vuejs-accessibility` en warning
- **Critère atteint** : la CI échoue sur toute nouvelle violation critical/serious ; baseline vide

## A11Y-1 — Overlays restants → BaseModal — ~~FAIT~~ (PR #180)

- [x] 7 modales `components/admin/*` migrées (9 coquilles)
- [x] Overlays inline des vues : Settings (3 : TOTP setup / recovery codes / disable — la révocation sessions passait déjà par `useConfirm`), ApiKeys (2), GroupDetail (1), Probes (1), Templates (2), Alerts (2)
- [x] `components/monitors/detail/*` : 5 vraies modales migrées (alert auto-setup, push URL, DNS drift, postmortem, éditeur SLO) — les autres `fixed inset-0` étaient bien des backdrops non-dialogue
- [x] Lightbox screenshot (MonitorDetailView) : nouvelle taille `xl` (64rem) ajoutée à BaseModal
- [x] Garde-fou `tests/a11yModals.test.js` : nouvel overlay `fixed inset-0` hors allowlist (drawer mobile, backdrop dropdown MaintenanceView) = suite rouge
- **Critère atteint** : 25 dialogues via BaseModal, 0 modale artisanale restante
- Convention retenue : submit dans le `<form>` (Enter-to-submit), actions hors-form dans `#footer`

## A11Y-2 — Boutons icône & formulaires — ~~FAIT~~ (PR #181)

- [x] 58 boutons icône labelisés dans 24 vues/composants (réutilisation des clés existantes ; +3 clés `a11y.*` EN+FR)
- [x] `aria-invalid` + `aria-describedby` sur les 4 formulaires à erreur inline (Settings timezone, Templates config, ServerSetup URL, Login MFA)
- **Critère atteint** : gate axe vert, plus de `button-name`/`select-name`/`label` sur les vues principales

## A11Y-3 — Navigation & structure — ~~FAIT~~ (PR #179, `b238652`) sauf h1/h2

- [x] Skip-link : déjà présent (AppLayout) → traduit via `a11y.skip_to_content` EN+FR
- [x] `tabindex="-1"` sur `<main id="main-content">` (cible du skip-link ET du focus reset)
- [x] `document.title` par route : `meta.titleKey` i18n + `router.afterEach`
- [x] Focus reset au changement de route (skippé au chargement initial)
- [x] `<html lang>` synchronisé dès le premier paint (i18n/index.js)
- [ ] Hiérarchie de titres : un `h1` par vue, `h2` pour les sections → reporté en PR 3 (sweep par vue)
- **Critère** : navigation entre vues annoncée au lecteur d'écran, title onglet à jour

## A11Y-4 — Live regions temps réel — ~~FAIT~~ (PR #181)

- [x] Toasts d'erreur `role=alert`, succès/info `role=status` (rôle par toast, plus de double annonce)
- [x] Badge reconnexion WS + indicateur global up/down + compteur bulk en wrappers `aria-live="polite"` stables
- **Critère atteint** : changements d'état annoncés sans spam (rien en assertive sauf erreurs)

## A11Y-5 — Contrastes & finitions — ~~FAIT~~ (PR #181)

- [x] `--text-3` AA sur les 2 thèmes (dark 2.45→4.56:1, light 2.77→4.57:1, ratios documentés dans style.css)
- [x] `prefers-reduced-motion` : règle globale déjà présente (vérifiée) + gardes skeleton conservées
- [x] Touch targets : déjà ≥ 24 px partout (WCAG 2.5.8 AA) ; minima 40-44 px mobile déjà dans AppLayout — aucun changement
- Caveat noté : text-3 dark = 4.05:1 sur `--bg-surface-3` (fond hover transitoire uniquement)

---

## Découpage PR proposé (3 PRs, ~15-18 h total)

1. **PR 1** : A11Y-0 + A11Y-3 → **PR #179 mergée** (21a63da)
2. **PR 2** : A11Y-1 → **PR #180 mergée** (b963f74)
3. **PR 3** : A11Y-2 + A11Y-4 + A11Y-5 + h1/h2 → **PR #181 mergée** (0d78e7d, après rebase)

> **CHANTIER TERMINÉ ET MERGÉ** (2026-06-13) — A11Y-0→5 sur main (21a63da, b963f74, 0d78e7d). Reste optionnel : eslint-plugin-vuejs-accessibility.

Chaque PR : tests vitest dans la foulée (Node 22 via Docker), parité i18n vérifiée, conventional commit `fix(a11y):` (PATCH — c'est de la consolidation).

## Hors scope (chantiers séparés)

- Responsive mobile des 14 vues sans breakpoints → plan dédié si feu vert
- Toggle thème clair/sombre → feature, attend la sortie de phase stabilisation
- Alternative textuelle aux charts ApexCharts (table de données) → à évaluer en A11Y-5, probablement follow-up
