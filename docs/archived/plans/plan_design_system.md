# Plan — Consolidation design system (post-VELOURS)

> Feu vert utilisateur 2026-06-15, suite au constat d'hétérogénéité (drift des boutons, parcours détection↔alerte dispersés, lisibilité).
> Principe directeur : **VELOURS a unifié les tokens (couleurs/typo), pas la couche au-dessus** — ni les *composants* (boutons, badges), ni les *parcours* (où vivent les fonctions liées). Ce plan corrige les deux.
> Ne remplace pas `plan_responsive.md` (branche `feat/responsive-r0-r1`, R-0→R-4 faits) : chantier distinct.

## Constat (audit 2026-06-15, grep-sourcé)

### Axe A — Incohérence visuelle des composants
- **Drift des boutons** : `.btn-*` (style.css:216-291) ont une base partagée (padding `.35rem .75rem`, font `.8125rem`, weight 600) **mais aucune échelle de tailles**. Résultat : ~176 usages (`btn-primary` ×89, `btn-secondary` ×43, `btn-ghost` ×36, `btn-danger` ×8) dont une grande partie surcharge la taille en inline avec ≥ 8 combinaisons concurrentes (`text-xs`, `text-sm`, `h-8`, `h-9`, `px-3 py-1.5`, `px-3 py-1`, `text-xs px-3 h-9`…).
- **Couleurs hardcodées** : `.btn-primary`/`.btn-danger` utilisent des hex/rgba en dur (`#e3bb66`, `#f0d08c`, `rgba(220,171,74,…)`, `#fca5a5`, `rgba(248,113,113,…)`) au lieu des tokens VELOURS → ne suivent pas proprement le thème.
- **Classes concurrentes / mortes** : `.filter-btn` défini (IncidentsView ~504-521) mais **utilisé 0 fois** (la vivante est `.filter-chip`, globale) ; `.ack-btn` = énième bouton-icône maison distinct de `btn-ghost` ; 2 boutons stylés en `style=` inline (GroupsView:45, MaintenanceWindowCard:27).
- **Badges de statut dupliqués** : pas de composant partagé. `badgeClass`/`dotClass`/`statusLabel` réimplémentés localement (IncidentsView, SilencesView, MonitorRow) + maps `:class` statut inline dans ≥ 11 fichiers (GroupDetailView, PublicPageView, MaintenanceView, ProbesView, DashboardView, ProbeMap, MaintenanceWindowCard, AppLayout, CommandPalette, MonitorDetailView, MonitorsView).

### Axe B — Parcours détection↔alerte dispersés
Trois fonctions sœurs (« détecter quelque chose d'anormal »), câblées de **trois façons différentes** entre deux écrans :
| Feature | Toggle « détection » | Alerte / notification | Pont UX existant |
|---|---|---|---|
| **DNS drift** | `MonitorDnsPanel` / `MonitorConfigCards` (monitor) | condition matrice + `AlertsView` | **modale de suggestion** auto (MonitorDnsPanel:140-165 : choisir canal + « créer la règle ») |
| **Schema drift** (`json_path`) | toggle monitor (baseline) | condition `schema_drift` (`alertMatrix.js`) | **texte d'aide seul** (`AlertsView:328`, « Enable drift detection on the monitor first ») |
| **Anomalie z-score** | *aucun* (calcul serveur sur données existantes) | condition `anomaly_detection` (`alertMatrix.js:4`) | *aucun* |

- Preuve du split assumé à moitié : l'app doit afficher un avertissement de réconciliation (`monitor_detail.dns_alert_desc` : « DNS Drift is enabled but no alert rule exists… no notification will be sent ») et a construit un pansement (la modale DNS) **pour une seule des trois** features.
- La séparation **backend** mesure/notifier est légitime (standard Datadog/Grafana ; détecter sans alerter a du sens) → **on la garde**. C'est le **frontend** qui doit rendre le pont cohérent et homogène.

## Contraintes dures

- Gates CI verts : **axe `tests/a11y.test.js`**, **anti-overlay `tests/a11yModals.test.js`**, **parité i18n** EN+FR (toute nouvelle string dans `en.js` ET `fr.js`).
- Tests **vitest dans la foulée** (Node 22 via Docker).
- **Pas de régression visuelle desktop** ni de changement de comportement backend (la séparation mesure/notifier reste).
- **Zéro nouveau hex hardcodé** : tout passe par les tokens VELOURS (`--accent`, `--down`, `--up`, `--warn`, `--error`, `--text-*`).
- Aucune modale artisanale (réutiliser `BaseModal`) ; touch targets ≥ 44px mobile préservés.
- Commits `refactor(frontend):` / `feat(frontend):` / `fix(frontend):` selon la nature.

---

## Axe A — Consolidation visuelle

### A-0 — Conventions & inventaire figé — FAIT (avec A-1, PR #192)
- [x] Documenté dans `CLAUDE.md` § Design system : variantes × tailles, règle « jamais de surcharge de taille inline », `.btn-icon`, `<StatusBadge>` à venir.
- [x] Inventaire call-sites figé dans ce plan (constat grep) comme checklist du sweep A-2.

### A-1 — Échelle de tailles boutons + tokenisation — FAIT (PR #192, branche `feat/ds-a1-buttons`)
- [x] Échelle `.btn-sm` (~28px) / défaut md (~32px) / `.btn-lg` (~40px) ajoutée dans `style.css`. Additif, défaut inchangé.
- [x] `.btn-icon` (carré, ≥44px tactile mobile) ajouté.
- [x] Tokenisation : `btn-primary` accent hex/rgba → `color-mix(var(--accent))` (fidèle) ; `btn-danger` rouge générique `#f87171` → `var(--down)` (terracotta) dans les 2 thèmes → override clair redondant supprimé.
- [x] Validé Node 22 : lint, 273 vitest (gate axe), build OK. Contraste dark danger ≈6:1 (AA).
- ⚠️ **Pas de sweep des call-sites ici** (= A-2) : les boutons existants gardent leurs surcharges inline et leur rendu actuel.

### A-2 — Sweep des call-sites boutons — FAIT (PR #192, branche `feat/ds-a1-buttons`)
- [x] **86 boutons / 30 fichiers** : `text-xs`→`.btn-sm`, `text-sm`→défaut, `h-8`/`h-9`+`px-*`/`py-*` associés retirés. Transform scopé aux `class="…"` btn, diff intégralement relu. Layout/états/couleur préservés.
- [x] Validé Node 22 : lint, 273 vitest (gate axe), build OK.
- [ ] **Reporté en A-4** : les 2 boutons `style=` inline (GroupsView:45, MaintenanceWindowCard:27) — relèvent du nettoyage, regroupés avec ack-btn/.filter-btn.
- ⚠️ Pas de validation **visuelle** par vue (pas de browser headless dispo) — à faire côté mainteneur ; tailles légèrement ajustées vs surcharges inline d'origine.

### A-3 — Composant `<StatusBadge>` — FAIT (PR #192, branche `feat/ds-a1-buttons`)
- [x] `components/shared/StatusBadge.vue` créé (`:status` + `:dot` → badge-* + libellé i18n + dot tokenisé). Test `tests/statusBadge.test.js`.
- [x] **Famille globale `.badge-*` tokenisée** (badge-up/down/timeout/unknown étaient hors-token emerald/red/amber → color-mix sur --up/--down/--warn/--text-3) ; overrides clairs redondants supprimés.
- [x] **Bug i18n corrigé** : libellés statut monitor codés en anglais en dur (useMonitorDisplay + MonitorRow) → clés `status.*` (ajout `status.timeout`/`status.error` en+fr).
- [x] `useMonitorDisplay` allégé + dot tokenisé ; MonitorsView (×2) → `<StatusBadge>`.
- [x] **Suivi A-3 soldé** (PR #196) : `GroupDetailView` → `<StatusBadge>` (était la seule vraie pastille restante ; affichait le statut brut minuscule → corrigé i18n). PublicPageView/CommandPalette/MonitorDetailView = points colorés (pas des pastilles) ; RecentChecksTable/SummaryCard = pas de pastille → laissés tels quels (hors scope StatusBadge).
- ⚠️ `IncidentsView`/`SilencesView` `badgeClass` = statut **incident/silence** (autre concept), hors scope StatusBadge. `MonitorRow.vue` = **code mort** non importé → suppression en A-4.

### A-4 — Nettoyage classes mortes/concurrentes — FAIT (PR #192, branche `feat/ds-a1-buttons`)
- [x] `.filter-btn` (morte) supprimée dans IncidentsView (vivante = `.filter-chip`).
- [x] `.ack-btn` (7 usages + CSS scopé) → `.btn-icon` global + `.btn-icon--active`.
- [x] 2 boutons `style=` inline → `.btn-icon` (GroupsView, MaintenanceWindowCard).
- [x] **`MonitorRow.vue` supprimé** (code mort, non importé).
- [x] Grep final : plus aucun `<button style=…>` ni `ack-btn`/`filter-btn`.
- [x] Validé Node 22 : lint, vitest (gate axe), build OK.

---

## Axe B — Cohérence des parcours détection↔alerte

### B-0 — Modèle cible — FAIT (PR #194)
- [x] Modèle figé : **pont forward sur toggle de détection** (DNS, schema) ; l'anomalie n'a pas de toggle (alert-only par nature → pas de pont forward, c'est légitime) ; CTA inverse depuis la condition d'alerte = reste à faire. Backend inchangé.

### B-1 — Composant de pont unique — FAIT (PR #194, branche `feat/ds-axis-b`)
- [x] `composables/useDetectionAlertBridge.js` : flux générique offrir→créer paramétré par `condition`. Test `tests/detectionAlertBridge.test.js`.
- [x] `components/shared/DetectionAlertBridge.vue` : modale générique + i18n `detection_alert.*` (EN+FR).

### B-2 — Application homogène — PARTIEL (PR #194)
- [x] **DNS drift** : MonitorDnsPanel + useMonitorDns refactorés sur le pont (comportement préservé, règle `any_down`).
- [x] **Schema drift** : carte schema propose le même pont (condition `schema_drift`) — parité avec DNS.
- [x] **Anomalie** : pas de toggle monitor (alert-only) → pas de pont forward (légitime). DNS drift : pas de condition séparée (remonte en `any_down`).
- [x] **Lien inverse** dans `AlertsView` (PR #195) : condition `schema_drift` + moniteur sans `schema_drift_enabled` → **CTA actionnable** qui active la détection en place (au lieu du texte mort `schema_drift_help`).

### B-3 — Indicateur d'état unifié — FAIT (PR #195, branche `feat/ds-axis-b2-b3`)
- [x] Cartes DNS drift + schema drift : « ✓ Notification câblée » / « ⚠ Aucune notification — détection seule » via `useDetectionAlertBridge.refreshWired`. CTA masqué une fois la règle créée.
- [x] Composable : + `wired` + `refreshWired(condition)` ; `createAlertRule` → `wired=true`. Tests étendus. i18n en+fr.
- [x] Validé Node 22 : `eslint --max-warnings 0`, 286 vitest (gate axe), build OK.

---

## Hors scope
- Refonte du moteur d'alerte backend / de la séparation mesure-notifier (légitime, conservée).
- Refonte visuelle des tokens VELOURS (déjà fait).
- Responsive (chantier `plan_responsive.md`).
- Refonte IA globale de la navigation (on corrige les parcours détection↔alerte, pas l'arborescence entière).

## Découpage PR proposé
1. **Axe A d'abord** (gain visuel immédiat, faible risque) : A-1+A-4 (système), puis A-2 (sweep par lots de vues), puis A-3 (StatusBadge).
2. **Axe B ensuite** (touche au comportement, plus sensible) : B-1, puis B-2/B-3.
Axe A et Axe B sont indépendants — peuvent partir sur deux branches.

## Suivi
| Phase | PR/branche | Statut |
|---|---|---|
| A-0 conventions | PR #192 | **fait** (doc CLAUDE.md) |
| A-1 échelle boutons + tokens | PR #192 | **fait** (additif + tokenisation fidèle) |
| A-2 sweep call-sites | PR #192 | **fait** (86 boutons / 30 fichiers) |
| A-3 StatusBadge | PR #192 | **fait** (+ badges tokenisés + fix i18n) |
| A-4 nettoyage classes | PR #192 | **fait** (ack-btn→btn-icon, .filter-btn morte, MonitorRow supprimé) |
| B-0 modèle cible | PR #194 | **fait** |
| B-1 composant pont | PR #194 | **fait** (composable + composant + test) |
| B-2 application | PR #194 + #195 | **fait** (DNS+schema forward ; CTA inverse #195) |
| B-3 indicateur d'état | PR #195 | **fait** (cartes DNS+schema : câblé / aucune notif) |
