# Plan d'action — Bilan complet 2026-07-02

> Issu du bilan 4 axes (backend / sécurité / UX-features / mobile) du 2026-07-02.
> Chaque item = un agent dédié, worktree isolé, branche basée sur `main`, commit conventionnel, **pas de push** (revue avant PR).
> Modèle choisi selon la nature : **sonnet** = fix mécanique bien spécifié · **opus** = sécurité/architecture.

## Statut des vagues

| Vague | Contenu | Statut |
|---|---|---|
| 1 | P0 + P1 (6 agents) | ✅ **MERGÉE 2026-07-02** — 6/6 sur main : #222 (A3) `61a156e`, #223 (B3) `bb9aeed`, #224 (A2) `ffc3deb`, #226 (A1) `42efef4`, #227 (B2) `745d4f2`, #225 (B1) `222f96c` + bonus #228 (undici 7.28.0 → npm audit vert). Merge séquentiel avec update-branch entre chaque (CI sur code combiné) ; arbitrage run.sh appliqué (identique A1/B2) ; docs resync (TTL 60s + rate-limits §12, Capacitor 8). Worktrees + branches nettoyés |
| 2 | P2 dette/ops + UX (4 agents) | ✅ **MERGÉE 2026-07-03** — cycle complet (revue → correctif → contre-revue → PR → merge squash séquentiel avec update-branch/CI combinée) : #234 (C4) `5a96ebc`, #231 (C1) `e7c9a18`, #233 (C3) `cf3d9d8`, #232 (C2) `720e389`. CI 15/15 verte à chaque étape, zéro conflit prédit (`git merge-tree`). Worktrees + branches nettoyés. Détail : § Revue vague 2. NB : l'agent C3 initial est mort en laissant du travail non commité → repris et fini par un agent relais |
| 3a | Sécurité structurelle (7 items) | ✅ **MERGÉE 2026-07-09** — 7/7 sur main : #256 (SA1) `7cbcce3`, #257 (SA2) `8de10a9`, #258 (SA3) `7352447`, #259 (SA4) `924c193`, #260 (SA5) `251e0c7`, #261 (SA6) `882e49c`, #262 (SA7) `4adf81e`. Cycle complet (6 revues indépendantes + SA7 implémenté & revu → 2 correctifs SA2/SA3 → 2 contre-revues → 7 PRs → merge squash séquentiel). CI 15/15 verte à chaque PR. Zéro conflit (merge-tree : branches auto-mergeables sur main ET entre elles). Ruleset « Sec » (up-to-date non strict). Détail : § Revue vague 3a |
| 3b-3d | Features/dette produit | 📋 backlog, non délégué |

> **Release v1.15.0 publiée le 2026-07-03** (vagues 1+2 + perf #218) : GitHub Release + images GHCR server/probe 1.15.0 + `app-release.apk` attaché — chaîne release-please auto, 3e run confirmé. FEATURES.md amendé (#237). Traitement PRs ouvertes le même jour : #218 mergée (revue LATERAL : mergeable, ~~follow-up factoriser dans stats.py~~ ✅ **FAIT 2026-07-08 PR #254 `13dea83`** — helper `fetch_latest_results` LATERAL PG/self-join SQLite, consommé par public.py + status.py ×2 + composite.py + dédup monitors.py ; PG 16 réel vérifié ; hors périmètre assumé : tls_fleet.py et les sites groupés par probe) ; dependabot #212/#215/#220/#229 mergées après rebase ; #217 fastapi<0.140 mergée (0.139 corrige le break _IncludedRouter — mémoire à jour) ; Plumber v0.3.86 via #236 (recréée depuis main, SHA vérifié contre le tag officiel ; #230 fork et #219 fermées) ; #235 purge stub lockfile. Reste ouverte : #238 release PR suivante (normal). |

---

## P0 — Bugs latents & sécurité élevée (vague 1)

### A1. Toast global d'erreurs API (frontend) — **sonnet** — branche `fix/api-error-toast`
- Bug latent : `frontend/src/api/client.js` n'a qu'un intercepteur 401 ; `useMonitorPatch.js:23-24` commente « error already surfaces via the API client's global toast » → **ce toast n'existe pas**. Les échecs de PATCH (MonitorDetail, Dashboard, TlsFleet, GroupDetail, IncidentGroups, Admin, Audit) sont silencieux.
- Fix : brancher `useToast` (reactive module-level, importable) dans l'intercepteur de réponse de `client.js`. i18n en+fr. Tests vitest.

### A2. Modèle de confiance probes H1+H2 — **opus** — branche `sec/probe-trust`
- **H2a écriture** : `POST /probes/results` (`probes.py:355`) accepte un résultat pour n'importe quel `monitor_id` sans vérifier `serves_monitor` — alors que `/probes/diagnostics` (`probes.py:319-333`) le vérifie. → appliquer la même garde au flux results.
- **H1 rotation** : `POST /probes/{id}/rotate-key` documenté dans `SECURITY.md:281,436` mais **inexistant**. → l'implémenter (superadmin, nouvelle clé affichée une fois, invalidation immédiate du cache Redis d'auth — fenêtre stale actuelle 300 s).
- Tests serveur obligatoires (forge cross-monitor refusée, rotation + invalidation cache).

### A3. `create_channel` sans contrôle team M2 — **sonnet** — branche `sec/channel-team-check`
- `alerts.py:100-107` fixe `team_id=payload.team_id` sans `assert_can_assign_team` (contrairement à monitors `monitors.py:464` et groups `groups.py:76`). Vecteur explicitement décrit dans le docstring `deps.py:289`.
- Fix + test (rattachement à un team étranger → 403/404).

## P1 — Sécurité moyenne & mobile quick wins (vague 1)

### B1. Cloisonnement WebSocket par tenant M1 — **opus** — branche `sec/ws-tenant-scoping`
- `manager.broadcast` (`ws.py:54-66`) diffuse tout à toutes les sockets ; `/ws/public/{slug}` (non auth) partage le même manager (`ws.py:168`) → un visiteur anonyme reçoit les événements d'incidents de toute l'instance.
- Fix : attacher un scope à chaque connexion (user → build_access_filter ; public → monitors du groupe slug) et filtrer au broadcast. Tests ws.

### B2. Mobile quick wins — **sonnet** — branche `mobile/quick-wins`
1. Bouton retour Android non géré (aucun `@capacitor/app`, aucun listener `backButton`) → l'app quitte au lieu de naviguer.
2. WebSocket jamais suspendu en arrière-plan (`stores/websocket.js` reconnecte toutes les 5 s même app cachée) → `appStateChange` : fermer sur `isActive:false`, reconnecter au retour.
3. `POST_NOTIFICATIONS` absent de `AndroidManifest.xml` (Android 13+, seul `INTERNET` déclaré).

### B3. Couverture audit log M3 — **sonnet** — branche `sec/audit-log-coverage`
- `log_action` absent sur : AlertChannel create/delete, AlertRule create/update/delete, MonitorGroup create/delete, probe PATCH (bascule `is_active` = révocation de facto). `SECURITY.md:80,131,386` exige ces traces (checklist forensique s'appuie dessus).
- Fix + tests (une trace par mutation).

## P2 — Dette / ops / UX (vague 2, après revue vague 1)

| Item | Modèle | Détail |
|---|---|---|
| C1. Leader election boucles de fond | opus | 8 boucles lancées par process (`main.py:56-175`), zéro verrou distribué → duplication si N réplicas. Verrou Redis SETNX ou advisory lock PG par tâche. |
| C2. Auth probe O(n) bcrypt | opus | `deps.py:190-197` : cache miss = scan bcrypt de toute la flotte (TTL 60 s). Index préfixe de clé → candidat unique, et/ou TTL plus long. |
| C3. structlog JSON + request-ID | sonnet | `structlog.configure()` absent, aucun middleware X-Request-ID malgré FEATURES §10 et codemap. Câbler les deux + resync codemap. |
| C4. UX quick wins | sonnet | Tri persistant (`sortKey/sortDir` hors `useFilterPreset`), toast « Annuler » sur bulk delete, `EmptyState` sur 6 vues (Incidents, ApiKeys, Templates, Audit, TlsFleet, IncidentGroups). |

## P3 — Vague 3 (feu vert utilisateur 2026-07-08, 4 axes retenus — mobile reporté à une session dédiée)

> Méthode vagues 1-2 reconduite : agents parallèles en worktrees → revues indépendantes → correctifs → PRs → merges séquentiels (update-branch + CI combinée). Sous-vagues séquentielles.

### Vague 3a — Sécurité structurelle (✅ MERGÉE 2026-07-09 — 7/7)

| Item | Branche | Détail |
|---|---|---|
| SA1. SSRF épinglage IP | `sec/ssrf-ip-pinning` | `_validate_webhook_url` valide le hostname mais la requête re-résout le DNS → rebinding possible. Résoudre une fois, valider l'IP, épingler l'IP résolue pour la requête effective. |
| SA2. Lockout par compte | `sec/account-lockout` | Rate-limit IP seul aujourd'hui. Compteur Redis par compte sur échecs login (seuil/fenêtre), réponse anti-énumération, audit log, TTL auto. |
| SA3. Rotation FERNET_KEY | `sec/fernet-rotation` | Script/CLI MultiFernet : re-chiffrer tous les champs Fernet (AlertChannel configs), doc SECURITY.md, procédure zéro-downtime. |
| SA4. Resync docs + OIDC meta | `sec/docs-oidc-resync` | Table rate-limits SECURITY.md §12 (dont /results 60 vs 600/min) + métadonnées sessions OIDC (`auth.py:476-477`). |
| SA5. common_cause cross-tenant | `sec/common-cause-tenant-filter` | Caveat B1 : `correlated_monitor_ids` de `common_cause_detected` diffusés sans filtre de scope au broadcast WS. Filtrer par scope destinataire. |
| SA6. Cache auth probe durci | `sec/probe-cache-fingerprint` | Reliquat contre-revue A2 : empreinte du hash bcrypt dans la valeur de cache (invalide si hash change) + test pinnant l'ordre commit→éviction. |
| SA7. incident-groups REST cross-tenant | `sec/incident-groups-tenant-filter` | Découvert par la revue SA5 : `GET /incident-groups/` expose monitor_ids + `root_cause_monitor_name` d'autres tenants à tout possesseur d'un incident du groupe ; ownership par `owner_id` seul (pas build_access_filter). Filtrage payload par scope + harmonisation accès. |

Reportés (gros, sessions dédiées) : WebAuthn, SBOM + Cosign. Réserves mineures SA5 consignées (probe_ids/group_id visibles sur sockets publiques — opaques, non bloquant).

#### Revue vague 3a (2026-07-09) — 6 relecteurs indépendants + SA7 revu + 2 correctifs + 2 contre-revues

| Item | Commit(s) | Revue | Correctif | Contre-revue |
|---|---|---|---|---|
| SA1 SSRF pinning | `49d7e82`→#256 `7cbcce3` | ✅ **mergeable tel quel** — transport httpx `_PinnedHostTransport` (supérieur à la spec, TOCTOU structurellement fermé) ; bypasses testés empiriquement (SNI/redirects/formes exotiques/multi-A/IPv6) ; call sites exhaustifs. 13 tests, pytest 790 | — | — |
| SA2 lockout | `4de5789`+`a485a90`→#257 `8de10a9` | ⚠️ avec réserves : R1 doc DoS-lock, **R2 INCR/EXPIRE non atomique (compteur immortel)**, R3 timing oracle. 8 tests, pytest 785 | ✅ `a485a90` — R2 pipeline MULTI/EXEC + EXPIRE(nx=True) atomique + auto-guérison ; R3 burn bcrypt branche user-None ; R1 docstring + runbook SECURITY.md §9. +3 tests, pytest 788 | ✅ **validé** — atomicité réelle prouvée, test discriminant rejoué rouge (assert 0<-1), schéma clés vérifié numériquement |
| SA3 Fernet rotation | `4bfcf29`+`e5729ac`→#258 `7352447` | ❌ **défaut majeur** : `docker-compose.yml` ne passe pas `FERNET_KEY_PREVIOUS` → procédure documentée = outage alertes/TOTP/SSO + perte définitive possible. Code MultiFernet+outil+tests OK. pytest 786 | ✅ `e5729ac` — passthrough compose+`.env.example` ; exit≠0 si unreadable>0 ; SECURITY.md étape 6 (run 0/0 avant destruction clé) ; CLAUDE.md champs Fernet corrigés. +test, pytest 787 | ✅ **validé avec remarques** — C1 prouvé via `docker compose config`, C2 propagation shell end-to-end, régressions nulles (previous vide/malformée gérée) |
| SA4 docs+OIDC | `c05e921`→#259 `924c193` | ✅ **mergeable tel quel** — 137 décorateurs `@limiter.limit` vérifiés 1 à 1 vs table §12 (tous conformes) ; parité session OIDC via `store_refresh_session`. pytest 778 | — | — |
| SA5 common_cause WS | `5d8f5af`→#260 `251e0c7` | ✅ **mergeable tel quel** — copie par destinataire (pas de mutation partagée), filtre keyé sur le champ (3 variantes), publishers recensés exhaustivement. 5 tests (4 rouges pré-fix), pytest 782 | — | — |
| SA6 cache probe | `81822c1`→#261 `882e49c` | ✅ **mergeable tel quel** — double défense (garde écriture + empreinte au hit, non tautologique), invariant post-rotation ; **vérifié par mutation** (M1/M2/M3 rouges). 5 tests, pytest 782 | — | — |
| SA7 incident-groups | `2cbe12b`→#262 `4adf81e` | ✅ **mergeable tel quel** (implémenté cette session + revu indépendamment) — `build_access_filter` owner+team sur 2 routes, `_serialize_group` filtre incident_ids/refs + null root_cause id **et** name hors scope ; pas de mutation ORM, pas de N+1 ; masquage du NOM pinné. 6 tests (3 rouges pré-fix), pytest 783 | — | — |

**Reliquats non bloquants vague 3a** (→ backlog P3) : SA1 — double résolution DNS (pré-check redondant), pool httpx partagé multi-hosts (théorique, documenter « 1 client par destination »), proxies env ignorés, résiduels TOCTOU hors périmètre (`_oidc_discover`, web_push, CGNAT 100.64/10 non bloqué) ; SA2 — `_dummy_hash is None` = 2 bcrypt au 1er appel process (s'auto-corrige), `/totp/disable` sans compteur par compte ; SA3 — pas de batching/verrou rotation (lost update PATCH concurrent, acceptable), `test_main_exit_code` teste la valeur de retour pas la propagation SystemExit ; SA4 — TODO SECURITY.md l.529 incomplet (d'autres endpoints d'écriture sans limite : alerts/rules, auth/logout, delete deps/composite), test n'asserte pas TTL/valeur ip ; SA5 — fuite d'inférence résiduelle assumée (existence corrélation + group_id + shared_probe_ids), routage sur l'ancre inchangé (gap fonctionnel préexistant) ; SA6 — **`_auth_via_user_api_key` même motif non durci + AUCUNE éviction cache à la révocation user (clé révoquée valide ≤60 s)** ← à traiter, comparaison empreinte non constant-time ; SA7 — `.limit()` avant filtre mémoire (top-50 peut évincer des groupes accessibles, préexistant, pas une fuite).

**Note process** : les 6 branches SA1-SA6 partaient de `13dea83` (avant release v1.15.2 `207529c`) → dérive CHANGELOG/manifest/version dans les diffs, sans vraie modif d'agent ; auto-mergeables quand même. Merge séquentiel sans rebase nécessaire (ruleset « Sec » n'impose pas up-to-date strict). Deux worktrees de revue SA1/SA3 d'une session antérieure n'avaient laissé aucun verdict écrit → revues refaites de zéro. Redirection des 2 agents de correctif vers worktrees isolés pour éviter la collision du working tree principal (les branches étant déjà checkout dans des worktrees harness, `git switch` dans le repo principal avait de toute façon échoué). /tmp saturé (~550 Mo de scratchpads sessions 2-3/07) → reviewers contournés via `~/.cache` ; purge refusée par le classifieur (à faire manuellement).

### Vague 3b — Quick wins produit (📋 après 3a)
RSS/Atom status page · export SLA PDF (réutiliser `reports.py`) · canal SMS/voix Twilio (config-gated, comme les autres canaux).

### Vague 3c — Features moyennes (📋 après 3b)
API tokens à scopes (`scopes` JSONB sur `UserApiKey`) · incident manuel status page (`POST /incidents`) · checks SQL/gRPC/Docker (probe).

### Vague 3d — Dette backend (📋 après 3c)
Découpage `monitors.py` (1973 lignes) · bornes boucles verdict/heartbeat · fallback Redis `probe_stats` · tests unitaires `incident_{decider,slo,alerts,correlation}` + `threshold_advisor` · resync `.claude/codemap.md`.

### Mobile (reporté — session dédiée)
Play Store (AAB), iOS, widget Android, pull-to-refresh, App Links, haptics.

---

## Revue vague 1 (2026-07-02) — 6 relecteurs indépendants

| Branche | Verdict revue | Findings majeurs | Correctif |
|---|---|---|---|
| `fix/api-error-toast` (A1) | avec réserves | double affichage inline+toast (~40 sites non flaggés) ; spam toasts sur polling (useMonitorTesting/ProbesView/ProbeMap) | ✅ `ccf8af6` — 59 sites flaggés (sweep complet), passthrough config sur ~25 helpers api, dédup useToast, mineurs (detail vide/5xx/cancel) ; 308/308 vitest, eslint 0 warning |
| `sec/probe-trust` (A2) | avec réserves | H1-a : éviction Redis avant commit DB → l'ancienne clé peut se re-cacher 60 s | ✅ `8bb61d2` — commit avant éviction (best-effort) + composite rejeté + TTL docs + 3 tests ; 33/33, ruff clean |
| `sec/channel-team-check` (A3) | **mergeable tel quel** | aucun | — (mineur : `AlertChannelUpdate` code mort) |
| `sec/ws-tenant-scoping` (B1) | avec réserves | M-1 : refresh lazy inopérant sur sockets publiques (pas de frame entrant) → fuite illimitée post-retrait ; M-2 : user jamais rechargé (superadmin rétrogradé / compte désactivé gardent leur scope) | ✅ `904e458` — refresh piloté horloge serveur (wait_for timeout), User rechargé chaque cycle (4001 si révoqué, superadmin rétrogradé effectif), 1011 sur erreur technique au connect ; 25 tests ws, suite 692/692 |
| `mobile/quick-wins` (B2) | avec réserves | listeners Capacitor dupliqués à chaque remount AppLayout (logout→login) | ✅ `d7d19b5` — guards wired-once + 2 tests ; 297/297 vitest, eslint 0 warning |
| `sec/audit-log-coverage` (B3) | avec réserves | `put_alert_matrix` + `auto-rules` non tracés (bypass de toute la couverture rules) ; trace `probe.update` anonyme/vide | ✅ `758c51c` — matrix_update + auto_create tracés (diff compteurs+conditions), probe.update/delete attribués avec diff, api_key.* réparé + tests attribution, test anti-secret renforcé ; suite 696/696 |

### Contre-revue des correctifs (2026-07-02)

| Fix | Verdict contre-revue | Notes |
|---|---|---|
| A1 `ccf8af6` | ✅ validé | gates ré-exécutées indépendamment (308/308 vitest, eslint 0) ; positions axios toutes correctes ; ~30 sites échantillonnés sans régression ; le `catch{}` ProbeMap répare une unhandled rejection préexistante |
| A2 `8bb61d2` | ✅ validé avec remarques | vecteur revu fermé ; reste une variante résiduelle étroite (slow-path bcrypt en vol pendant le commit peut re-cacher l'ancienne clé ~100-300 ms → 60 s) — durcissement suggéré : empreinte du hash dans la valeur de cache ; aucun test ne pinne l'ordre commit→éviction |
| B1 `904e458` | ❌ défaut majeur F-1 | timeout réarmé plein à chaque frame → pings dashboard 30 s < fenêtre 60 s = refresh jamais déclenché → M-2 inopérant + régression | 
| B1 `16594d4` (re-fix F-1) | ✅ validé | vérifié empiriquement : pas de busy-loop (24 recomputes/0.5 s attendus ~25), pas d'amplification sous spam (1 recompute/fenêtre pour ~500 frames), 2 tests prouvés échouer pré-fix ; deadline glissante + garde route publique OK ; 27 tests ws, suite 694/694 |
| B2 `d7d19b5` | ✅ validé | contre-preuve exécutée : les 2 nouveaux tests échouent sur le code pré-fix ; flag levé après null-check import (pas de latch sur échec) |
| B3 `758c51c` | ✅ validé avec remarques | tests api_keys prouvés échouer sur main ; « updated » du matrix_update compte les lignes inchangées ; trace émise même sur no-op (documenté) ; pas de test d'attribution probe.delete |

**Reliquats non bloquants issus des contre-revues** (à verser en P3/backlog) : durcissement cache probe (empreinte hash), test d'ordre commit→éviction, `AuditLog.diff` = JSON générique dont l'échec de sérialisation ferait échouer la requête entière (note architecturale), `_audit_entries` sans ORDER BY dans les tests, dédup toast par message+type (edge type différent), spread `{params, ...config}` clobberable en théorie ; `ConnectionManager.disconnect` non idempotent (latent, aucun chemin de double appel aujourd'hui).

**Arbitrage merge** : conflit `tools/pre-commit/run.sh` entre A1 et B2 → garder la version **A1** (monte le worktree à son chemin réel = chaîne gitdir complète), reprendre le guard bash portable `"${ARR[@]+…}"` de B2, et passer à `git rev-parse --path-format=absolute --git-common-dir`.
**À corriger sur main au merge** : CLAUDE.md § Mobile obsolète (projet déjà en Capacitor 8, pas 7) ; CLAUDE.md § deps « TTL 300s » cache probe → 60 s ; SECURITY.md §12 rate-limits périmés (/results 60 vs 600, /heartbeat 30 vs 120).
**Follow-ups actés (non bloquants)** : back Android ne ferme pas modales/drawer ; dédup/diff before-after sur les updates audit ; matrix-templates superadmin non tracés ; payloads `correlated_monitor_ids` cross-tenant (P3, déjà listé) ; `check_result` = code mort frontend ; `AlertChannelUpdate` code mort.

## Revue vague 2 (2026-07-03) — 4 relecteurs + 4 correctifs + 4 contre-revues

| Branche | Verdict revue | Findings majeurs | Correctif | Contre-revue |
|---|---|---|---|---|
| `ops/leader-election` (C1, `092c5f1`) | avec réserves (aucun majeur) | `WatchError` hérite de `RedisError` → invalidation WATCH classée « panne Redis » = fail-open à tort (fenêtre de double exécution) ; `recover_digest_windows` one-shot non gated au boot ; `try_acquire` non blindé dans la boucle | ✅ `268dc1f` — WatchError = perte de leadership (renew→False, release silencieux), `_recover_digests_once` gated `LeaderLock("digest_recovery")`, blindage + reprise de bail orphelin (`GET == token` → renew WATCH-guardé), docstring chevauchement ; 742 tests, 16/16 leader | ✅ validé — preuve pré-fix rejouée (3 rouges sur `092c5f1`), race takeover probée adversarialement, CancelledError non avalée (shutdown propre vérifié) ; 4 remarques mineures → backlog |
| `perf/probe-auth-index` (C2, `8f79d7d`→`1d697c3`) | **mergeable tel quel** (3 mineurs) | aucun — préfixe 64 bits sans valeur seule (bcrypt sur clé entière), pas de lockout legacy, rotation A2 cohérente, collision par index unique DB, Alembic head unique | ✅ `9082850` — fallback auto-cicatrisant sur prefix miss (état « clé pointée + préfixe NULL » post-downgrade/upgrade n'est plus irrécupérable) + 4 tests (secret faux = 1 bcrypt sans scan, re-rotation new-gen, probe inactive, self-heal) | ✅ validé avec 1 durcissement → appliqué en `3d385aa` : self-heal via UPDATE conditionnel `WHERE api_key_prefix IS NULL` (une rotation concurrente ne peut plus être clobberée par un self-heal en vol → probe briquée) ; 738 tests, ruff OK |
| `ops/structlog-request-id` (C3, `0c7b303`) | **défaut majeur** | M1 : `uvicorn.run()` sans `log_config=None` → le dictConfig par défaut d'uvicorn ré-attache un handler access plain-text APRÈS `configure_logging()` en prod Docker (double ligne par requête + logs cycle-de-vie non-JSON) — vérifié empiriquement en conteneur ; + X-Request-ID entrant non validé, 500 sans header, CORS expose absent | ✅ `7125cea` — `log_config=None` + re-config lifespan, regex `^[A-Za-z0-9._-]{1,128}$` sinon uuid4, handler Exception qui construit la 500 JSON avec header PUIS re-raise, `expose_headers=["X-Request-ID"]`, doc stderr ; 745 tests, 7 tests prouvés rouges pré-fix | ✅ validé — E2E prod réel (uvicorn live, pas TestClient) : 22/22 lignes JSON, 0 plain-text, 500 envoyée au client avec header avant re-raise, valeur injectée absente de tous les logs ; 4 remarques cosmétiques → backlog |
| `ux/quick-wins` (C4, `e46d606`→`1dfb87f`) | avec réserves | M1 : doublons d'ids si Undo après un `fetchAll` intermédiaire pendant la fenêtre de 6 s (résurrection par navigation Dashboard) ; R1 assumée : reload pendant la fenêtre = delete jamais envoyé (fail-safe, wording « removed ») | ✅ `942f3cd` — registre module-level `pendingDeleteIds` filtré dans `fetchAll` + dédup/démarquage dans onAction/onExpire (tous chemins d'erreur), `verdictFilter` dans `hasActiveIncidentFilters`, clearFilters préserve le tri ; 346 vitest, 2 tests M1 rouges pré-fix | ✅ validé avec remarques — aucune fuite du registre (tous les chemins démarquent), dédup préserve position + fraîcheur serveur, deux bulk deletes indépendants ; preuve pré-fix rejouée (2 rouges sur HEAD~1) |

**Note process** : l'agent C3 initial est mort sans commit (2e occurrence après B1 en vague 1) — travail repris par un agent relais qui a aussi corrigé 2 bugs latents de l'ébauche (clear_contextvars avant le log d'accès, double access-log uvicorn).

**Reliquats non bloquants vague 2** (backlog P3) : C1 — PEXPIRE non vérifié dans `_renew` (faux True possible sur Redis < 6.0.9 uniquement), asymétrie fail-open du GET fallback si Redis tombe entre SET NX et GET, `release()` non gardé dans `_recover_digests_once`, test release-WatchError non discriminant, latence de failover = cadence de la tâche (retention leader mort à 03:00 = purge sautée un jour, bénin) ; C2 — oracle timing préfixe connu/inconnu acté (schéma standard, 64 bits inénumérable) ; C3 — double traceback par 500 en prod (`uvicorn.error` sans request_id, non corrélable), `request_failed` sans duration_ms/status_code, chemin lifespan-configure_logging non couvert par test (ASGITransport sans lifespan), test 500 fragile si pytest-xdist un jour ; C4 — `fetchAll` fire-and-forget dans onExpire (unhandled rejection possible, pattern préexistant), GroupDetailView (hors-store) affiche encore les monitors pendant la fenêtre de 6 s (cosmétique), R1 à documenter dans la PR (+ flush `visibilitychange` en piste pour Capacitor), dismiss du toast ≠ annulation (UX). Hygiène hors branche : `frontend/frontend/package-lock.json` (stub vide 82 o) tracké sur main depuis `badd0da` → chore de purge séparé.

## Suivi vague 1 (2026-07-02)

| Branche | Agent | Modèle | Statut |
|---|---|---|---|
| `fix/api-error-toast` | A1 | sonnet | ✅ `e0676b1` — intercepteur global d'erreurs (skip 401/refresh, detail FastAPI ≤200c sinon i18n errors.\* en+fr), opt-out `skipErrorToast` câblé sur les 28 call sites qui toastaient déjà (anti double-toast) ; 12 tests intercepteur, 298 vitest verts, eslint 0 warning. ⚠️ fixe aussi `tools/pre-commit/run.sh` (worktrees) — B2 le patche différemment → conflit à arbitrer au merge |
| `sec/probe-trust` | A2 | opus | ✅ `135a027` — H2 : garde de scope sur `/probes/results` (403 si `network_scope` du monitor ≠ `network_type` de la probe ; `all` reste permissif — même sémantique que le heartbeat, O(1) sans DB, log `probe_result_scope_rejected`). H1 : `POST /probes/{id}/rotate-key` superadmin + invalidation immédiate du cache Redis via index inverse `probe_auth_rev:{probe_id}`. SECURITY.md mis à jour. 10 nouveaux tests, suite 684/684 verte. NB hors scope : SECURITY.md §12 dit 60/min sur /results, code = 600/min |
| `sec/channel-team-check` | A3 | sonnet | ✅ `cd8705e` — `assert_can_assign_team` sur create_channel + rate-limit 30/min manquant ajouté ; autres routes vérifiées saines (rules sans team_id, pas d'update channel) ; 3 tests régression, suite complète 680/680 verte |
| `sec/ws-tenant-scoping` | B1 | opus | ✅ `9e8d504` (après relance — 1er agent mort sans commit) — scope par connexion (`UNAUTHED` → rien ; dashboard = monitors accessibles via `build_access_filter`+teams, refresh lazy ≤60 s sur keep-alive, fail-safe ; superadmin = tout ; public slug = monitors du groupe) ; filtre broadcast = lookup set en RAM, zéro DB/message ; durcissement bonus : JWT d'un user supprimé/inactif → close 4001 ; payloads inchangés (zéro risque frontend). 21/21 tests ws, suite 688/688 verte. ⚠️ Caveat suivi : `common_cause_detected.correlated_monitor_ids` livré sur le monitor ancre — UUIDs corrélés potentiellement cross-tenant (sévérité basse, à suivre en P3) |
| `mobile/quick-wins` | B2 | sonnet | ✅ 3 commits (`814d734`→`170d3e1`) — back button (`lib/nativeApp.js`), suspension WS arrière-plan, POST_NOTIFICATIONS ; 295 vitest verts ; bonus fix worktree `tools/pre-commit/run.sh` |
| `sec/audit-log-coverage` | B3 | sonnet | ✅ `4fee365` — 14 mutations tracées (channels/rules ×5, groups ×3, probe PATCH, + bonus maintenance ×3 et templates ×3), zéro secret loggé ; 15 nouveaux tests + 55 existants verts, ruff clean |
