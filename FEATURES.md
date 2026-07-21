# WhatIsUp — Inventaire des Fonctionnalités

> **Source de vérité** des features livrées. À amender à chaque release.
> Référence : **v1.16.2** (2026-07-21) — vague fiabilité post-état-des-lieux (SEC-2 + R-1/R-2/R-4) : SSRF probe HTTP (portage du pinning IP SA1 côté probe — transport httpx épinglé, re-validation par hop de redirect), fail-open Redis sur l'auth API-key (panne Redis ⇒ fallback bcrypt, plus de 500), atomicité renotify (commit par incident), unification du matching des conditions d'alerte (prédicats purs partagés dispatch/preview, simulateur 7/7 conditions + garde-fou anti-divergence, enum morte `tls_grade_below` supprimée). Précédent : **v1.16.0** (2026-07-20) — 2e vague sécurité post-audit (SA1-SA7 + S1/S2/S4) : SSRF anti-DNS-rebinding (IP résolue épinglée sur le transport httpx), lockout compte par utilisateur + anti-énumération timing, rotation `FERNET_KEY` (MultiFernet + outil `rotate_fernet`), scoping cross-tenant des payloads WS (`correlated_monitor_ids`) et `incident-groups`, durcissement cache auth probe **et** API-key utilisateur (fingerprint + révocation immédiate), SSRF sur le checker `ping`, comblement rate-limit sur 19 endpoints (teams, alerts rules, onboarding, audit + sweep). Précédent : **v1.15.0** (2026-07-03) — durcissement sécurité post-audit 2026-07 (WebSocket scopé par tenant, confiance probe scope-bindée + rotation de clé, couverture audit log des mutations de config), leader election Redis, logs JSON structurés + X-Request-ID, perf (auth probe par préfixe indexé, `GET /monitors/` 7869 → 0,6 ms) et quick wins UX (toast erreurs global, tri persistant, undo bulk delete) & mobile (back Android, WS en arrière-plan, POST_NOTIFICATIONS). Socle : design system consolidé + responsive (v1.14), VELOURS + a11y gates CI (v1.13), 2FA TOTP + sessions actives (v1.12), Health Engine V2 (M0-M5, en prod sur 17/17 monitors depuis 2026-05-06).
> Dernière release : **v1.16.2** (2026-07-21). Précédente : **v1.16.1** (2026-07-20) — docs (FEATURES.md v1.16.0).
> Pour la chronologie détaillée, voir `CHANGELOG.md`.

**Légende** : ✅ livré · 🔬 livré + tests automatisés · 🚧 partiel (voir notes).

---

## Sommaire

1. [Authentification & Utilisateurs](#1-authentification--utilisateurs)
2. [Monitoring — Types de checks](#2-monitoring--types-de-checks)
3. [Sondes (Probes)](#3-sondes-probes)
4. [Incidents & Corrélation](#4-incidents--corrélation)
5. [Alerting](#5-alerting)
6. [Status pages publiques](#6-status-pages-publiques)
7. [Dashboard & UX](#7-dashboard--ux)
8. [Maintenance windows](#8-maintenance-windows)
9. [Audit & Compliance](#9-audit--compliance)
10. [Infrastructure & Déploiement](#10-infrastructure--déploiement)
11. [Sécurité](#11-sécurité)
12. [CI/CD & Tests](#12-cicd--tests)
13. [Mobile (Capacitor)](#13-mobile-capacitor)
14. [Extensions & Intégrations](#14-extensions--intégrations)
15. [Internationalisation](#15-internationalisation)
16. [Health Engine V2 (Global)](#16-health-engine-v2-global)
17. [Réseau & Intelligence (V2-02)](#17-réseau--intelligence-v2-02)
18. [Récap statistiques](#18-récap-statistiques)

---

## 1. Authentification & Utilisateurs

### JWT & sessions
- ✅ JWT HS256 — access 15 min / refresh 7 j (`core/security.py`)
- ✅ Refresh token Redis avec hash SHA-256 + TTL + rotation à chaque `/auth/refresh`
- ✅ `/auth/logout` révoque le refresh côté Redis
- ✅ Bearer header obligatoire — pas de token en query/URL
- 🔬 **Lockout compte par utilisateur + anti-énumération** (v1.16, audit SA2) — compteur d'échecs Redis (`INCR`/`EXPIRE NX` en pipeline atomique, auto-cicatrisation d'un TTL perdu) : verrouillage temporaire après N tentatives ; la branche compte inconnu/inactif de `/auth/login` brûle un bcrypt factice pour égaliser le timing avec un mot de passe faux sur un compte réel (plus d'oracle de timing pour deviner les emails enregistrés) ; fail-open si Redis down ; runbook de déverrouillage manuel (`SECURITY.md §9`)
- 🔬 **Sessions actives** (v1.12) — les refresh tokens portent des métadonnées (`created_at` / `ua` / `ip`) et constituent la liste de sessions ; `POST /auth/sessions/list`, `DELETE /auth/sessions/{id}`, `POST /auth/sessions/revoke-all` + UI Settings (badge « cet appareil », révocation par ligne, « déconnecter les autres »). La rotation hérite des métadonnées de la session d'origine ; claim `jti` sur les refresh tokens (deux logins dans la même seconde = deux sessions distinctes) (`api/v1/sessions.py`)

### 2FA TOTP (v1.12)
- 🔬 Enrôlement : `POST /auth/totp/setup` (QR + secret) → `POST /auth/totp/enable` (1er code valide active) → **8 codes de récupération** à usage unique affichés une seule fois (`api/v1/totp.py`)
- 🔬 Login : si 2FA actif, `/auth/login` renvoie un défi MFA (`mfa_token` court, claim `type=mfa`, n'ouvre que `/verify`) ; `POST /auth/totp/verify` l'échange contre la paire access/refresh avec un code TOTP **ou** un code de récupération
- 🔬 Désactivation `POST /auth/totp/disable` = mot de passe **et** code
- 🔬 Stockage : secret TOTP chiffré Fernet, codes de récupération bcrypt, garde anti-rejeu Redis (un code TOTP n'est utilisable qu'une fois dans sa fenêtre)
- 🔬 UI : section Settings (activer/désactiver, QR via `qrcode`, modale codes de récupération) + écran second facteur dans `LoginView` avec bascule code de récupération
- 🔬 Dépendances : `pyotp` (serveur), `qrcode` (frontend) ; nécessite `FERNET_KEY`

### OIDC / SSO
- ✅ OIDC authorization code + PKCE complet (`api/v1/auth.py`)
- ✅ Configuration entièrement via UI (pas de redémarrage), stockée chiffrée (Fernet) dans `system_settings`
- ✅ Auto-provisioning configurable au 1er login (opt-in admin)
- ✅ Account linking via `user.oidc_sub` (unique)
- ✅ Scopes configurables (défaut : `openid email profile`)
- ✅ `OidcCallbackView` côté frontend

### Inscription & profils
- ✅ Mode invite-only par défaut (`/auth/register` → 403)
- ✅ Bcrypt 12-rounds (async) sur les mots de passe
- ✅ Self-update `PATCH /auth/me` limité à `full_name` + `timezone` — escalade silencieusement bloquée
- ✅ Flag `is_superadmin` (immutable hors superadmin)
- ✅ Flag `can_create_monitors` (par défaut `false` pour les nouveaux comptes)
- ✅ Timezone IANA par utilisateur (validation stricte → 422 si invalide)

### Teams & RBAC
- ✅ `Team` avec rôles `owner > admin > editor > viewer` (`models/team.py`)
- ✅ Monitors / channels / maintenance windows team-scoped (rétrocompatible single-user)
- ✅ `TeamMembership` (user × team × role)
- ✅ CRUD `/api/v1/teams/`

### Tags & RBAC fin
- ✅ Tags `key:value` many-to-many sur monitors
- ✅ `UserTagPermission` : view / edit / admin
- ✅ `AlertRule.tag_selector` ciblant un tag
- ✅ Filtres dashboard par tag

### API keys
- ✅ Personal API keys utilisateur (`wiu_u_<32 chars>`, bcrypt, expiry, revoke, last_used_at, prefix)
- 🔬 **Cache d'auth API-key durci** (v1.16, audit S4, portage du pattern SA6 probe) — valeur cache empreinte `user_id|key_id|SHA-256[:16]` du hash bcrypt vérifié ; le fast-path recharge la clé live (`is_revoked`/`expires_at`) et compare l'empreinte en temps constant (`hmac.compare_digest`), évince sur mismatch → **révocation immédiate**, plus d'attente du TTL (60 s) ; slow-path relit la clé juste avant l'écriture cache et l'ignore si elle n'est plus valide (ferme la race bcrypt-en-vol pendant une révocation)
- 🔬 Probe API keys — format `wiu_<prefix>.<secret>` (v1.15) : préfixe non-secret 64 bits indexé en DB + bcrypt sur la clé entière → **1 seule vérification bcrypt** au lieu du scan O(n) de la flotte ; fallback legacy `wiu_<secret>` avec auto-cicatrisation vers le nouveau format ; cache Redis SHA-256[:32]
- 🔬 Rotation `POST /probes/{id}/rotate-key` (v1.15, superadmin, 10/min, audit-loggé) — éviction immédiate du cache Redis via index inverse (l'ancienne clé cesse de fonctionner sans attendre le TTL)
- 🔬 **Fail-open Redis sur l'auth API-key** (v1.16.2, R-2) — helpers `redis_get/setex/delete_safe` (`core/redis.py`) : panne Redis ⇒ cache miss + fallback bcrypt au lieu d'un 500 sur toute auth user-key/probe ; les évictions de rotation/révocation tolèrent aussi la panne (entrée périmée neutralisée par le fingerprint re-validé au fast-path + TTL 60 s) — aligne l'auth sur leader election et lockout, déjà fail-open ; réservé aux chemins cache-only (pas les compteurs rate-limit ni les files digest)

---

## 2. Monitoring — Types de checks

| Type | Options | Fichier checker |
|---|---|---|
| `http` | status codes, follow_redirects, SSL warn-days (+ pinning SHA-256 V2-02-05), body regex, expected_headers (exact ou `/regex/`), keyword (+ negate), expected_json_path/value, json_schema, schema drift baseline, waterfall (DNS+TTFB+download), custom metrics push, **custom_headers per-monitor + UA presets** (v1.7) | `probe/whatisup_probe/checkers/http.py` |
| `tcp` | port, timeout, banner capture | `checkers/tcp.py` |
| `udp` | port, timeout (ICMP unreachable / open) | `checkers/udp.py` |
| `dns` | record_type (A/AAAA/CNAME/MX/TXT/NS), expected_value, custom nameservers, **DNS drift** (baseline auto-learn), **split horizon** (baseline interne/externe distincte) | `checkers/dns.py` + `services/dns.py` |
| `smtp` | port, STARTTLS toggle, EHLO handshake, banner-to-ready ms | `checkers/smtp.py` |
| `ping` | ICMP via `ping` système, RTT | `checkers/ping.py` |
| `domain_expiry` | WHOIS, warn-days configurable, days remaining | `checkers/domain_expiry.py` |
| `keyword` / `json_path` | extension du check `http` | `checkers/http.py` |
| `scenario` | Playwright (navigate / click / fill / assert / screenshot / wait / scroll), Core Web Vitals (LCP/CLS/INP), variables `secret: true` chiffrées Fernet, pool Chromium partagé, `MAX_CONCURRENT_SCENARIOS` | `checkers/scenario.py` |
| `heartbeat` | dead-man's switch `/api/v1/ping/{slug}`, grace_seconds | `services/heartbeat.py` |
| `composite` | aggregation `all_up` / `any_up` / `majority_up` / `weighted_up`, weights, cycle detection | `services/composite.py` |

### Options communes par monitor
- `interval_seconds`, `timeout_seconds`, `enabled`
- `ssl_check_enabled`, `ssl_expiry_warn_days`
- `network_scope` (`all` / `internal` / `external`)
- `flap_threshold` + `flap_window_minutes` (override par monitor)
- `auto_pause_after` (consécutifs, nullable = désactivé)
- `data_retention_days` (override de la rétention globale)
- `runbook_enabled` + `runbook_markdown` (renderer maison safe HTML escape)
- `slo_target` + `slo_window_days`
- `tags` + `team_id` + `group_id`

---

## 3. Sondes (Probes)

- ✅ Register `POST /api/v1/probes/register` — name unique + location + network_type + GPS
- ✅ Geocoding via Nominatim (sans clé API)
- 🔬 **Rotation de clé** `POST /probes/{id}/rotate-key` (v1.15, superadmin) — nouvelle clé `wiu_<prefix>.<secret>`, éviction cache Redis immédiate (index inverse), audit-loggé
- 🔬 **Auth par préfixe indexé** (v1.15) — le préfixe non-secret de la clé sélectionne la probe en DB → 1 bcrypt au lieu du scan O(n) de toutes les clés de la flotte ; fallback legacy + auto-cicatrisation
- 🔬 **Confiance probe scope-bindée** (v1.15, audit H1/H2) — `POST /probes/results` rejette tout résultat pour un monitor hors du scope de la probe (`network_scope`, assignation) : une probe compromise ne peut plus forger des résultats arbitraires (`probe_result_scope_rejected` loggé)
- 🔬 **Cache d'auth probe fingerprinté** (v1.16, audit SA6) — ferme la race « rotate-key + bcrypt en vol » : la valeur cache embarque une empreinte SHA-256[:16] du hash bcrypt vérifié, re-vérifiée sans I/O supplémentaire au fast-path (évince sur mismatch) ; le slow-path relit le hash live juste avant l'écriture et l'ignore s'il n'est plus courant (`probe_auth_cache_write_skipped_stale_hash`) — une clé tournée ne peut plus se ré-authentifier via une entrée cache périmée pendant jusqu'à 60 s
- ✅ `network_type ∈ {internal, external}` — séparation panne réseau corp vs internet
- ✅ Probe groups admin → user (RBAC accès aux sondes)
- ✅ Carte Leaflet temps réel (`ProbeMap.vue`) avec status 24 h
- ✅ Heartbeat probe → incident si ping absent > interval+grace (15 s par défaut)
- ✅ Trigger-now via Redis pub/sub (`scheduler.py` du probe)
- ✅ Config sync `GET/PUT /api/v1/config` (export JSON + import déclaratif, JWT ; rate-limit 10/min sur le PUT)
- ✅ **ASN enrichment (V2-02-01)** — chaque sonde résolue automatiquement vers son ASN + AS-name via Team Cymru DNS (`services/probe_enrichment.py`). Champs `Probe.public_ip`, `asn`, `asn_name`, `ixp_membership`, `asn_updated_at`. Refresh opportuniste à chaque heartbeat si stale (24 h par défaut, configurable via `ASN_REFRESH_HOURS`) + tâche de fond toutes les 6 h. Backend configurable `ASN_LOOKUP_PROVIDER ∈ {cymru, disabled}`. Best-effort : aucun blocage du heartbeat en cas d'échec lookup.
- ✅ **Outbound IP intelligence (V2-02-07)** — la sonde résout sa propre IP de sortie via `api.ipify.org` (+ fallbacks `ifconfig.me`, `icanhazip.com`) et l'envoie dans le heartbeat. Champs `Probe.self_reported_ip` + `Probe.self_reported_asn`. Si différent de `public_ip` (vu par le serveur via `request.client.host`) → badge `NAT/VPN` UI + tooltip explicatif. Détecte les setups proxy / NAT / VPN qui font passer une sonde pour autre chose qu'elle prétend (`probe/whatisup_probe/public_ip.py`).

---

## 4. Incidents & Corrélation

### Cycle de vie
- ✅ `Incident` : `started_at`, `resolved_at`, `duration_seconds`, `scope ∈ {global, geographic}`, `affected_probe_ids` (JSONB), `first_failure_at` (MTTD)
- ✅ Ack/Unack (`acked_at`, `acked_by_id`) + auto-clear sur résolution
- ✅ Snooze (`snooze_until`, 5–1440 min) — distinct de l'ack open-ended
- ✅ Bulk ack `POST /incidents/bulk-ack`

### Détection
- ✅ Flapping (`flap_threshold` × `flap_window_minutes`, override par monitor)
- ✅ **Anomaly detection** — z-score sur fenêtre 7j ± 3h (jour/nuit) (`services/anomaly.py`)
- ✅ **Threshold advisor** statistique (`services/threshold_advisor.py`)
- ✅ **Schema drift** (baseline + hash) sur réponses HTTP
- ✅ **Network verdict (V2-02-02)** — classification automatique panne service vs partition réseau (`services/network_verdict.py`). Champ `Incident.network_verdict ∈ {service_down, network_partition_asn, network_partition_geo, inconclusive}` calculé à l'ouverture puis recompute toutes les 5 min tant que ouvert. Distingue ASN-level partition (un opérateur tombe), geo-level partition (une région tombe) d'une vraie panne service. Foundation pour règle "ne pas paginer si network_partition_*".

### Corrélation
- ✅ `IncidentGroup` : `triggered_at`, `resolved_at`, `cause_probe_ids`, `correlation_type ∈ {probe, group, dependency, pattern}`, `root_cause_monitor_id`
- ✅ Common cause : fenêtre 90 s + intersection JSONB `?|` (Postgres) avec fallback Python
- ✅ Dépendances parent → child + `suppress_on_parent_down` + cycle detection 5 hops
- ✅ Graphe SVG force-directed interactif (`DependencyGraph.vue`)
- ✅ Patterns de corrélation persistés (`correlation_pattern.py`)
- 🔬 **`incident-groups` scopé par tenant** (v1.16, audit SA7) — la corrélation tourne globalement sur des sondes partagées ; l'accès utilise `build_access_filter` (owner OU team) et le payload est réécrit par requêteur (monitors hors tenant filtrés/nullifiés) ; superadmin voit tout. **Depuis post-v1.16.2 : les endpoints REST dédiés `GET /incident-groups/` sont supprimés** (vue frontend débranchée depuis longtemps) — les groupes restent exposés via les métadonnées inline de `GET /incidents/` (`correlation_type`, `root_cause_monitor_name`, `group_monitor_names`), elles-mêmes scopées tenant

### Post-mortem
- ✅ Génération markdown automatique à la résolution (`GET /monitors/{id}/incidents/{inc}/postmortem`)

### Diagnostic Engine (V2-01)
- ✅ **V2-01-01** Auto-traceroute corrélé sur incident — à l'ouverture, chaque sonde affectée collecte traceroute / dig +trace / openssl handshake / icmp ping / curl verbose, persistés dans `incident_diagnostics` (`models/incident_diagnostic.py`, `services/diagnostics.py`). UI : section dépliable "Diagnostic" dans `IncidentsView`.

### Renotify
- ✅ Escalade périodique (`services/renotify.py`) — interval par règle, skip si snoozed/acked
- 🔬 **Atomicité par incident** (v1.16.2, R-4) — commit après chaque incident traité : l'échec d'un dispatch ne jette plus les `AlertEvent` déjà enregistrés pour les incidents précédents du cycle (avant : renotifies envoyés aux canaux mais non tracés → re-déclenchés au cycle suivant)

---

## 5. Alerting

### Canaux (11)
| Canal | Fichier | Notes |
|---|---|---|
| Email | `channels/email.py` | SMTP, TLS/STARTTLS, `aiosmtplib` |
| Webhook | `channels/webhook.py` | HMAC-SHA256, template `string.Template` (safe_substitute) |
| Telegram | `channels/telegram.py` | bot_token chiffré Fernet |
| Slack | `channels/slack.py` | webhook URL chiffré |
| Discord | `channels/discord.py` | **T2-10** webhook URL chiffré, embed format |
| Mattermost | `channels/mattermost.py` | **T2-11** webhook (format proche Slack mais dédié) |
| Microsoft Teams | `channels/teams.py` | **T2-12** Adaptive Card via webhook |
| PagerDuty | `channels/pagerduty.py` | integration_key chiffré, severity mapping |
| Opsgenie | `channels/opsgenie.py` | api_key chiffré, team/responder routing |
| Signal | `channels/signal.py` | gateway `bbernhard/signal-cli-rest-api` |
| FCM | `services/fcm.py` | Firebase push mobile (actions ack/snooze) |

### Règles
- ✅ Cibles : `monitor_id` | `group_id` | `tag_selector`
- ✅ Conditions : `all_down`, `any_down`, `ssl_expiry`, `response_time_above`, `response_time_above_baseline`, `anomaly_detection`, `schema_drift`
- 🔬 **Matching unifié dispatch/preview** (v1.16.2, R-1) — prédicats purs `services/alert_conditions.py`, source de vérité unique partagée entre `fire_alerts` (dispatch réel) et `simulate_rule` (préviz UI) ; le simulateur couvre désormais les **7 conditions** (baseline via la même moyenne 7 j, anomalie via le même `compute_zscore`, schema drift) et converge sur la sémantique du dispatch (fenêtre SSL per-monitor + cert invalide, seuil non défini = ne fire jamais) ; test garde-fou : toute nouvelle `AlertCondition` sans support preview casse la suite ; enum morte `tls_grade_below` supprimée (jamais présente dans le type PG — l'API la refuse désormais en 422 au lieu d'un 500 à l'INSERT)
- ✅ `min_duration_seconds` — délai avant fire
- ✅ `renotify_after_minutes` — escalade
- ✅ `threshold_value`, `baseline_factor`, `anomaly_zscore_threshold`
- ✅ `digest_minutes` — agrégation alertes (Redis-backed)
- ✅ `schedule` — TZ + jours + plage horaire + suppress offhours
- ✅ Rate cap anti-storm : `storm_max_alerts` × `storm_window_seconds` → digest forcé
- ✅ **Suppression sur partition réseau (V2-02-02)** — flag `AlertRule.suppress_on_network_partition` (opt-in). Si `true` et que l'incident a un `network_verdict ∈ {network_partition_asn, network_partition_geo}`, dispatch court-circuité dans `maybe_digest_or_dispatch`. Plus de page on-call sur des pannes opérateur. Évènement loggé `alert_suppressed_network_partition`.
- 🔬 **Pont détection→notification (v1.14)** — une détection (DNS drift, schema drift) n'envoie rien seule ; à son activation, un pont unique (`DetectionAlertBridge.vue` + `useDetectionAlertBridge`, paramétré par condition) propose de câbler un canal et crée la règle. Lien inverse dans le formulaire d'alerte : choisir la condition `schema_drift` pour un monitor sans détection active = CTA qui l'active en place (plus de cul-de-sac). Indicateur d'état unifié sur les cartes DNS/schema : « notification câblée » / « aucune notification — détection seule ».

### UI Alert Matrix v2
- ✅ Cards empilables par condition + chips canaux colorés (`alert-matrix/*.vue`)
- ✅ Section "Advanced" repliable
- ✅ Picker multi-conditions
- ✅ Help inline "How it works" plain-language par condition

### Templates & Preview
- ✅ `AlertMatrixTemplate` — 3 presets seedés par check_type (`standard`, `strict/paging`, `low_noise`)
- ✅ Superadmin CRUD UI
- ✅ **Impact preview** `POST /alerts/monitors/{id}/matrix/preview` — replay 30 j + would-fire count par condition, badge `≈ N / 30j`, debounce, tail estimate erfc pour anomaly

### Silences
- ✅ `AlertSilence` — name, reason, owner_id, monitor_id (null = catch-all owner-wide), starts_at, ends_at
- ✅ Guard `_is_silenced()` court-circuite avant tout IO
- ✅ Vue `SilencesView` + presets durée 15m/1h/4h/1d, badges Actif/Planifié/Passé
- 🚧 Pas de récurrence cron ni scope par tag/team (follow-up)

### Sécurité Alerting
- ✅ Tous les secrets chiffrés Fernet (`encrypt_channel_config`)
- ✅ SSRF guard sur webhooks + redirects re-validés
- ✅ Test `POST /alerts/channels/{id}/test`
- ✅ `AlertEvent` audit trail (sent/failed)

---

## 6. Status pages publiques

- ✅ URL `/status/{slug}` sans auth (`api/v1/public.py`)
- ✅ Customisation par `MonitorGroup` : logo, title, description, accent color, custom CSS, announcement banner
- ✅ Historique incidents 30 j
- ✅ Uptime bars 90 j par composant (`UptimeHistoryBars.vue`)
- ✅ Subscriptions visiteurs (token unsubscribe sécurisé) — `StatusSubscription` model
- ✅ WS public `/ws/public/{slug}` (sans auth, isolé du WS dashboard)

---

## 7. Dashboard & UX

### Temps réel
- ✅ WebSocket dashboard avec auth par message (jamais query param)
- ✅ Per-IP connection limit pré-auth + ping interval 30 s + auto-reconnect backoff exponentiel

### Design system « VELOURS » (v1.13)
- 🔬 **Deux thèmes tokenisés de bout en bout** : sombre « encre » (bruns chauds, texte ivoire) + clair « ivoire », via CSS custom properties (`style.css`) — toggle `data-theme` topbar persisté. Plus aucune couleur Tailwind/hex en dur dans les vues/composants (~2 300 occurrences converties, garde par le gate axe)
- ✅ Typo display **Fraunces** (variable roman+italique, latin+latin-ext) **auto-hébergée** `public/fonts/` (licence OFL, zéro CDN) — hero, h1, gros chiffres (`.font-display`) ; corps Plus Jakarta Sans, données JetBrains Mono tabulaire
- ✅ Accents sémantiques : or (`--accent`), sauge (`--up`), terracotta (`--down`), orange brûlé (`--error`) — **tous AA ≥ 4.5:1 dans les deux thèmes, ratios calculés par script et documentés dans style.css**
- ✅ **Dashboard éditorial** : hero verdict Fraunces (« Tout est *opérationnel.* » / « N services *en difficulté.* »), ruban de stats display cliquables avec compteurs animés (sautés sous `prefers-reduced-motion`), grille services à sparklines SVG, incidents/sondes offline en rangées flottantes, entrée en cascade
- ✅ Couleurs **runtime JS thémées** (`lib/themeColors.js` : `cssVar`/`withAlpha`) : ApexCharts, marqueurs/popups Leaflet, graphe de dépendances SVG suivent le thème actif ; palette probes 8 teintes chaudes ; filtre de tuiles limité au fond de carte
- ✅ Favicon SVG (barres d'uptime sauge/or sur encre) + fallback .ico ; matière : cartes 18 px, ombres douces double-couche, hover lift
- ✅ **Consolidation composants (v1.14)** : échelle de tailles boutons unique (`.btn-sm` / md / `.btn-lg` + `.btn-icon`) au lieu des surcharges inline ad-hoc ; couleurs boutons **et** badges entièrement tokenisées (plus aucun hex en dur, dérivées des tokens dans les 2 thèmes) ; composant `<StatusBadge>` canonique à libellés i18n remplaçant les badges de statut dupliqués (corrige des libellés figés en anglais) ; suppression des classes-boutons mortes/concurrentes (`.ack-btn`, `.filter-btn`) et du code mort

### Responsive / mobile (v1.14)
- ✅ Shell `AppLayout` : drawer off-canvas + hamburger + overlay + scroll-lock (`< 1024px`)
- ✅ Vues de contenu adaptées mobile-first : tables denses en scroll horizontal (`overflow-x-auto` + `min-w`), liste monitors en cartes empilées `< md`, grilles de formulaires/stats qui se replient, barres d'actions/filtres en `flex-wrap`, rangées d'incidents reflowées `< 640px` ; cible double navigateur + app native Android (Capacitor)

### Accessibilité (v1.13 — gates CI permanents)
- 🔬 **Gate axe-core en CI** (`tests/a11y.test.js`) : échec sur toute violation critical/serious dans les 7 vues principales
- 🔬 **Garde-fou modales** (`tests/a11yModals.test.js`) : tout overlay `fixed inset-0` hors allowlist = suite rouge ; **25 dialogues via `BaseModal`** (focus trap, `role=dialog`/`aria-modal`, Escape, restitution du focus)
- ✅ `document.title` par route + focus reset sur `#main-content` à chaque navigation SPA ; skip-link i18n ; `<html lang>` synchronisé
- ✅ Boutons icône labelisés (58), formulaires `aria-invalid`/`aria-describedby`, hiérarchie h1/h2, live regions (toasts erreur `role=alert`, WS/bulk `aria-live=polite`), contrastes AA sur les deux thèmes

### Visualisations
- ✅ Sparklines (LATERAL JOIN, ~2000× plus rapide qu'un window function — `services/stats.py`)
- 🔬 **`GET /monitors/` en LATERAL** (v1.15) — dernière ligne CheckResult par monitor via LATERAL (suppression du double full-scan) : **7 869 ms → 0,6 ms** mesuré en prod
- ✅ Heatmaps (`UptimeHeatmap.vue`)
- ✅ Uptime bars 90 j (`UptimeHistoryBars.vue`)
- ✅ Charts ApexCharts lazy-loaded (~400 KB hors bundle initial) : response time, availability, SLO burn, custom metrics
- ✅ Carte sondes Leaflet (`ProbeMap.vue`)
- ✅ **Carte ASN-aware (V2-02-06)** — `ProbeMap.vue` colore l'anneau extérieur des markers selon l'ASN (palette FNV-1a déterministe `lib/asnPalette.js`), l'intérieur selon l'uptime. Filtre par chip ASN au-dessus de la carte. Pop-up enrichi avec `AS<num> <name>` + warning NAT/VPN si divergence (V2-02-07). Légende auto-générée à partir des sondes affichées.
- ✅ **Incident playback (V2-02-06)** — endpoint `GET /incidents/{id}/timeline` (rate-limit 30/min) renvoie les CheckResults par sonde sur la fenêtre [start-5m, end+5m] (cap 2000 points) avec lat/lng/ASN. Composant `IncidentPlaybackMap.vue` + composable `useIncidentPlayback.js` (scrubber play/pause/reset, animation propagation panne). Bouton 📍 dans `IncidentsView` pour ouvrir inline.

### Productivité
- ✅ Command palette v2 — fuzzy search maison, blocs Recent / Open incidents / Actions, inline pause/ack au survol (`CommandPalette.vue`, `lib/fuzzy.js`)
- ✅ Hotkeys globaux : `g d/m/i/a/p/s` nav, `c` create, `/` palette, `?` cheatsheet (`useHotkeys.js`)
- ✅ Modale cheatsheet (`HotkeysModal.vue`)
- ✅ Skeleton loaders (`SkeletonBox/Text/Row.vue`) avec ARIA + `prefers-reduced-motion`
- 🔬 Empty states standardisés avec CTA + lien doc + bouton "rejouer le tour" (`EmptyState.vue` + `useTour.js`) — **déployé sur 6 vues** (v1.15) avec distinction vide réel / vide filtré (CTA « effacer les filtres »)
- ✅ Bulk actions monitors (move group, add tag, enable/pause/export/delete) + incidents (acknowledge all) (`BulkActionBar.vue`)
- 🔬 **Undo bulk delete** (v1.15) — suppression différée 6 s derrière un toast « Annuler » (registre `pendingDeleteIds`) : plus de suppression de masse irréversible au mauvais clic
- ✅ Filtres persistants (querystring + localStorage) — `useFilterPreset.js`
- 🔬 **Tri persistant liste monitors** (v1.15) — preset de tri persisté localStorage + URL, restauré à chaque visite
- 🔬 **Toast global d'erreurs API** (v1.15) — intercepteur axios : toute requête en échec affiche un toast (dédup anti-spam) au lieu d'échouer en silence ; opt-out par appel via `skipErrorToast`
- ✅ **Badge + filtre verdict réseau (V2-02-02)** — sur `IncidentsView.vue`, badge contextuel coloré (Service/ASN/Géo) avec tooltip explicatif à côté du status badge ; chip de filtre par verdict (Tous / Service down / Partition ASN / Partition géo) appliqué client-side ; clés i18n EN+FR.
- ✅ Wizard 3 étapes création monitor (`CreateMonitorWizard.vue`)

### Personnalisation
- ✅ Timezone utilisateur IANA (45 zones + auto, `useTimezone.js` + `<FormattedDate>`)
- ✅ Onboarding wizard 4 steps replayable via `?tour=1`
- ✅ Toast / Confirm composables (`useToast.js`, `useConfirm.js`)

### Runbooks & Annotations
- ✅ Runbook markdown par monitor (toggle + onglet + bloc inline incident, renderer safe)
- ✅ Annotations timeline par monitor (déploiements, changements)

---

## 8. Maintenance windows

- ✅ CRUD `/api/v1/maintenance/`
- ✅ Scope per-monitor OU per-group, team-scoped
- ✅ Modal create/edit + vue calendrier (`MaintenanceView.vue`, `MaintenanceWindowCard.vue`)
- ✅ Quick-schedule depuis `MonitorDetailView`
- ✅ Alertes supprimées pendant la fenêtre (`services/maintenance.py: is_in_maintenance`, `is_group_maintenance_suppressed`)
- ✅ Uptime distinct (downtime planifié ≠ panne)

---

## 9. Audit & Compliance

- ✅ `AuditLog` immuable : timestamp, user_id, email, action, object_type/id/name, diff JSON, ip
- ✅ Logging sur toute opération admin (CRUD monitor/probe/alert/team)
- 🔬 **Couverture complète des mutations de config** (v1.15, audit 2026-07) — audit log sur channels/rules (×5), groups (×3), probe PATCH/delete (désormais attribués), maintenance (×3), templates (×3), alert matrix + auto-rules : plus aucune mutation de configuration sans trace
- ✅ Index sur (timestamp, user_id, object_type+id)
- ✅ `/api/v1/audit/` list endpoint
- ✅ SLO target / window par monitor (`GET /monitors/{id}/slo`) + burn rate
- ✅ SLA reports custom range (uptime %, P95 RT, incidents, JSON download)
- ✅ Data retention globale + override par monitor (purge nightly `services/retention.py`)

---

## 10. Infrastructure & Déploiement

### Stack
- ✅ `docker-compose.yml` (postgres:16-alpine, redis:7-alpine, server, probe-local, frontend, nginx) avec healthchecks et limites ressources
- ✅ `docker-compose.probe.yml` — probe standalone
- ✅ Multi-stage Dockerfile server + probe, non-root, surface attaque minimale
- ✅ **Python 3.12** côté server/probe ; Node 22 LTS côté frontend
- ✅ Nginx reverse proxy avec security headers + CSP stricte
- ✅ Server bind sur `127.0.0.1:8000` (TLS au reverse proxy)

### Données
- ✅ Migrations Alembic versionnées et reversibles
- ✅ Index BRIN sur `check_results.checked_at` (P95 24h : 288 → 75 ms)
- ✅ Sparkline LATERAL JOIN (8s → <200 ms dashboard)
- ✅ Cache uptime (invalidation SCAN pattern)

### Observabilité
- ✅ Prometheus exporter `/metrics` (`prometheus-fastapi-instrumentator`)
- 🔬 **Logs JSON structurés en production** (v1.15) — `structlog` + bridge stdlib (uvicorn/sqlalchemy/apscheduler inclus, `uvicorn.run(log_config=None)`) : une seule ligne JSON par évènement, parsable par tout agrégateur ; format console lisible en dev
- 🔬 **Middleware X-Request-ID** (v1.15) — réutilise l'en-tête entrant s'il est bien formé (validation `^[A-Za-z0-9._-]{1,128}$`), sinon UUID généré ; injecté dans tous les logs de la requête et écho dans la réponse **y compris sur les 500** ; exposé via CORS `expose_headers`

### Haute disponibilité
- 🔬 **Leader election Redis** (v1.15, `core/leader.py`) — lock `SET NX PX` + fencing token, renew 10 s / TTL 30 s : les **7 boucles de fond singleton** (retention, heartbeat, renotify, network verdict, ASN refresh, digest recovery…) ne tournent que sur le réplica leader → multi-réplicas serveur sans double-exécution ; **fail-open si Redis down** (mono-réplica inchangé)

### Outils
- ✅ Script interactif `deploy.sh` (FR) — 3 modes (full / serveur seul / sonde distante), génération secrets, self-signed, prompts SMTP
- ✅ `recette.sh` — smoke tests
- ✅ `mobile/build.sh init|sync|apk` (Docker, JDK 21, ne pollue pas l'hôte)

### Frontend / Mobile
- ✅ Helper unique `lib/serverConfig.js` (`apiBaseUrl`, `wsBaseUrl`, `isNative`, `isConfigured`)
- ✅ `Capacitor.getPlatform()` pour détection native (pas d'UA sniffing)

---

## 11. Sécurité

### Crypto au repos
- ✅ **Fernet** AES-128-CBC + HMAC-SHA256 sur secrets canaux (bot_token, webhook_secret, webhook_url, integration_key, api_key Opsgenie, OIDC client_secret, scenario `secret: true` variables)
- ✅ Bcrypt 12-rounds (passwords + probe API keys)
- ✅ SHA-256 sur refresh tokens (jamais en clair)

### Crypto en transit
- ✅ TLS 1.2+ (Nginx)
- ✅ HSTS (`max-age=31536000; includeSubDomains; preload` en HTTPS)
- ✅ CSP stricte : `default-src 'self'; script-src 'self'` (pas d'`unsafe-inline`)

### Authentification
- ✅ JWT HS256, claims `sub`/`exp`/`iss`/`type` validés
- ✅ Access 15 min, refresh 7 j révocable Redis
- ✅ Token rotation à chaque refresh
- ✅ 2FA TOTP opt-in : secret Fernet, recovery codes bcrypt à usage unique, anti-rejeu Redis, `mfa_token` dédié (`type=mfa`) inutilisable comme access token
- ✅ Sessions actives listables et révocables par l'utilisateur (par session ou globalement)
- ✅ WebSocket auth message uniquement (jamais URL)
- ✅ Per-IP connection limit avant auth WS
- ✅ Public slug WS validé pré-accept
- 🔬 **Fan-out WebSocket scopé par tenant** (v1.15, audit M1) — le WS dashboard ne pousse que les évènements des monitors accessibles à l'utilisateur (`build_access_filter`), le WS public que ceux du groupe du slug ; scope rafraîchi périodiquement, **close 4001 si l'utilisateur est révoqué** en cours de session
- 🔬 **`correlated_monitor_ids` filtré par destinataire** (v1.16, audit SA5) — le scoping WS ne gatait que sur le `monitor_id` primaire de l'évènement `common_cause_detected` ; sa liste `correlated_monitor_ids` (corrélation globale sur sondes partagées) pouvait référencer des monitors d'autres tenants. `ConnectionManager.broadcast` réécrit désormais le payload par destinataire (intersection avec le scope de la connexion, dashboard **et** WS public), superadmin conservant la liste complète ; variantes sérialisées mémoïsées par forme filtrée distincte pour rester sur le hot path
- 🔬 **Lockout compte + anti-énumération** (v1.16, audit SA2) — détail §1

### Autorisation
- ✅ Ownership enforcement par JOIN sur tous endpoints mutants
- ✅ Superadmin bypass explicite
- ✅ `AlertRule` delete + `list_events` + `delete_channel` filtrent par owner
- 🔬 **`create_channel` vérifie le `team_id`** (v1.15, audit) — `assert_can_assign_team` : impossible de rattacher un canal d'alerte à une équipe dont on n'est pas membre
- 🔬 **Confiance probe scope-bindée** (v1.15, audit H1/H2) — résultats hors scope rejetés + rotation de clé superadmin avec éviction cache immédiate (détail §3)
- ✅ Privilege escalation auto bloquée (`UserSelfUpdate` Pydantic n'expose pas `is_superadmin` / `can_create_monitors`)

### Validation entrée
- ✅ Pydantic v2 partout, `extra="forbid"` sur les schemas In/Update
- ✅ Range / format / IANA TZ validés
- ✅ ORM SQLAlchemy uniquement (zéro string interpolation SQL)

### Anti-SSRF
- ✅ `_validate_webhook_url()` rejette RFC 1918 / loopback / link-local
- ✅ Appliqué à : webhooks, OIDC discovery, scenario navigation, checkers HTTP/TCP/UDP/SMTP/DNS/**ping**
- ✅ Redirects re-validés à chaque hop
- 🔬 **IP résolue épinglée — anti DNS rebinding** (v1.16, audit SA1) — la validation DNS avait lieu au moment du check mais httpx re-résolvait l'hostname à la requête réelle, laissant une fenêtre de rebinding (DNS qui bascule vers une IP privée entre validation et connexion). `_PinnedHostTransport` (transport httpx custom) résout une seule fois, rejette privé/loopback/link-local/multicast, réécrit l'URL vers l'IP validée tout en conservant le hostname d'origine en `Host` header et SNI (extension `sni_hostname`) — la vérification du certificat cible toujours le vrai hostname. Câblé sur `ssrf_safe_client()` : slack/discord/mattermost/teams/signal/webhook + digest (`services/alert.py`)
- 🔬 **SSRF sur le checker `ping`** (v1.16, audit S1) — `validate_host_ssrf()` câblé dans `PingChecker.check()` (même pattern que TCP/UDP/SMTP/DNS) ; seule la regex anti-injection protégeait auparavant le host passé au sous-processus `ping`, laissant sonder des adresses internes/metadata cloud (`probe/whatisup_probe/checkers/ping.py`)
- 🔬 **IP pinning côté probe — checker HTTP** (v1.16.2, SEC-2) — portage du pattern SA1 serveur : `_SSRFPinnedTransport` sur le client httpx partagé de la probe — chaque requête **et chaque hop de redirect** résout l'hôte une fois, rejette interne/metadata, épingle l'IP validée dans l'URL (Host header + SNI conservés sur le vrai hostname, URL restaurée après coup pour `final_url` et les redirects relatifs) ; ferme la fenêtre de rebinding validation→connexion et les hops intermédiaires non re-validés ; `SSRFBlockedError` → `CheckResult` en erreur « SSRF blocked » (`probe/whatisup_probe/checkers/_shared.py`)
- ✅ **SEC-B3** (v1.10.2) : `_extract_host()` (probe diagnostics) rejette tout host commençant par `-` — passé en argv positionnel à `traceroute`/`dig`/`ping`, il serait sinon interprété comme un flag (pas de shell, mais flag-injection). `run_collection` log + skip (`probe/whatisup_probe/diagnostics.py`)

### Anti-XSS / Clickjacking
- ✅ Vue 3 auto-escape (zéro rendu HTML serveur)
- ✅ `v-html` interdit (sauf rendus markdown via renderer maison safe)
- ✅ `X-Frame-Options: DENY` + `frame-ancestors 'none'`
- ✅ `X-Content-Type-Options: nosniff`
- ✅ `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`

### Rate limiting (slowapi)
- ✅ **Backend distribué Redis** (SC-07, v1.8) : cohérence des compteurs cross-instances FastAPI, fallback mémoire si Redis indisponible

| Endpoint | Limite |
|---|---|
| `/auth/login` | 10/min |
| `/auth/register` | — (endpoint désactivé, 403 invite-only) |
| `/auth/refresh` | 30/min |
| `/auth/me` PATCH | 30/min |
| `/auth/oidc/login` + `/auth/oidc/callback` | 20/min |
| `/auth/totp/*` (setup/enable/verify/disable) | 10/min |
| `/auth/sessions/list` + DELETE | 30/min |
| `/auth/sessions/revoke-all` | 10/min |
| `/probes/heartbeat` | 120/min |
| `/probes/results` | 600/min |
| `/probes/{id}/rotate-key` | 10/min |
| `/monitors` POST | 10/min |
| `/config` GET + PUT | 10/min (export lourd / import déclaratif) |
| `/silences` | GET 60 / POST 20 / PATCH 30 / DELETE 30/min |
| `/incidents/bulk-ack` | 20/min |
| `/incidents/{id}/snooze` | 30/min |
| `/alerts/rules` POST | 30/min |
| `/teams` | GET 60 / POST 20/min |
| `/teams/{id}` | GET 60 / PATCH 30 / DELETE 30/min |
| `/teams/{id}/members` | GET 60 / POST 20/min |
| `/teams/{id}/members/{user_id}` | PATCH 30 / DELETE 30/min |
| `/onboarding/status` + `/onboarding/complete` | 60/min (GET) / 30/min (POST) |
| `/audit` GET | 30/min (superadmin only) |
| `/groups` POST | 20/min |
| `/api-keys/{id}` DELETE | 30/min |
| `/auth/logout` | 30/min |
| `/monitors/{id}/dependencies/{dep_id}` + `/composite-members/{member_id}` DELETE | 30/min |
| `/public/pages/{slug}/unsubscribe` | 10/min |
| GET standard `/api/v1` (listes + détail — sweep SEC-3 2026-07-21) | 60/min |
| `/monitors` + `/monitors/{id}` + `/monitors/{id}/results` GET | 120/min (chemins chauds dashboard) |
| `/monitors/{id}/incidents/{inc}/postmortem` GET | 30/min |
| `/auth/oidc/config` + `/push/vapid-public-key` GET | 30/min (publics statiques) |
| `/api/health` + `/api/metrics` | — (health checks + scrape Prometheus, hors routers v1) |

- ✅ **Gate CI toutes méthodes** (`test_rate_limit_coverage.py`) : depuis SEC-3, un endpoint `api/v1` ajouté sans `@limiter.limit` fait échouer la CI, GET compris (exemptions documentées SECURITY.md §12)

### CORS
- ✅ Origines explicites (jamais `*` avec `credentials: true`)
- ✅ HTTP origins rejetées au démarrage en production
- ✅ Refus de démarrage si `SECRET_KEY` par défaut en production (`validate_production_settings`)

### Secrets management
- ✅ Aucun secret en dur dans le code
- ✅ `FERNET_KEY` requis en prod (refus démarrage sinon)
- 🔬 **Rotation `FERNET_KEY` sans coupure** (v1.16, audit SA3) — `FERNET_KEY_PREVIOUS` (liste CSV) accepté au déchiffrement via `MultiFernet` (le chiffrement reste sur la clé primaire) ; outil `python -m whatisup.tools.rotate_fernet [--dry-run]` re-chiffre `alert_channels.config`, `monitors.scenario_variables` (vars secret), `users.totp_secret`, `system_settings.oidc_client_secret` avec la clé primaire — idempotent, ne loggue jamais les valeurs, exit 1 si des valeurs restent illisibles ; procédure zéro-downtime documentée `SECURITY.md §7` (déployer 2 clés → rotate → retirer l'ancienne)
- ✅ Probe rejette `PROBE_API_KEY` vide
- ✅ Redis healthcheck sans password en argv
- ✅ Secrets channels masqués (`***`) dans réponses API
- ✅ OIDC client_secret jamais retourné

### Docker hardening (recommandé prod)
- ✅ Non-root user (`USER 1000:1000`)
- ✅ Server `bind: 127.0.0.1` (jamais `0.0.0.0`)
- ✅ Postgres / Redis non exposés (réseau interne seulement)
- 🚧 `read_only: true` + `no-new-privileges:true` à activer en prod

---

## 12. CI/CD & Tests

### Workflows GitHub Actions
| Fichier | Trigger | Rôle |
|---|---|---|
| `ci.yml` | push/PR main | lint ruff + tests server (≥50%) + tests probe (≥35%) + Alembic up/down |
| `codeql.yml` | push/PR + lundi 06h | CodeQL `security-extended` Python + JS/TS |
| `security-audit.yml` | push/PR + lundi 08h | pip-audit (server+probe) + npm audit (frontend) |
| `plumber.yml` | push/PR main | Plumber — compliance des workflows GitHub Actions (SHA pinning, permissions, triggers, image tags, branch protection) → SARIF vers Code Scanning ; **gate bloquant** (100% / A) |
| `release.yml` | tag `v*` **+ `workflow_call`** | CI gate → build & push GHCR (server+probe) → GitHub Release auto-extraite du CHANGELOG |
| `mobile-release.yml` | push main + tag v* **+ `workflow_call`** | Build APK debug ; release signée sur tag (keystore secrets) |
| `release-please.yml` | push main | Auto-versioning + CHANGELOG + tag SemVer (conventional commits) ; sur `release_created`, **chaîne `release.yml` (Docker) + `mobile-release.yml` (APK signé)** via `workflow_call` → release publiée de bout en bout sans dispatch manuel (1er run réel : v1.14.2) |

### Tests
- ✅ **Backend** : ~745 tests pytest (auth, 2FA TOTP, sessions, monitors, probes, alerts, incidents, SLO, OIDC, maintenance, config, bulk, snooze, silences, ws, leader election, request-ID, audit coverage)
- ✅ **Frontend** : ~346 tests vitest (composants, composables, stores, fuzzy, skeleton, empty states, hotkeys, push, toast erreurs, tri persistant, undo bulk)
- ✅ **Probe** : ~145 tests (HTTP/TCP/DNS/SMTP/scenario + SSRF host validation + config + contrats heartbeat/perform_check)

### Supply chain
- ✅ Dependabot configuré (`.github/dependabot.yml`)
- ✅ pip-audit + npm audit hebdomadaires
- ✅ **pip-audit durci (v1.10.4, #168)** : `security-audit.yml` upgrade pip vers ≥26.1.2 avant l'audit pour patcher PYSEC-2026-196 (pip 26.1.1 de l'image runner) — fix réel plutôt que `--ignore-vuln`
- ✅ **Garde-fou dérive de deps (v1.14.2, #202)** : pin `tzlocal != 5.4.2` (probe) — release amont publiée comme wheel cassé (`dist-info` sans module) qui cassait l'import apscheduler et toute la collecte des tests probe ; cap fastapi relevé à `< 0.140` en v1.15 (0.137-0.138 cassaient le routing via `_IncludedRouter`, corrigé en 0.139)
- ✅ **Plumber — compliance pipeline CI/CD** (`plumber.yml` + `.plumber.yaml`, OPA/Rego) : audit des workflows GitHub Actions (actions épinglées par SHA, permissions least-privilege déclarées, triggers non dangereux, pas de tags d'images mutables, protection de branche) → rapport noté + SARIF vers Code Scanning. **Score initial 100% / A** : toutes les actions déjà SHA-pinned, `main` protégée, et top-level `permissions: contents: read` ajouté à `release.yml`/`mobile-release.yml`/`security-audit.yml` pour atteindre 7/7 workflows avec permissions déclarées (jobs élevés en per-job). **Gate bloquant** (`soft-fail: false`, seuil 100%) : toute régression future (action non épinglée, workflow sans permissions, trigger dangereux) casse la CI. Binaire Plumber vérifié par attestation de provenance
- ✅ CodeQL `security-extended`

---

## 13. Mobile (Capacitor)

- ✅ App ID immuable `io.github.aurevlan.whatisup` (interdit de changer post-publication)
- ✅ Capacitor 8 + JDK 21 (Dockerfile + workflow)
- ✅ Build via Docker (`mobile/build.sh init|sync|apk`) — ne pollue pas l'hôte
- ✅ `ServerSetupView` au 1er lancement natif (URL backend, validation `/api/health`, persist localStorage)
- ✅ Live reload device (`vite --host` + `capacitor.config.json: server.url`)
- ✅ Biometric unlock — Face ID / Touch ID / BiometricPrompt (`@capgo/capacitor-native-biometric`)
- ✅ Refresh token en secure storage (Keychain iOS / Keystore Android via `capacitor-secure-storage-plugin`)
- ✅ FCM push avec actions inline (ack / snooze 1 h / snooze 4 h)
- 🔬 **Bouton retour Android** (v1.15) — navigue dans l'historique de l'app au lieu de la quitter (quitte seulement depuis la racine)
- 🔬 **WebSocket suspendu en arrière-plan** (v1.15) — `appStateChange` Capacitor : déconnexion propre en background, reconnexion au retour au premier plan (batterie/données)
- 🔬 **Permission `POST_NOTIFICATIONS`** (v1.15) — demande runtime Android 13+ : les push FCM fonctionnent sur les Android récents
- ✅ APK release signée via secrets keystore + version sync depuis `package.json` + `versionCode = github.run_number` (Play Store-compatible)
- ✅ Graceful fallback si `GOOGLE_SERVICES_JSON_BASE64` absent

---

## 14. Extensions & Intégrations

- ✅ **Browser extension** Chromium — recorder de scénarios (navigate/click/fill/screenshot), placeholders `{{password_N}}` chiffrés Fernet ; download `/api/v1/extension/download` (ZIP avec URL serveur pré-configurée)
- ✅ **Web Push** VAPID — `/api/v1/push/{subscribe,unsubscribe,test}` ; opt-in serveur (`VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`)
- ✅ **Monitor templates** (`MonitorTemplate`) — JSON config réutilisable, `/api/v1/templates/`
- ✅ **Config import/export (IaC)** — `GET/PUT /api/v1/config/` JSON, dry-run + prune, match par nom (idempotent), secrets redacted
- ✅ Endpoint Prometheus `/metrics` (intégration Grafana)

---

## 15. Internationalisation

- ✅ vue-i18n@9 Composition API (`legacy: false`)
- ✅ **Anglais** (défaut) + **Français** complets (`i18n/{en,fr}.js`)
- ✅ ~200+ clés hiérarchiques (`nav.*`, `auth.*`, `error.*`, `monitors.*`, `alerts.*`, `silences.*`, `wizard.*`, `empty.*`, `hotkeys.*`, …)
- ✅ Switch langue persistée `localStorage('whatisup_lang')`
- ✅ Accents FR vérifiés (audit dédié — voir CHANGELOG 1.2.0)

---

## 16. Health Engine V2 (Global)

> Refonte du modèle de détection : **probe = capteur**, **serveur = juge unique**. Déployé en prod sur 17/17 monitors depuis 2026-05-06. Voir `plan_v2_global_health.md` pour la genèse.

### Foundation (M0–M1)
- ✅ **M0** — Modèle `MonitorHealthState` + table `monitor_health_states` (état agrégé par monitor, JSONB `probe_health`, percentiles 5 min, sample_count)
- ✅ **M1** — Aggregator serveur (`services/health.py`) : ingestion en continu des `CheckResult`, calcul p50/p95/p99 sur fenêtre glissante 5 min via `core/percentile.py`, état up/down par probe, ratio quorum
- ✅ Toggle per-monitor `Monitor.health_engine_enabled` (opt-in à la migration, opt-out via PATCH ou UI)
- ✅ Rollback global env `LEGACY_INCIDENT_ENGINE=true` (court-circuite le bridge SLO dans `services/incident.py`)

### SLO rules (M2–M3)
- ✅ **M2** — Évaluateur `quorum_down` : "≥ X% des probes voient down sur N min, min M probes" → ouvre `Incident.trigger_kind=quorum_down`
- ✅ **M3** — Évaluateur `quorum_slow` : "p95 fleet > seuil ms sur N min" → `trigger_kind=quorum_slow`
- ✅ Modèle `SLORule` (rule_type, quorum_ratio, p95_threshold_ms, window_seconds, min_probes, cooldown_seconds, enabled)
- ✅ Cooldown anti-flap par règle (60s par défaut)
- ✅ Badge `trigger_kind` coloré dans `IncidentsView`

### Toggle UI + CRUD (M4)
- ✅ Panel "Quorum & SLO" dans `MonitorDetailView` : toggle Health Engine + table SLO rules
- ✅ CRUD complet `/monitors/{id}/slo-rules` (POST/PATCH/DELETE) avec validation Pydantic
- ✅ Lecture state `/monitors/{id}/health` (probe_health JSONB, percentiles courants)

### Probe divergence + migration (M5)
- ✅ **M5** — `divergence_score` par probe (S2L1 dans `services/slo.py`) : probe systématiquement en désaccord avec le fleet → `divergence_score > 0.5` → exclue automatiquement du quorum (mais reste visible et ingère)
- ✅ Script `whatisup.scripts.migrate_to_health_engine` : migration en masse opt-in avec règle par défaut `quorum_down` 60% / 5 min / min 2 probes / cooldown 60s
- ✅ Coexistence legacy ↔ V2 testée (`test_health_engine_legacy_coexistence.py`, `test_legacy_engine_flag.py`)

### Tests dédiés
`test_health_ingest.py`, `test_health_state_model.py`, `test_slo_quorum_down.py`, `test_slo_quorum_slow.py`, `test_probe_divergence.py`, `test_health_engine_legacy_coexistence.py`, `test_legacy_engine_flag.py`, `test_incident_timeline.py`.

### Restant (M6+, planifié)
- 🚧 Burn-rate fast/slow (Google SRE multi-fenêtres) côté Health Engine
- 🚧 UI history des `monitor_health_states` (timeline percentiles)
- 🚧 Migration des règles legacy `response_time_above` → `quorum_slow`

---

## 17. Réseau & Intelligence (V2-02)

> Vague β : enrichir chaque incident avec une compréhension réseau (qui parle à qui via quel ASN, partition vs panne service, qualité TLS/DNS/BGP). Voir `plan_vague_gamma_tls_dns_bgp.md`.

### ASN enrichment (V2-02-01)
- ✅ Lookup ASN + AS-name via Team Cymru DNS (`services/probe_enrichment.py`)
- ✅ Champs `Probe.public_ip`, `asn`, `asn_name`, `ixp_membership`, `asn_updated_at`
- ✅ Refresh opportuniste sur heartbeat si stale (24h par défaut, `ASN_REFRESH_HOURS`) + tâche fond toutes les 6h
- ✅ Backend pluggable `ASN_LOOKUP_PROVIDER ∈ {cymru, disabled}`
- ✅ Best-effort : aucun blocage du heartbeat en cas d'échec lookup

### Network verdict (V2-02-02)
- ✅ Classification automatique `service_down` / `network_partition_asn` / `network_partition_geo` / `inconclusive` (`services/network_verdict.py`)
- ✅ Champ `Incident.network_verdict` calculé à l'ouverture, recompute toutes les 5 min tant que ouvert
- ✅ Flag `AlertRule.suppress_on_network_partition` opt-in : court-circuite le dispatch si verdict = `network_partition_*`
- ✅ Évènement `alert_suppressed_network_partition` loggé pour audit
- ✅ Badge contextuel coloré + chip de filtre dans `IncidentsView` (i18n EN+FR)

### TLS audit + grade A-F (V2-02-03 / V2-02-05)
- ✅ Audit TLS approfondi par check HTTP : version protocole, cipher suite, courbe ECDHE, chain validation
- ✅ Grade A-F calculé selon Mozilla Server Side TLS Guidelines
- ✅ SSL pinning SHA-256 (T2-05) : option `expected_certificate_sha256`, alerte sur drift
- ✅ Tests dédiés `test_tls_audit.py`, `test_ssl_advanced.py`, `test_monitors_ssl_advanced.py`

### DNS consistency (V2-02-04)
- ✅ Comparaison cross-NS : détecte les NS du domaine qui retournent des records divergents
- ✅ Fold dans le check DNS standard (`probe/checkers/dns.py`)
- ✅ Tests `test_dns_consistency.py`

### BGP looking-glass (V2-02-04)
- ✅ Endpoint `/api/v1/bgp/lookup` (rate-limit) : interroge un looking-glass externe pour résoudre un préfixe → ASN d'origine
- ✅ Fold dans le pipeline diagnostic à l'ouverture d'un incident
- ✅ Tests `test_bgp_lookup.py`

### Outbound IP intelligence (V2-02-07)
- ✅ La sonde résout sa propre IP de sortie via `api.ipify.org` (+ fallbacks `ifconfig.me`, `icanhazip.com`)
- ✅ Champs `Probe.self_reported_ip` + `self_reported_asn` poussés au heartbeat
- ✅ Si différent de `public_ip` (vu par serveur via `request.client.host`) → badge `NAT/VPN` UI + tooltip

### TLS fleet dashboard (V2-02-08)
- ✅ Vue dédiée `TlsFleetView` listant tous les monitors HTTPS avec leur grade, expiration, cipher
- ✅ Endpoint `/api/v1/tls-fleet/` (rate-limit) avec filtres
- ✅ Module API client `frontend/src/api/tlsFleet.js`

### Carte ASN-aware + Incident playback (V2-02-06)
- ✅ `ProbeMap.vue` : anneau extérieur des markers coloré selon ASN (palette FNV-1a `lib/asnPalette.js`), intérieur selon uptime
- ✅ Filtre par chip ASN + légende auto-générée
- ✅ Pop-up enrichi `AS<num> <name>` + warning NAT/VPN
- ✅ Endpoint `GET /incidents/{id}/timeline` (rate-limit 30/min, cap 2000 points)
- ✅ Composant `IncidentPlaybackMap.vue` + composable `useIncidentPlayback.js` (scrubber play/pause/reset)

---

## 18. Récap statistiques

| Pilier | Items livrés | Fichiers clés |
|---|---|---|
| Auth | 11 axes (+2FA TOTP +sessions actives +lockout/anti-énumération v1.16) | `auth.py`, `totp.py`, `sessions.py`, `user.py`, `security.py`, `teams.py`, `tag.py`, `api_key.py`, `lockout.py` |
| Check types | 11 types | `probe/whatisup_probe/checkers/*.py` |
| Probes | 12 axes (+ASN +outbound IP +auth préfixe/rotation clé +scope-binding v1.15 +cache fingerprinté v1.16) | `probe.py`, `probes.py`, `probe_group.py`, `probe_enrichment.py`, `ProbeMap.vue` |
| Incidents | 11 axes (+playback +diagnostic engine +incident-groups tenant-scopé v1.16) | `incident.py`, `correlation.py`, `anomaly.py`, `diagnostics.py`, `incident_diagnostic.py` |
| Alerting | 14 axes (+silences +network suppress +matrix preview +pont détection→alerte) | `alert.py`, `alerts.py`, `silences.py`, `useDetectionAlertBridge.js`, `services/channels/*.py` (11 canaux) |
| Status pages | 4 axes | `public.py`, `PublicPageView.vue` |
| Dashboard UX | 18 axes (+design system VELOURS +a11y gates +consolidation composants +responsive mobile +quick wins v1.15 : toast erreurs, tri persistant, undo bulk, EmptyState ×6) | `ws.py`, `stats.py`, `style.css`, `lib/themeColors.js`, `StatusBadge.vue`, components shared/* + monitors/* |
| Maintenance | 4 axes | `maintenance.py` × 2 |
| Audit/Compliance | 6 axes (+couverture complète mutations config v1.15) | `audit_log.py`, `retention.py`, `reports.py` |
| Infra | 10 axes (+leader election +logs JSON/X-Request-ID v1.15) | `docker-compose.yml`, Dockerfiles, deploy.sh, `core/leader.py` |
| Sécurité | 17 axes (+SC-07 distributed RL +WS tenant scoping v1.15 +SSRF anti-rebinding +lockout +rotation FERNET_KEY +WS correlated_ids scopé +incident-groups scopé +cache probe/API-key fingerprinté +ping SSRF +19 rate-limits v1.16 +SSRF probe pinning +fail-open Redis auth v1.16.2) | `security.py`, `middleware.py`, `_helpers.py`, `core/limiter.py`, `lockout.py`, `tools/rotate_fernet.py`, `checkers/_shared.py` |
| CI/CD | 6 workflows + release-please | `.github/workflows/*.yml` |
| Mobile | 7 axes (+quick wins Android v1.15 : back button, WS background, POST_NOTIFICATIONS) | Capacitor 8, FCM, biometrics, mobile-release.yml |
| Extensions | 5 axes | extension/, config IaC, web_push, templates, prometheus |
| i18n | 2 langues | i18n/{en,fr}.js (~1330 / 1298 clés) |
| **Health Engine V2** | M0-M5 livrés (M6+ à venir) | `services/health.py`, `services/slo.py`, `monitor_health.py`, `core/percentile.py` |
| **Réseau & Intelligence (V2-02)** | 8 axes (ASN, partition, TLS, BGP, DNS consistency, playback, NAT/VPN, fleet dashboard) | `services/network_verdict.py`, `services/probe_enrichment.py`, `api/v1/bgp.py`, `api/v1/tls_fleet.py` |

**Stack** : Python 3.12 (FastAPI / SQLAlchemy 2 async / Alembic), Vue 3.5 (Pinia / Tailwind 4 / vue-i18n@9), Postgres 16, Redis 7, Nginx, Capacitor 8 (JDK 21), Docker Compose multi-stage.

**Volumétrie** (mise à jour 2026-05-10) :
- ~28 modèles SQLAlchemy (+`monitor_health`, `silence`, `incident_diagnostic`, `alert_matrix_template`)
- ~26 services métier (+`health`, `slo`, `network_verdict`, `probe_enrichment`, `diagnostics`, `alert_matrix_preview`, `alert_matrix_templates`)
- ~24 vues frontend (+`SilencesView`, `TlsFleetView`)
- ~47 endpoints API v1 (+`silences`, `bgp`, `tls_fleet`, SLO rules, health state, diagnostics, `totp`, `sessions`)
- ~11 checkers probe + module `diagnostics.py` + `public_ip.py`
- 11 canaux d'alerte (8 historiques + Discord/Mattermost/Teams)

---

## Règle de mise à jour

> **À chaque PR qui ajoute, modifie ou supprime une feature visible** :
> 1. Mettre à jour la section concernée de `FEATURES.md` dans le même commit.
> 2. Compléter la section `## [Unreleased]` du `CHANGELOG.md`.
> 3. Si la PR ajoute un endpoint avec rate-limit → reporter dans la table §11.
> 4. Si la PR introduit un nouveau type de check ou canal → reporter dans §2 ou §5.
> 5. Si la PR touche le Health Engine ou les V2-02 → reporter dans §16 ou §17.

*Dernière revue exhaustive : 2026-05-10 (v1.8.0 + Health Engine V2). Dernier amendement : 2026-07-21 (v1.16.2 — vague fiabilité SEC-2 + R-1/R-2/R-4 : SSRF probe IP pinning, fail-open Redis auth, atomicité renotify, matching conditions d'alerte unifié + preview 7/7).*
