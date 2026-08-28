# État des lieux — 2026-07-21

> Audit 4 axes (refactorisation / sécurité / nettoyage / documentation) par agents parallèles, contre-vérifié.
> État de départ : main propre à `020f959`, **v1.16.0 publiée** (2026-07-20), CI verte, **0 PR ouverte, 0 stash**.
> Complète `plan_bilan_2026-07-16.md` (P0 S1/S2/S4 soldés depuis ; ce document corrige 2 erreurs du bilan précédent, voir ⚠️).

## ⚠️ Corrections factuelles vs bilan du 16/07

1. **S3 (pin redis) N'EST PAS mergé.** Le commit revu `ae0659f` (`fix(deps): exclude broken 8.0.0`) n'existe que sur la branche locale `fix/redis-pin` — jamais poussé/mergé. Main a toujours `redis>=5.2.0,<9` avec le commentaire contradictoire (`pyproject.toml:28-30`) : le bug pubsub 8.0.0 documenté est **autorisé par le pin**. → **P0 : cherry-pick/PR de `ae0659f`** (contient aussi la dédup httpx dep/dev-dep).
2. **`PublicPage` est bien du code mort** (vérifié : zéro usage hors définition/exports ; la mention dans `ws.py:27` est une docstring sur la *vue frontend* `PublicPageView`). La note CLAUDE.md reste valide ; à supprimer (P1).

---

## 1. Sécurité — conformité ÉLEVÉE ✅

Les 5 règles absolues du projet sont **respectées et testées en CI** :
- **Rate limiting** : 100 % des endpoints mutants décorés (2 exemptions justifiées : `/auth/register` 403 invite-only, `/probes/register` superadmin) + garde-fou CI `test_rate_limit_coverage.py`.
- **SSRF serveur** : `validate_webhook_url` + `_PinnedHostTransport` (IP pinning, re-validation par hop de redirect) sur tous les canaux à URL utilisateur. Canaux à hôte vendeur fixe (Telegram/PagerDuty/Opsgenie/FCM) légitimement hors guard.
- **Fernet** : tous les champs sensibles chiffrés ; le `secret` HMAC webhook l'est aussi (mieux que documenté dans CLAUDE.md). `AlertChannelOut` n'expose jamais `config`.
- **Multi-tenant** : `build_access_filter` (`api/deps.py:561`) systématique, 404 sur cross-tenant, bypass superadmin. Aucun `select` non filtré détecté.
- **Auth** : WS auth par frame (timeout 5 s, close 4001), lockout Redis fail-open, rotation `FERNET_KEY_PREVIOUS`/MultiFernet, refus démarrage prod sur config faible. Aucun secret en dur.

**Risques résiduels (par priorité)** :
| # | Risque | Sévérité | Détail |
|---|---|---|---|
| SEC-1 | **Pin redis contradictoire sur main** (S3 perdu) | Moyenne | Cherry-pick `ae0659f` depuis `fix/redis-pin` |
| SEC-2 | **SSRF probe** `checkers/http.py` | Moyenne/Faible | Pas d'IP pinning (fenêtre DNS-rebinding validation→connexion) + hops de redirect intermédiaires non re-validés (`:98`, `:177`). Porter `_PinnedHostTransport` côté probe ou `follow_redirects=False` + re-validation par hop. Impact borné (URLs configurées par users authentifiés). |
| SEC-3 | Rate-limit GET incohérent | Faible | GET lourds/sensibles sans limiter : `GET /config` (export), `GET /alerts/events`, listes monitors. Harmoniser ou documenter l'exemption GET dans SECURITY.md §12. |
| SEC-4 | npm audit non vérifiable localement | Info | Couvert par le workflow CI hebdo ; lockfile versionné. |

## 2. Refactorisation / dette

**Haute priorité** :
| # | Item | Où | Effort |
|---|---|---|---|
| R-1 | **Divergence `simulate_rule` vs `fire_alerts`** — le preview UI ne gère que 4 conditions, le dispatch réel 7 (`response_time_above_baseline`, `anomaly_detection`, `schema_drift` absents du preview). Toute nouvelle condition diverge silencieusement. | `services/alert.py:54` vs `services/incident_alerts.py:32,171-233` | M — factoriser le matching condition→bool en fonction pure partagée |
| R-2 | **Pas de fail-open Redis sur le chemin d'auth** — `api/deps.py` appelle `redis.get/setex` sans try/except (l.77, 195-196) : Redis down ⇒ 500 sur toute auth par API key (contraste : `core/leader.py` et lockout sont fail-open). | `api/deps.py`, `core/redis.py` | M — wrapper résilient avec fallback bcrypt |
| R-3 | **`api/v1/monitors.py` : 1931 lignes, 39 endpoints** | découpage en sous-routers (SLO / Health / composite / baselines / import-export / postmortem) | L |

**Moyenne priorité** :
- R-4 `renotify.py:72-82` : rollback sur la session partagée + commit unique final → perte d'atomicité par incident. Fix S : commit par incident ou `begin_nested`.
- R-5 `StatusBadge` sous-utilisé : logique statut/couleur réinventée dans ~7 fichiers (IncidentsView, ProbesView, SilencesView, MaintenanceWindowCard, DependencyGraph, ProbeMap, useMonitorMap). Étendre `useMonitorDisplay` + StatusBadge.
- R-6 `CreateMonitorModal` (847 l.) / `EditMonitorModal` (789 l.) : formulaire dupliqué → extraire `MonitorFormFields.vue` (recoupe P2 `useMonitorForm` du bilan 16/07).
- R-7 Gros fichiers restants : `alerts.py` 869, `services/alert.py` 788, `incident.py` 741, `AlertsView.vue` 864, `MonitorDetailView.vue` 794, `IncidentsView.vue` 781.

**Basse** : `diagnostics.py` enqueue best-effort sans retry (assumé, commentaire l.12) ; 1 seul TODO dans tout le backend (`incident_alerts.py:203`, baseline non pondérée heure-de-semaine) ; les P2 frontend du bilan 16/07 restent valides (useAsyncResource, formatDuration ×4, ~90 strings hors i18n, factory CheckResult probe ×7).

## 3. Nettoyage — inventaire actionnable

**Branches locales** (tout mergé sauf mention) :
```bash
# 1. Purger les worktrees d'agents (14 sous .claude/worktrees/ + 2 prunables)
git worktree prune
git worktree list | grep '.claude/worktrees/agent-' | awk '{print $1}' | xargs -r -n1 git worktree remove --force
# 2. Branches mergées
git branch -D fix/monitors-list-latest-status-perf fix/test-fcm-flaky-sentinel \
  sec/account-lockout sec/common-cause-tenant-filter sec/docs-oidc-resync sec/fernet-rotation \
  sec/incident-groups-tenant-filter sec/probe-cache-fingerprint sec/probe-ping-ssrf \
  sec/rate-limit-coverage sec/user-api-key-cache
git branch --list 'worktree-agent-*' | xargs -r git branch -D
# 3. Remote
git remote prune origin   # puis delete ciblés des docs/* perf/* sec/* mergées
```
- **NE PAS supprimer** : `fix/redis-pin` (porte le S3 non mergé → SEC-1 d'abord), `proto/dashboard-redesign` (référence design).

**Code mort à supprimer** (P1, une PR "chore") :
- Backend : modèle `PublicPage` complet (`models/monitor.py:421` + relationship `:190` + schémas `monitor.py:455,462` + exports `__init__.py:27,54`) ; `UserTagPermission` (model + schémas `tag.py:33,39`, jamais branché) ; shim `probe/whatisup_probe/checker.py`.
- Frontend : `SummaryCard.vue`, `UptimeHistoryBars.vue`, `SkeletonText.vue` (0 import) ; **feature Incident Groups débranchée** (route redirigée vers /incidents, `router/index.js:102-103`) → `IncidentGroupsView.vue` + `api/incidentGroups.js` + clés i18n `incidentGroups.*` (en.js:25,1319 / fr.js:24,1286). NB : l'API backend incident-groups reste servie — décider si la feature revient ou si on nettoie aussi côté serveur.

**Plans racine** (tous gitignorés) : archiver dans `docs/archived/plans/` (avec `git add -f` ou exception `!docs/archived/` au .gitignore) : `plan_stabilisation_audit`, `plan_redesign_velours`, `plan_responsive`, `plan_accessibilite` (soldé), `plan_design_system` (soldé), `plan_bilan_2026-07`, `plan_v2_global_health` (en prod depuis mai). Garder actifs : `plan_bilan_2026-07-16.md` + ce fichier.

## 4. Documentation

**Sains, ne pas toucher** : FEATURES.md (à jour v1.16.0), CHANGELOG.md, CONTRIBUTING.md (référence du flux release-please), commentaires pyproject (fastapi + tzlocal exacts).

**À corriger (par priorité)** :
| Prio | Doc | Correction |
|---|---|---|
| HAUTE | README.md | `docker-compose.prod.yml` (l.365,368) **n'existe pas** → commande cassée ; corriger vers `docker-compose.yml` |
| HAUTE | CLAUDE.md | § "Processus de release" décrit encore le tag manuel → réécrire sur release-please (aligner sur CONTRIBUTING.md) |
| HAUTE | codemap.md | `MonitorRow` fantôme ; manquent `lockout.py`, `tools/rotate_fernet.py`, `api/auth.js`, `lib/nativeApp.js`, `lib/themeColors.js`, `useDateFormat.js`, `useDetectionAlertBridge.js`, `DetectionAlertBridge.vue` ; « Capacitor 7 » → 8 ; retirer SummaryCard/UptimeHistoryBars/SkeletonText (morts) |
| MOYENNE | README.md | « What's new » bloqué à v1.14 → ajouter 1.15 + 1.16 ; pin FastAPI « <0.137 » (l.58) → `<0.140` ; captures PNG du 13/06 = pré-release VELOURS → refaire ou requalifier la légende |
| MOYENNE | CLAUDE.md | CheckType incomplet (l.95) : manquent `udp · smtp · ping · domain_expiry` ; note Fernet : le `secret` webhook HMAC **est** chiffré |
| BASSE | UPGRADING.md | Figé à v1.0.0 → renvoi vers CHANGELOG + SECURITY.md §7, ou renommer |

## Ordre de bataille proposé

1. **SEC-1** — PR cherry-pick `ae0659f` (redis `!=8.0.0` + dédup httpx). 15 min, déjà revu mergeable.
2. **Vague nettoyage** — branches/worktrees (local, sans PR) + PR code mort (PublicPage, UserTagPermission, shim probe, 5 fichiers frontend, i18n).
3. **Vague docs** — PR unique : README (compose.prod, What's new, pin), CLAUDE.md (§release, CheckType), codemap resync, UPGRADING renvoi. Archivage plans racine.
4. **SEC-2** — SSRF probe IP pinning (porter `_PinnedHostTransport`).
5. **R-1 + R-2 + R-4** — unification évaluateurs d'alerte, fail-open Redis auth, atomicité renotify (chacun avec tests).
6. **P2/P3 du bilan 16/07** (factorisations, découpage monitors.py) + backlog produit 3b/3c — inchangés, à arbitrer.

## Suivi

- [x] 1. SEC-1 pin redis — **PR #277 MERGÉE** (`ac59b8e`, 2026-07-21). Cherry-pick propre, checks requis verts (npm audit rouge = CVE dev-deps préexistantes brace-expansion/node-tar, sans rapport — à corriger via `npm audit fix`, voir 2b). Branche locale `fix/redis-pin` désormais supprimable.
- [x] 2. Nettoyage :
  - [x] 2a. Local — 16 worktrees agents supprimés (root-owned via conteneur alpine), 39 branches locales mergées supprimées (11 nommées + 28 `worktree-agent-*`), 11 branches distantes mergées supprimées + `remote prune`. Restent : `fix/redis-pin` (supprimable), `proto/dashboard-redesign` (référence design).
  - [x] 2b. Code mort — **PR #280 MERGÉE** (`ebdd2e3`, 2026-07-21) : PublicPage + UserTagPermission (+ migration drop), shim probe, fichiers frontend orphelins + i18n. `npm audit fix` — **PR #282 MERGÉE** (`aa6cd6f`) : brace-expansion DoS + node-tar.
- [x] 3. PR docs — **PR #281 MERGÉE** (`883c187`, 2026-07-21) : README (compose.prod, What's new 1.15→1.16, pin FastAPI), CLAUDE.md (§release release-please, CheckType complet, note Fernet HMAC), codemap resync, UPGRADING renvoi, plans archivés dans `docs/archived/plans/`.
- [x] 4. SEC-2 SSRF probe — **PR #283 MERGÉE** (`0ef4008`, 2026-07-21). `_SSRFPinnedTransport` porté côté probe (pinning IP + re-validation par hop de redirect, Host/SNI préservés, URL restaurée pour `final_url`), `SSRFBlockedError` → CheckResult error. 11 tests dédiés, suite probe 160/160.
- [x] 5. R-1/R-2/R-4 :
  - [x] R-2 fail-open Redis auth — **PR #284 MERGÉE** (`65e6b9b`, 2026-07-21). Helpers `redis_get/setex/delete_safe` (core/redis.py) + bascule des 2 chemins d'auth API-key et des invalidations ; panne Redis ⇒ cache miss + fallback bcrypt au lieu de 500. Éviction sautée neutralisée par le fingerprint SA6/S4 + TTL 60 s. Suite serveur 840/840. NB : faux positif CodeQL `py/weak-sensitive-data-hashing` (SHA-256 index de cache, décalage de lignes) rejeté comme les alertes #12/#13.
  - [x] R-4 atomicité renotify — **PR #285 MERGÉE** (`9fea9b6`, 2026-07-21). Commit par incident dans `check_renotify` ; le rollback d'un incident en échec ne jette plus les AlertEvent des incidents précédents du cycle (doublons de renotify). Test d'atomicité dédié.
  - [x] R-1 unification conditions d'alerte — **PR #286 MERGÉE** (`a34bca7`, 2026-07-21). `services/alert_conditions.py` (prédicats purs partagés fire_alerts/simulate_rule), preview couvre les 7 conditions câblées + converge sur la sémantique dispatch (fenêtre SSL per-monitor, seuil non défini = jamais), test garde-fou anti-divergence. Suite 874/874. **Découverte : `tls_grade_below` = valeur d'enum morte** — arbitrée « supprimer » : **PR #287 MERGÉE** (`6bf2ebe`, 2026-07-21).
- [x] 6. Arbitrage rendu (2026-07-21) — les 3 axes validés, ordre ci-dessous.

## Ordre de bataille post-arbitrage (2026-07-21)

**Vague A — dette backend** :
- [x] A1. Suppression Incident Groups côté serveur — **PR #290 MERGÉE** (`615443d`, 2026-07-21, −480 l.) : `api/v1/incidents.py` + schémas `IncidentGroupOut`/`IncidentRef` + tests (tenant scope, recette, extra, smart alerts) + i18n empty-state supprimés. **Conservés à dessein** : modèle `IncidentGroup`, corrélation dans `services/incident.py` et métadonnées inline de `GET /incidents/` (scopées tenant) ; redirect frontend `/incident-groups` → `/incidents` gardé pour les vieux favoris.
- [x] A2. SEC-3 rate-limit GET — **PR #291 MERGÉE** (`1047b64`, 2026-07-21) : les 30 GET sans décorateur sous `api/v1` harmonisés — **60/min** standard (listes + détail), **120/min** chemins chauds (`GET /monitors/`, `/monitors/{id}`, `/monitors/{id}/results` — polling test 3 s), **10/min** export `/config` (aligné sur le PUT), **30/min** postmortem (génération markdown) + publics statiques (`/auth/oidc/config`, `/push/vapid-public-key`). Gate CI étendu : `test_all_get_v1_endpoints_have_rate_limit` (scoping module `whatisup.api.v1.*`) ; exemptions restantes documentées §12 : `/api/health` (health checks LB/probe/ServerSetupView) et `/api/metrics` (scrape Prometheus), hors routers v1. SECURITY.md §12 + FEATURES.md §11 mis à jour. Découverte au passage : `default_limits=["200/minute"]` dans `core/limiter.py` est **inopérant** sans `SlowAPIMiddleware` (non monté) — les GET non décorés étaient réellement sans limite.
- [x] A3. R-3 découpage `api/v1/monitors.py` — **PR #292 MERGÉE** (`7e7aa9e`, 2026-07-21) : fichier monolithe (1955 l. post-A2) → package `api/v1/monitors/` de 9 modules : `crud` (list/create/get/patch/delete/bulk/trigger), `import_export`, `stats` (results/uptime/history/percentiles/probes/report), `health` (health-state/slo/slo-rules — Health Engine V2), `incidents` (+postmortem), `dependencies` (graph/dependencies/composite/correlated/`_would_create_cycle`), `baselines` (dns+schema drift), `annotations`, `_common` (`_get_monitor_or_404`). Déplacement pur, zéro changement de contrat API. **Pièges traités** : ordre d'inclusion des sous-routers dans `__init__.py` (statiques `GET /export`/`/graph` avant `GET /{monitor_id}`, sinon 422 UUID) ; re-export `create_monitor` pour `templates.py` ; 2 clés module mises à jour dans `test_rate_limit_coverage.py` (`monitors.dependencies.*`). Méthode : split par plages sed + header d'imports commun puis `ruff check --fix` (403 imports inutilisés purgés automatiquement). Codemap mis à jour. **Piège majeur découvert** : un router parent agrégeant les sous-routers ajoute un 2e niveau de wrapper lazy `_IncludedRouter` (FastAPI ≥ 0.138) qui **retire le préfixe `/monitors` des `APIRoute.path` internes** → `test_rate_limit_coverage` (introspection routing) cassait. Solution : chaque sous-module porte son propre `APIRouter(prefix="/monitors")` et `main.py` boucle sur le tuple `monitors.routers` au premier niveau.

**→ VAGUE A TERMINÉE** (A1 #290 / A2 #291 / A3 #292, toutes mergées le 2026-07-21). Prochaine étape : vague B (frontend).

**Vague B — dette frontend** :
- [x] B1. R-5 — **PR #293 MERGÉE** (`d61924b`, 2026-07-21). ⚠️ **La prémisse de l'item était fausse** : la généralisation de `<StatusBadge>` était déjà soldée (#192/#196) — aucun fichier hors `StatusBadge.vue` n'utilise `badge-up`/`badge-down`/… Et les 7 fichiers listés ne rendent pas un statut de monitor : `IncidentsView` = cycle de vie incident (ouvert/acquitté/résolu), `SilencesView` = phase de silence, `MaintenanceWindowCard` = phase de maintenance (domaines de valeurs distincts) ; `DependencyGraph`/`ProbeMap`/`ProbesView`/`useMonitorMap` produisent des couleurs résolues pour `fill` SVG et marqueurs/popups Leaflet (hors contexte composant). Y plaquer `StatusBadge` aurait produit de mauvais libellés.
  **Livré à la place (même nature, surface plus visible)** : (1) régression VELOURS corrigée — `useMonitorDisplay.uptimeColor`/`responseTimeColor` rendaient encore la palette Tailwind brute (emerald/amber/red/gray) ; après la PR, **plus aucune couleur de statut hors token dans `src/`** ; (2) bug i18n — chips de filtre `statusFilters` avec « Up »/« Down »/« Error » codés en anglais (même famille que le bug corrigé en #192) + couleurs hors DS ; (3) barème d'uptime ≥99/≥90 dupliqué (useMonitorDisplay) et triplé (ProbeMap : pastille, texte, fill) → unifié dans `lib/themeColors` (`uptimeLevel` + `levelTextClass`/`levelBgClass`/`levelColor`). Test `tests/uptimeLevel.test.js` (13 cas) en garde-fou anti-retour à la palette brute. **Piège Tailwind v4** : les classes doivent rester des littéraux dans les maps — le scanner ne détecte pas les noms construits par interpolation (sinon CSS manquant). 355 vitest verts.
  **Reste** : badges incident/silence/maintenance à harmoniser comme **famille distincte** de `StatusBadge` — à arbitrer séparément, ne pas forcer dans le composant monitor.
- [x] B2. R-6 extraction `MonitorFormFields.vue` — **PR #294 MERGÉE** (`7d76d99`, 2026-07-21). CreateMonitorModal 847 → **321** l., EditMonitorModal 789 → **273** l. **Bug trouvé grâce à la dédup** : les 2 copies du catalogue `checkTypes` avaient divergé avec des libellés **codés en dur en anglais (création) / en français (édition)** — le même type de sonde changeait de langue selon l'écran, indépendamment de la locale ; idem sur ~15 chaînes de champs (port, seuil domaine, type d'enregistrement DNS, mot-clé, chemin JSON, intervalle, timeout, redirections, SSL). Tout passe désormais par i18n : `lib/checkTypeCatalog.js` (libellés via `monitors.check_type.*` existants + nouvelles clés `create_monitor.types.*` en+fr).
  **Choix** : formulaire par **provide/inject** et non par prop — les champs le mutent en `v-model`, ce que `vue/no-mutating-props` signalerait (CI lint en `--max-warnings 0`) ; même convention que `monitors/detail/injectionKeys.js`. Le ref est fourni tel quel (jamais réassigné, `Object.assign`).
  **Rendu préservé** sur 3 points délicats : slot `before-flapping` (le runbook de l'édition doit rester avant le flapping), astuce « membres composite » conditionnée à `mode="create"`, ouverture auto des accordéons déjà renseignés déduite du contenu du formulaire. Corrigé au passage : `applyUaPreset` retourne une nouvelle liste et attend la *valeur* du preset (pas l'id) + garde-fou 20 en-têtes. 405 vitest + build prod verts.
- [~] B3. P2 — **PR #295 (partie 1) MERGÉE** (`4eb2a91`, 2026-07-21) (branche `refactor/b3-shared-helpers`). ⚠️ **Comptages du plan corrigés après vérification** : `formatDuration` existait en **3** exemplaires (pas 4) ; côté probe la vraie duplication portait sur **8 sites SSRF dans 6 checkers**, pas une « factory CheckResult ×7 » (les 51 constructions restantes ont des champs trop dissemblables pour qu'une factory les rende plus lisibles).
  **Livré** : (1) durées d'incident — les 3 vues rendaient le *même* incident de 90 min en « 1.5h » (ProbeTimeline), « 1h30min » (PublicPage) et « 1h 30m » (Incidents), unités codées en dur donc jamais traduites → `useDateFormat.formatDuration(seconds)` + `formatDurationMinutes(minutes)`, unités en i18n `common.duration_*` (en+fr), format retenu `1h 30min` ; (2) probe — `ssrf_blocked_result()` dans `_shared.py` remplace les 8 recopies du triplet (status `error` / préfixe `SSRF blocked` / raison). Enjeu réel : c'est à cette forme qu'un refus SSRF délibéré se distingue d'une panne réseau. `scenario.py` non touché (lève une `ValueError` dans la boucle d'étapes, pas un CheckResult). 418 vitest + build verts ; **suite probe 122 passed / 38 failed identique à main sans le commit** (échecs sandbox connus = pas de réseau sortant, vérifié par stash).
  **Sweep i18n = PR #296 ouverte 2026-07-21** (branche `refactor/b3-i18n-sweep`, ~170 chaînes, scan 268 → 94 candidats restants tous non-traduisibles légitimes). **Même bug de fond qu'en B2** : une partie des chaînes était **codée en français dans une base anglaise** — un anglophone lisait « Certificat SSL », « Voir le screenshot », « Pas encore apprise — en attente d'un check… » et tout le panneau de métriques custom. Couvert : ScenarioBuilder + AddChannelModal (~100 chaînes à eux deux), panneaux de détail monitor, CommandPalette, AppLayout, Settings/Admin/Login/PublicPage, BaseModal, SkeletonRow.
  **Non traduits à dessein** (les traduire serait un bug) : noms de touches (Tab/Enter/Escape — touches physiques), attributs DOM (href/src), noms de produits (Slack/PagerDuty/Teams), masques d'URL et de jeton, acronymes (LCP/CLS/INP, HTTP/SSL/DNS/TTFB). Libellés seed des modèles de scénario laissés en anglais : ce sont des **données stockées** dans la config du monitor, pas de l'affichage.
  **Garde-fou permanent** : `tests/i18nParity.test.js` (clé présente d'un seul côté, feuille vs sous-arbre, traduction vide, placeholder d'interpolation perdu). Non théorique : le sweep a fait collisionner `alerts.add_channel` (chaîne) avec un bloc imbriqué homonyme → renommé `alerts.channel_form`. Piège tests : BaseModal/SkeletonRow traduisent leur aria-label → stubber `vue-i18n` (convention `statusBadge.test.js`) et ne pas sélectionner un bouton par le texte de son libellé. 422 vitest verts.
  **`useAsyncResource` = PR #297 ouverte 2026-07-21** (branche `refactor/b3-async-resource`). ⚠️ **L'item tel qu'écrit n'était pas justifié** — audit des 75 sites avant d'abstraire : (1) **aucun bug** (les 3 sites « sans finally » sont des faux positifs : chaîne `.finally()` dans `stores/probes.js`, `catch` exhaustif dans `useMonitorAlerts`, flux de polling dans `useMonitorTesting`) ; (2) gestion d'erreur **déjà cohérente** (l'intercepteur axios toaste toute requête échouée sauf `skipErrorToast`, donc les `catch` « silencieux » ne le sont pas côté utilisateur) ; (3) **4 stratégies d'erreur distinctes** (finally seul / toast / état de repli / bannière) ⇒ un wrapper à options n'aurait pas raccourci les appels. Factoriser = churn sur 22 fichiers sans bénéfice.
  **Vrai défaut trouvé par l'audit, et livré** : les vues à rechargement par filtre reçoivent leurs réponses **dans le désordre**. Sur `watch([statusFilter, daysFilter], load)`, passer de « 7 j » à « 30 j » avec une 1re requête plus lente affiche les 7 j sous un filtre indiquant 30 — indétectable côté appelant, irreproductible à la demande (dépend de la latence). `useAsyncResource` numérote les appels, n'applique que le plus récent, et seule la requête en tête peut éteindre `loading` (sinon une réponse périmée masque le spinner d'une requête en vol). Option `initialLoading: true` pour AuditView (squelette au 1er rendu). Appliqué à IncidentsView / AuditView / TlsFleetView. Test `tests/asyncResource.test.js` (6 cas) reproduit l'inversion via promesses différées. 428 vitest verts.

**→ VAGUE B TERMINÉE** (B1 #293, B2 #294, B3 #295+#296+#297). Prochaine étape : vague C.

**Vague C — features (arbitré)** :
- [x] C1. Abonnements status page — **PR #298 ouverte 2026-07-21** (branche `feat/c1-status-subscriptions`). **Constat en ouvrant l'item** : `StatusSubscription` était une **impasse complète** — la table se remplissait mais n'était relue par aucun code de dispatch, donc (a) aucun mail n'était jamais envoyé, (b) le jeton d'unsubscribe n'étant délivré par aucun canal, l'endpoint était inatteignable en pratique, (c) la page n'exigeant aucune auth, n'importe qui pouvait abonner l'adresse d'un tiers.
  **Livré** : double opt-in (`confirm_token`/`confirmed_at` + migration ; jeton effacé à la confirmation pour qu'un vieux lien ne réactive pas un abonnement supprimé ; réinscription possible tant que non confirmé, sinon un mail perdu enferme l'adresse) ; `notify_subscribers()` sur ouverture/résolution, branché dans **`fire_alerts`** = point de passage commun à tous les chemins (composite/ponctuel/promu/standard) plutôt que sur chaque site d'appel ; lien de désinscription dans chaque mail.
  **Décisions** : envoi **best-effort** (une panne SMTP ne doit pas interrompre la résolution d'un incident ni priver les autres abonnés) ; migration **conservatrice** (l'existant est marqué confirmé — l'invalider priverait d'un service des abonnés de bonne foi sans recours) ; nouveau réglage **`PUBLIC_BASE_URL`** (derrière un reverse proxy le serveur ne voit ni l'hôte externe ni le schéma) documenté README + `.env.example` ; liens en **query param** `/status/{slug}?confirm=…` car le routeur n'expose que `/status/:slug` (une sous-route serait avalée par le catch-all).
  876 pytest + 428 vitest verts. **Piège tests** : le fixture remplace `get_db` par la session du test **sans commit** → ne pas `refresh()` après un appel HTTP, cela écrase la mutation en attente.
- [x] C2. API tokens à scopes — **PR #299 ouverte 2026-07-21** (branche `feat/c2-api-key-scopes`, 884 pytest verts). **Problème réel** : une clé API rendait un `User` avec **tous ses droits** — une clé émise pour l'extension Recorder ou un script de supervision pouvait supprimer des monitors, créer des canaux d'alerte, lire le journal d'audit. Une clé valait donc un mot de passe.
  **Choix d'application** : vérification dans **`get_current_user`** sur la **méthode HTTP** (`GET`/`HEAD`/`OPTIONS` = lecture, tout le reste exige `write`). C'est le passage obligé de toute route authentifiée ⇒ aucune route ne peut être oubliée, là où un décorateur par endpoint aurait dû être posé sur ~150 routes et aurait fini par en rater. Portées volontairement grossières pour cette raison. Les sessions JWT ne sont pas concernées (seule une clé API porte des scopes).
  **Compatibilité** : défaut `["read","write"]` + migration qui laisse les clés existantes inchangées — restreindre est un choix explicite à la création, jamais une conséquence de la mise à jour (sinon les intégrations déjà distribuées casseraient silencieusement). Validation : scope inconnu → 422 ; `write` sans `read` → 422 (une clé sans lecture serait inerte).
  Frontend : sélecteur « Accès complet / Lecture seule » à la création + mention « Lecture seule » dans la liste. Docs : FEATURES.md §API keys + SECURITY.md (matrice de rotation). 8 tests dédiés (dont le cas `DELETE`, le plus destructeur). 428 vitest + build verts.

  **Piège rencontré** : `_auth_via_user_api_key` rend désormais `(user, scopes)` — son unique appelant direct hors `deps.py` (`test_auth_redis_failopen`) devait être mis à jour, la suite complète l'a attrapé.

**→ VAGUE C TERMINÉE** (C1 #298 mergée, C2 #299). **PLAN INTÉGRALEMENT SOLDÉ** : vagues A + B + C, 10 PRs (#290-#299).
