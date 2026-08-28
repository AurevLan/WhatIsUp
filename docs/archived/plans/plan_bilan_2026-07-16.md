# Bilan optimisation — 2026-07-16

> Audit 4 axes (backend / frontend / probe+tests+CI / hygiène repo) par agents parallèles.
> Complète `plan_bilan_2026-07.md` (vagues 1-3a mergées ; 3b-3d backlog). Les items déjà listés en 3d y restent — repris ici avec le nouveau contexte.
> État de départ : main propre, v1.15.2, CI verte, 3 PRs ouvertes (release-please #263 + dependabot #264/#265).

## P0 — Sécurité / correctness (à traiter en priorité)

| # | Item | Où | Détail |
|---|---|---|---|
| S1 | **SSRF checker `ping`** | `probe/whatisup_probe/checkers/ping.py:14,28` | Seul checker sans `validate_host_ssrf` (regex anti-injection seule) → peut cibler 127.0.0.1 / 169.254.169.254 / 10.x. Aligner sur tcp/udp/smtp/dns/http. |
| S2 | **Rate-limit manquant sur mutations** | `api/v1/teams.py` (9 endpoints, 0 limiter, import absent) ; `alerts.py:95,235,295,380,446,767` (7 mutations) ; `onboarding.py` (POST) ; `audit.py` | Ajouter `@limiter.limit` + `request: Request`. Resync table SECURITY.md §12 ensuite. |
| S3 | **Pin redis contradictoire** | `server/pyproject.toml:28-30` | Commentaire : « <8 : redis-py 8.0.0 force socket_timeout=5s sur pubsub → subscriber WS crashe » mais le pin réel est `<9` (autorise 8.x). Trancher : vérifier si le bug 8.x existe encore → soit cap `<8`, soit corriger le commentaire. |
| S4 | **Reliquat SA6** (déjà connu) | `deps.py` `_auth_via_user_api_key` | Pas d'éviction cache à la révocation d'une clé user (valide ≤60 s) + empreinte non appliquée au motif user. Même durcissement que SA6 probe. |

## P1 — Quick wins (faible effort, gains nets)

### Code mort à supprimer
- **`PublicPage`** complet : modèle `models/monitor.py:421` + relationship `:190`, schémas `schemas/monitor.py:455,462`, exports `models/__init__.py:27,54`. Aucun endpoint ne l'utilise (piège documenté CLAUDE.md — le solder).
- **Shim probe `checker.py`** (4 lignes, aucun importeur interne).
- **Frontend** : `SummaryCard.vue`, `UptimeHistoryBars.vue`, `SkeletonText.vue` (jamais importés) + classes CSS orphelines `style.css` : `.ack-btn`, `.btn-lg`, `.card-interactive`, `.input-error/success`, `.ws-flash*`, `.pulse-down/warn`, `.list-enter/leave/move-*` (garder `.page-*`, utilisées).

### Robustesse / CI
- 2 `except: pass` silencieux à logger : `services/fcm.py:179`, `api/v1/ws.py:372`.
- CI : **mypy strict configuré mais jamais lancé** (`ci.yml` job lint = ruff seul) — soit le câbler, soit retirer la config morte ; **pas de `vite build` sur PR** (build web cassable indétecté) ; **aucun `timeout-minutes`** sur les jobs ; gate coverage probe à 40 % (faible).
- `httpx` dupliqué dep+dev-dep (`server/pyproject.toml:54,71`).
- Commentaire cap `fastapi<0.140` périmé (bug résolu en 0.139) — rouvrir le cap ou réécrire la justification.

### Docs / repo
- **FEATURES.md** : en-tête bloqué à v1.15.0 — amender v1.15.1 (self-host fonts) + v1.15.2 (LATERAL `fetch_latest_results`).
- **README** : section « What's new » s'arrête à 1.14 — ajouter 1.15.
- **Codemap périmé** : `MonitorRow.vue` fantôme (2×), `deps.py` mal localisé (est en `api/deps.py`), manquent côté server `incident_{alerts,correlation,decider,slo}.py`, `lockout.py`, `core/percentile.py`, `channels/fcm.py` ; côté frontend `DependencyGraphView`, `lib/{biometricAuth,nativeApp,runbookMarkdown,themeColors}.js`, `composables/{useDateFormat,useDetectionAlertBridge}.js`, `AlertMatrix.vue` + sous-dossier `alert-matrix/`, `MetricsDashboard`, `ScheduleEditor`, `TagChips`, `DependencyGraph`, `shared/{DetectionAlertBridge,ErrorBoundary,StatusBadge}.vue`, `alerts/AlertTemplatesSection.vue`.
- **Plans racine** : archiver dans `docs/archived/plans/` → `plan_stabilisation_audit`, `plan_accessibilite`, `plan_redesign_velours`, `plan_responsive`, `plan_design_system`, `plan_v2_global_health` (header trompeur « en cours » alors qu'en prod). NB : `plan_*.md` est gitignored partout — si on veut les préserver dans git, ajouter `!docs/archived/` au `.gitignore`.
- **Branches mortes** : 21 locales `worktree-agent-*` (toutes mergées) + `proto/dashboard-redesign` + `sec/*`/`fix/*` squash-mergées ; côté remote `git remote prune origin` + élaguer `docs/*`, `perf/*`, `sec/*` mergées.
- `docs/LAUNCH_POSTS.md` (2026-04-07, pré-VELOURS) — rafraîchir ou archiver.
- **nginx désaligné** : `frontend/Dockerfile` = 1.31-alpine vs `docker-compose.yml` = 1.29-alpine.
- Orphelins disque : `build-output/apk/app-debug.apk`, `.ruff_cache/` racine (owned root).
- Bugs de langue en dur : `EditMonitorModal.vue:181,286` (français dans un composant anglais), `SettingsView.vue:282` (anglais en dur).

## P2 — Factorisation (effort moyen, dette réelle)

### Backend
- **Helper générique `get_owned_or_404(Model, id, user, db)`** : 5 implémentations dupliquées (`monitors.py:61`, `admin.py:239`, `api_keys.py:24`, `groups.py:32`, `incident_updates.py:30`) + fetch inline recopié dans `alerts.py`/`metrics.py`/`status.py` (8× "Monitor not found").
- **Pagination** absente : `teams.py:84`, `audit.py:18`, `alerts.py:472` (/events), `groups.py:47`.
- 52 endpoints renvoient `-> dict` en contournant les schemas `*Out` (risque champ manquant silencieux — piège déjà documenté). Harmonisation progressive.
- N+1 job de fond : `services/reports.py:132-146` (boucle `generate_group_report`).
- Index redondant cosmétique : `ix_monitors_enabled_owner` vs index simple `owner_id`.

### Frontend
- **`useAsyncResource(fetcher)`** → `{data, loading, error, reload}` : le triptyque loading/try/catch/finally est réimplémenté dans les 22 vues (ex. `SilencesView.vue:176-187`, AdminView 17 bascules).
- **`formatDuration` ×4 formats divergents** (`ProbeTimelineView:102` "1.5h", `IncidentsView:382` "5h 3m", `PublicPageView:378` "5h3min", `IncidentPlaybackMap:96`) + `formatUptime` (`toFixed(2)+'%'` ×6) → centraliser dans `useDateFormat`, unités i18n.
- ~15 `toLocaleString` inline contournant `FormattedDate`/`useTimezone` (`AuditView:113`, `IncidentGroupsView:125`, `ProbesView:424`, `DashboardView:228`…).
- **~90 strings UI en dur** hors i18n — prioriser `ScenarioBuilder` (19), `Edit/CreateMonitorModal` (21), `MonitorConfigCards` (11), `AddChannelModal` (8), `TeamDetailModal` (8).
- **`useMonitorForm`** : `buildPayload`/normalisation URL quasi identiques entre `CreateMonitorModal.vue:719-786` et `EditMonitorModal.vue:663-729` (847+789 lignes).

### Probe
- **Factory `CheckResult`** (`.error(exc)`, `.ssrf_blocked()`, timeout) : bloc erreur identique dupliqué dans 7 checkers (`ping:90`, `udp:85`, `domain_expiry:105`, `tcp:72`, `dns:127`, `http:400`, `smtp:117`) + bloc SSRF ×5 + parsing host/port ×3 → helper `resolve_host_port()`.

## P3 — Structurant (effort élevé, à planifier en vagues)

- **Découpage `api/v1/monitors.py` (1927 l., 39 endpoints)** par sous-ressource : slo-rules, composite, dependencies, baselines DNS/schema, annotations, import/export, postmortem. (Déjà en 3d.)
- **Sortir la logique métier des handlers** : `get_postmortem` (`monitors.py:1018-1157`, ~140 l.) et `get_dependency_graph` (`:625-715`, ~90 l.) → services.
- **Désenchevêtrer le cluster incident** : `heartbeat.py:13` et `renotify.py:22` importent `_fire_alerts` privé ; `composite.py:100` import runtime anti-cycle ; 115 imports différés en corps de fonction au total (symptôme de cycles). Définir une interface publique `incident_alerts`.
- **Tests manquants sur services critiques** : `incident_alerts.py` (10 Ko, dispatch — le plus urgent), `incident_slo.py`, `composite.py`, `anomaly.py`, `threshold_advisor.py` ; endpoint `api_keys.py` sans test fonctionnel dédié (surface sécurité). (Recoupe 3d.)
- **Bundle graphiques** : ApexCharts ≈1,1 Mo (chunks lazy, hors chemin critique) — import ciblé ou uPlot pour sparklines. Rebuild pour chiffres frais.
- Virtualisation listes (AuditView/AdminView) — seulement si volumétrie.
- Autres fichiers >600 l. backend : `alerts.py` 867, `services/alert.py` 788, `incident.py` 741, `probes.py` 668.

## Nouvelles fonctionnalités possibles

**Backlog déjà acté** (plan_bilan_2026-07, vagues 3b-3c) :
- 3b : flux RSS/Atom status page · export SLA PDF (réutiliser `reports.py`) · canal SMS/voix Twilio.
- 3c : API tokens à scopes (`scopes` JSONB sur UserApiKey) · incident manuel sur status page · checks SQL/gRPC/Docker.
- Reportés sessions dédiées : WebAuthn/passkeys, SBOM + Cosign, mobile (Play Store AAB, iOS, widget, App Links).

**Nouvelles pistes (issues du bilan)** :
1. **On-call & escalade** : planning d'astreinte simple (rotation + fenêtre horaire) branché sur `renotify.py` — grosse valeur différenciante vs Uptime Kuma.
2. **Export Prometheus/OpenMetrics par monitor** (`/metrics` scrapeable avec labels monitor/probe) — intégration Grafana quasi gratuite, `core/metrics.py` existe déjà.
3. **Pont anomaly → alerte** : `anomaly.py` détecte mais n'a ni pont UI ni notification (acté « alert-only » au DS, mais un canal digest « anomalies de la semaine » serait cohérent avec le digest Redis existant).
4. **Abonnements status page** (email sur incident public) : `StatusSubscription` model existe déjà — vérifier ce qui manque pour le bout-en-bout (confirmation double opt-in, unsubscribe).
5. **Rapports SLA planifiés par email** (extension naturelle de `reports.py` + export PDF 3b).
6. **Config-as-code** : export/import YAML de la config complète (monitors + alertes + maintenance) versionnable — l'import/export JSON monitors existe, généraliser.
7. **Terraform provider / API publique documentée** (dépend de 3c tokens à scopes).

## Ordre de bataille proposé

1. **Vague sécurité éclair** (S1-S4 + rate-limits) — ½ journée, mergeable item par item.
2. **Vague hygiène** (code mort, docs, codemap, branches, CI mypy/vite build/timeouts) — mécanique, faible risque.
3. **Vague factorisation** (P2 : helpers backend, composables frontend, factory probe, i18n sweep) — par PR thématique avec tests.
4. **Vagues 3b/3c features** (backlog produit) puis **P3 structurant** (découpage monitors.py, cluster incident, tests services).

## Suivi

- [ ] P0 S1-S4 — **4/4 revus mergeable 2026-07-16** : S3 mergé sur main (`ae0659f`) ; S1/S2/S4 pushés + **PRs ouvertes #266 (S1) / #267 (S2, avec correctif docs 19≠18 `101791e`) / #268 (S4)** — reste : CI verte puis merge. NB S1 : 38 échecs suite probe en sandbox = pré-existants (identiques sur main), à confirmer en CI
  - S2 `b0a27b7` ✅ **revu : mergeable tel quel** (2ᵉ revue, 2026-07-16 — la 1ʳᵉ avait été interrompue mi-sabotage, worktree nettoyé) — implémenteur : endpoints décorés teams ×9, alerts POST /rules (seul vrai trou — l'audit surestimait, 6/7 déjà limitées), onboarding ×2, audit ×1, + sweep : groups POST, api_keys DELETE, auth/logout, monitors deps/composite DELETE ×2, public unsubscribe 10/min ; 2 exemptions assumées (register 403, probes/register superadmin) ; SECURITY.md §12 + FEATURES.md §11 miroir ; garde-fou CI global anti-régression (`test_rate_limit_coverage.py`) ; 831 pytest verts. Revue : introspection indépendante 184 routes / 105 mutantes → 0 trou hors 2 exemptions (vérifiées justifiées et minimales, backstop 200/min global) ; sabotage rejoué ×2 (tags, teams) → rouge les 2 fois avec message précis ; 149 endpoints limités tous porteurs de `request` ; 19 valeurs runtime = SECURITY.md §12 = FEATURES.md §11 ; 831 pytest verts + ruff check/format OK rejoués ; garde-fou fail-safe (wrapper sans functools.wraps → rouge). **Écart doc non bloquant : le vrai compte est 19 décorateurs, pas 18** (titre commit + note sweep SECURITY.md ; « 137 déjà décorés » ≈ 130 réels). Findings backlog : corriger le « 18 »→19 docs ; contradiction pré-existante SECURITY.md « pas de défaut implicite » vs `default_limits=["200/minute"]` (`core/limiter.py:18`) ; garde-fou dépendant des attrs privés slowapi `_route_limits` (fail-safe mais cassable par bump) ; GET coûteux hors périmètre du garde-fou
  - S1 `a7bc0e0` ✅ **revu : mergeable tel quel** — parité exacte tcp/udp, bypasses testés (décimal/hex/octal/127.1), preuve pré-fix rejouée (11 errors sur parent), ruff vert. Findings backlog : TOCTOU rebinding partagé par tous les checkers (`_shared.py:80`), NIT message IPv6, domain_expiry sans `_SAFE_HOST_RE` (sujet injection, séparé)
  - Note S1 : 38 échecs pré-existants suite probe complète en sandbox (réseau/pydantic) — identiques sur main, hors scope, à vérifier en CI
  - S4 `9540b2e` ✅ **revu : mergeable tel quel** — trou fermé (révocation immédiate + re-cache résiduelle neutralisée par le filtre `is_revoked` du fast path) ; question perf tranchée : le cache économise bcrypt (~100 ms), pas la DB — motif identique à SA6 probe. Preuves rejouées (6/6 rouges pré-fix, 23 verts, ruff OK). Réserves backlog : JOIN UserApiKey+User combinable (2 SELECT → 1), `expires_at` naïf non testé (latent hérité, sûr en prod PG), test race in-flight en session unique
  - S3 `ae0659f` ✅ **revu : mergeable tel quel** — crash 8.0.0 re-reproduit indépendamment (5,004 s, 2 runs), 8.0.1 saine 12 s idle, arbitrage `!=8.0.0,<9` validé (cohérent Dependabot #187, `<8` recréerait la contradiction), résolution pip 8.0.1 sans conflit, 828 pytest verts re-exécutés. Findings info backlog : mention « pool 100 » perdue du commentaire, CI en fakeredis ne détecterait pas une future régression pubsub réseau (piste : test d'intégration vrai redis)
- [ ] P1 code mort / CI / docs / branches
- [ ] P2 backend / frontend / probe
- [ ] P3 (recoupe 3d)
- [ ] Features 3b/3c + nouvelles pistes (à arbitrer)
