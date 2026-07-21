# Plan — Stabilisation post-audit (2026-06-11)

Branche : `chore/stabilisation-audit`. Source : audit complet 5 axes (backend, sécurité, frontend, probe/infra, tests).

## Chantiers

| # | Chantier | Statut |
|---|----------|--------|
| C1 | Probe quick-wins : try/except `_flush_loop`, throttle RAM visible via heartbeat `throttled_scenarios` | ✅ fa78850 |
| C2 | Sécurité : limiters annotations/maintenance POST/tags GET, tags PATCH/DELETE superadmin-only, metrics team access | ✅ 4f36dfc |
| C3 | Perf : bulk uptime/history `public.py` (+limiter), limite incidents publics 100 | ✅ 8fd48a3 |
| C4 | Tests : ws.py (9), checkers probe tcp/udp/ping/smtp/domain_expiry (39), CI migrations round-trip, cov 65→75 | ✅ 797aa23 |
| C5 | Probe résilience : spill disque reporter, HEALTHCHECK Dockerfile, limite body HTTP 10MB | ✅ fa78850 |
| C6 | Métriques Prometheus custom (tâches fond, dispatch alertes, caches auth) | ✅ 5c17927 |
| C7 | Frontend : i18n sweep (124 clés ×2), useDateFormat, console.log DEV-only | ✅ 9ecb50b |
| C8 | Frontend : découpe AdminView (1483→677), MonitorDetailView (1422→797, 9 composants detail/), MonitorsView (950→590, 4 composables) | ✅ 2092bf2 + fbcadb9 |

**TERMINÉ 2026-06-11** — 8 commits sur `chore/stabilisation-audit`, prêt pour PR.
Vérif finale : serveur 659 ✅, probe 143 ✅, vitest 249 ✅, lint/build/check:i18n ✅.
Bonus agent : fix TypeError latent `dnsValueStr` (table résolutions DNS).

## Findings écartés (faux positifs audit)
- UPGRADING.md existe.
- Stores Pinia : timers correctement nettoyés.
- Runbook renderer XSS-safe.
- trigger-now passe bien par le semaphore (`_run_check` l'acquiert en interne).
- `status.py /summary` déjà batché ; `list_rules` a déjà `selectinload(channels)` ; nginx a déjà `restart: unless-stopped`.

## Décisions notables
- RAM > 85 % : on garde le skip (un résultat `error` = down côté serveur → faux incidents) mais compteur `throttled_scenarios` dans le heartbeat.
- Tags : mutation superadmin-only (pool global partagé, `UserTagPermission` est du code mort jamais branché ; frontend n'utilise que GET/POST).
- Spill reporter : JSONL borné (5000 entrées / compaction 4 Mo), retry toutes ~30 s, 4xx jamais respillés.

## Notes
- Tout test backend/probe via Docker (pas de Python local). Vitest via node:22-alpine.
- Tests obligatoires pour chaque modif.
