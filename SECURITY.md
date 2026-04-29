# Politique de Sécurité — WhatIsUp

> Garde-fou exécutif du projet : **chaque contrôle listé ici doit être actif en production**.
> Conforme : OWASP Top 10 2021 · ANSSI RGS · NIST SP 800-63B · CWE Top 25.
> Dernière revue exhaustive : **2026-04-29** (v1.5.0). Référence canonique : `FEATURES.md` §11.

---

## Sommaire

1. [Versions supportées & SLA](#1-versions-supportées--sla)
2. [Signalement d'une vulnérabilité](#2-signalement-dune-vulnérabilité)
3. [Matrice OWASP Top 10 → mitigations](#3-matrice-owasp-top-10--mitigations)
4. [Contrôles automatisés (CI/CD)](#4-contrôles-automatisés-cicd)
5. [Contrôles manuels — checklist PR](#5-contrôles-manuels--checklist-pr)
6. [Patterns interdits / autorisés](#6-patterns-interdits--autorisés)
7. [Gestion des secrets](#7-gestion-des-secrets)
8. [Hardening déploiement](#8-hardening-déploiement)
9. [Incident response sécurité](#9-incident-response-sécurité)
10. [Supply chain](#10-supply-chain)
11. [Contrôles cryptographiques](#11-contrôles-cryptographiques)
12. [Rate limiting (table de référence)](#12-rate-limiting-table-de-référence)
13. [Pre-commit & hooks locaux](#13-pre-commit--hooks-locaux)
14. [Politique de mise à jour de ce document](#14-politique-de-mise-à-jour-de-ce-document)
15. [Références](#15-références)

---

## 1. Versions supportées & SLA

| Version | Support sécurité | Notes |
|---|---|---|
| `1.5.x` | ✅ Actif | Branche courante (toutes CVE patchées) |
| `1.4.x` | ⚠️ Critiques uniquement | EOL au prochain mineur |
| `1.3.x` et antérieur | ❌ Non supportée | Migration vers 1.5.x requise |
| `0.x` | ❌ Non supportée | Beta, pas de support |

### SLA de remédiation

| Sévérité (CVSS v3.1) | Acquittement | Patch en prod |
|---|---|---|
| Critique (9.0–10.0) | 24 h ouvrées | **7 jours** |
| Élevée (7.0–8.9) | 72 h ouvrées | **30 jours** |
| Moyenne (4.0–6.9) | 7 jours | **60 jours** |
| Faible (0.1–3.9) | 14 jours | au prochain release planifié |

---

## 2. Signalement d'une vulnérabilité

**🚫 NE PAS ouvrir d'issue publique GitHub pour une faille de sécurité.**

### Canaux

1. **GitHub Private Vulnerability Reporting** (préféré) — onglet `Security` → `Report a vulnerability`
2. **Email** — `aurelien+security@<domaine-projet>` (PGP key dans `.well-known/security.txt` à venir)
3. **`SECURITY.txt`** — `/.well-known/security.txt` (à publier, voir §14)

### Informations à fournir

- Description précise + impact estimé (CVSS v3.1 si possible)
- PoC reproductible (URL, payload, environnement)
- Version concernée (`docker images | grep whatisup`)
- Configuration partielle (sans secrets)
- Correctif suggéré (optionnel)

### Engagement

- Accusé de réception : **72 h ouvrées**
- Évaluation initiale : **7 jours**
- Mention publique du reporter dans le `CHANGELOG.md` après patch (sauf demande contraire)
- Pas de prime de bug bounty à ce jour, mais reconnaissance documentée

---

## 3. Matrice OWASP Top 10 → mitigations

| OWASP 2021 | Vecteur | Mitigation en place | Vérification |
|---|---|---|---|
| **A01 — Broken Access Control** | Cross-tenant leak | Ownership enforcement par JOIN, `require_superadmin`, RBAC teams + tags | Tests `test_*_ownership.py`, audit `delete_channel`/`list_events` |
| **A02 — Cryptographic Failures** | Secrets en clair | Fernet AES-128 sur tous secrets channels + OIDC + scenario, bcrypt 12-rounds, refresh tokens hashés SHA-256 | `core/security.py`, `_validate_production_settings()` |
| **A03 — Injection** | SQL / cmd / XSS | SQLAlchemy ORM exclusif, Pydantic v2 `extra="forbid"`, Vue 3 auto-escape, pas de `v-html` non-safe | CodeQL `security-extended`, code review |
| **A04 — Insecure Design** | Modèle d'accès | Threat model documenté (ce fichier), invite-only, escalade priv. silencieusement bloquée | Tests `test_me_update_*` |
| **A05 — Security Misconfiguration** | Defaults faibles | `validate_production_settings` refuse SECRET_KEY défaut, FERNET_KEY requis, CORS `*` interdit, server bind 127.0.0.1 | Démarrage prod ✓ |
| **A06 — Vulnerable Components** | CVE deps | Dependabot + pip-audit + npm audit hebdo + CodeQL | Workflows `security-audit.yml`, `codeql.yml` |
| **A07 — Auth Failures** | Brute-force, JWT | slowapi rate-limit, JWT 15min + refresh révocable, MFA biométrique mobile, OIDC PKCE | Table §12 |
| **A08 — Software & Data Integrity** | CI/CD compromise | GHCR images signées via OIDC (à activer), workflows pinned actions `@v6`, supply-chain audit | Workflows + §10 |
| **A09 — Logging & Monitoring** | Détection | `AuditLog` immuable, structlog JSON + request ID, Prometheus metrics | `audit_log.py`, `/metrics` |
| **A10 — SSRF** | Webhooks/scenario | `_validate_webhook_url()` rejette RFC 1918/loopback/link-local, redirects re-validés, applied to HTTP/TCP/UDP/SMTP/DNS | `services/channels/_helpers.py`, `probe/.../_shared.py` |

---

## 4. Contrôles automatisés (CI/CD)

### Workflows actifs

| Workflow | Trigger | Garde-fous |
|---|---|---|
| `ci.yml` | push/PR `main` | ruff lint + tests pytest serveur (`--cov-fail-under=50`) + tests probe (`--cov-fail-under=35`) + Alembic upgrade/downgrade |
| `codeql.yml` | push/PR + lundi 06h UTC | CodeQL `security-extended` Python + JS/TS |
| `security-audit.yml` | push/PR + lundi 08h UTC | `pip-audit` server + probe + `npm audit --audit-level=moderate` frontend |
| `release.yml` | tag `v[0-9]+.[0-9]+.[0-9]+*` | CI gate obligatoire avant build & push GHCR + GH Release |
| `mobile-release.yml` | push main + tag v* | APK debug + APK release signée (keystore secrets) |
| `release-please.yml` | push `main` | Auto-versioning SemVer + génération CHANGELOG + tag (déclenche `release.yml`) |

### Alertes bloquantes (= CI rouge)

- Vulnérabilité **High/Critical** détectée par `pip-audit` ou `npm audit`
- Finding **error-level** par CodeQL
- Couverture < seuil (50% server / 35% probe)
- `ruff check` non vert
- Migration Alembic non rétro-compatible (downgrade KO)

### Alertes non-bloquantes (à traiter sous SLA)

- Dependabot moderate
- CodeQL warning
- Findings `note` CodeQL

---

## 5. Contrôles manuels — checklist PR

À cocher dans la description de PR pour toute modification touchant l'API ou la DB :

- [ ] **Pydantic** : tout body/query/path/header validé avec `extra="forbid"` sur `*In`/`*Update`
- [ ] **Ownership** : `current_user.id` dans le `where` de toute requête mutante (ou `require_superadmin`)
- [ ] **Pas de secret** dans le code, les logs, les messages d'erreur API, les commits
- [ ] **`.is_(True)`** / `.is_(False)` (jamais `is True`) dans tous les filtres SQLAlchemy
- [ ] **Rate-limit** `@limiter.limit("X/minute")` + `request: Request` sur tout endpoint public ou sensible
- [ ] **Audit** : `log_action()` sur les opérations sensibles (CRUD config, escalation)
- [ ] **SSRF** : `_validate_webhook_url(url)` avant tout `httpx` sortant non-CDN
- [ ] **Fernet** : `encrypt_channel_config()` avant DB sur tout secret canal
- [ ] **WebSocket** : auth par message `{"type":"auth","token"}`, jamais en URL
- [ ] **CORS** : si nouvelle origin → ajout dans `CORS_ALLOWED_ORIGINS` (jamais `*` avec credentials)
- [ ] **Tests** : test de privilège (autre user reçoit 404 ou 403, jamais 200)
- [ ] **Tests** : test de validation (input invalide → 422)
- [ ] **Migration** : `downgrade()` testé localement
- [ ] **CHANGELOG** : section `[Unreleased]` mise à jour
- [ ] **FEATURES.md** : section concernée à jour si nouvelle feature visible

### Erreurs typiques à refuser en review

- 🔴 `select(Monitor).where(Monitor.enabled is True)` → toujours False, utiliser `.is_(True)`
- 🔴 Endpoint sans `@limiter.limit(...)`
- 🔴 Renvoyer 403 sur ressource d'un autre tenant (fuite d'existence) → renvoyer **404**
- 🔴 `db.refresh()` après mutation = écrase la modif, utiliser `await db.flush()`
- 🔴 Pydantic `*In` qui contient `is_superadmin` ou `owner_id` → permet escalade
- 🔴 Token dans URL WebSocket (`?token=...`) → apparaît dans logs reverse proxy
- 🔴 Nouveau channel sans `encrypt_channel_config()` à l'écriture
- 🔴 Webhook sortant sans SSRF guard

---

## 6. Patterns interdits / autorisés

### SQL — paramétrage

```python
# ❌ INTERDIT — injection
await db.execute(text(f"SELECT * FROM users WHERE email = '{email}'"))

# ✅ OK — ORM paramétré
await db.execute(select(User).where(User.email == email))
```

### Filtres booléens SQLAlchemy

```python
# ❌ INTERDIT — toujours False (compare l'objet Python)
select(Monitor).where(Monitor.enabled is True)

# ✅ OK
select(Monitor).where(Monitor.enabled.is_(True))
```

### WebSocket auth

```javascript
// ❌ INTERDIT — token visible dans logs reverse proxy
const ws = new WebSocket(`/ws/dashboard?token=${token}`)

// ✅ OK — auth par message
const ws = new WebSocket('/ws/dashboard')
ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }))
```

### Secrets en base

```python
# ❌ INTERDIT — secret en clair
channel.config = {"bot_token": "1234:abcdef"}

# ✅ OK — Fernet
channel.config = encrypt_channel_config({"bot_token": "1234:abcdef"})
```

### XSS frontend

```vue
<!-- ❌ INTERDIT — sauf si renderer markdown safe explicit -->
<div v-html="userMessage"></div>

<!-- ✅ OK -->
<div>{{ userMessage }}</div>

<!-- ⚠️ Cas runbook : passé par renderer maison qui escape HTML d'abord -->
<div v-html="renderRunbook(monitor.runbook_markdown)"></div>
```

### URLs sortantes

```python
# ❌ INTERDIT — laisse passer 127.0.0.1, 169.254.x, 10.x
await httpx.post(webhook_url, json=payload)

# ✅ OK
await _validate_webhook_url(webhook_url)  # raise si IP privée/loopback
await httpx.post(webhook_url, json=payload, follow_redirects=False)
```

### Privilege escalation par schema

```python
# ❌ INTERDIT — l'utilisateur peut s'auto-promote
class UserSelfUpdate(BaseModel):
    full_name: str | None = None
    is_superadmin: bool | None = None  # ← jamais !

# ✅ OK — surface limitée
class UserSelfUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = None
    timezone: str | None = None
```

### Refresh post-mutation

```python
# ❌ INTERDIT — écrase la modif (la refresh recharge l'ancienne valeur)
obj.field = new_value
await db.refresh(obj)
await db.commit()

# ✅ OK
obj.field = new_value
await db.flush()
await db.commit()
```

---

## 7. Gestion des secrets

### Variables obligatoires en production

```bash
SECRET_KEY=<256-bit hex>           # openssl rand -hex 32
FERNET_KEY=<urlsafe-b64 32 bytes>  # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
DATABASE_URL=postgresql+asyncpg://...
ENVIRONMENT=production
PROBE_API_KEY=wiu_<32 urlsafe>     # uniquement côté probe
```

### Variables fortement recommandées

```bash
CORS_ALLOWED_ORIGINS=https://votre-domaine.example.com   # liste explicite
REGISTRATION_OPEN=false                                  # invite-only
DATA_RETENTION_DAYS=90                                   # purge nightly
HEARTBEAT_INTERVAL=15                                    # check fond
VAPID_PUBLIC_KEY=...   VAPID_PRIVATE_KEY=...             # web push (opt-in)
```

### Rotation

| Secret | Fréquence | Procédure | Impact |
|---|---|---|---|
| `SECRET_KEY` | Compromission ou 12 mois | redéployer avec nouvelle valeur | invalide tous les JWT actifs |
| `FERNET_KEY` | Compromission uniquement | re-chiffrer tous les `AlertChannel.config`, `MonitorTemplate`, `system_settings.oidc_client_secret`, scenario `secret` vars (script à fournir) | indispo passagère des alertes |
| Probe API key | Compromission ou 6 mois | `POST /probes/{id}/rotate-key` | sonde re-enroll requise |
| DB password | Compromission ou 12 mois | `ALTER USER` + redéploiement | brève coupure |
| OIDC client_secret | Selon politique IdP | UI Settings → OIDC | re-login users |
| Android keystore | **JAMAIS** sans pré-publication majeure | rotation impossible post-Play Store | crash auto-update |

### Stockage local

- ✅ Secrets injectés via env vars uniquement (`.env` non commité)
- ✅ `frontend/android/app/release.keystore` ne doit **jamais** être commité (gitignore explicite)
- ✅ `google-services.json` injecté en CI uniquement (base64 GitHub secret)
- ✅ Pre-commit hook `gitleaks` bloque toute string ressemblant à un token

### Audit de logs / réponses API

- ✅ Toute réponse API : secrets canaux masqués (`***`)
- ✅ OIDC `client_secret` jamais retourné après création
- ✅ Refresh tokens hashés SHA-256 — log central voit uniquement `<hash:8>`
- ✅ Probe API key apparaît une seule fois (création/rotation), jamais re-affichable
- ✅ `structlog` redaction sur clés `password`, `token`, `secret`, `api_key`, `webhook_url`

---

## 8. Hardening déploiement

### Réseau

```
[Browser] ──HTTPS/WSS──► [Nginx TLS 1.2+] ──HTTP local──► [FastAPI :8000]
                                                            ├──► [Postgres :5432] (network: backend)
                                                            └──► [Redis :6379]    (network: backend)
[Probe distante] ──HTTPS──► [Nginx /api/v1/probes/*]
```

**Règles obligatoires en production** :
- 🔒 Postgres et Redis : **jamais** exposés publiquement (`expose:` interne uniquement)
- 🔒 Server FastAPI : `bind 127.0.0.1:8000` (déjà appliqué `docker-compose.yml`)
- 🔒 Reverse proxy Nginx unique entrée publique
- 🔒 Healthcheck `/api/health` accessible sans auth ; `/metrics` réservé réseau interne (à protéger ou IP-whitelist)
- 🔒 HSTS preload activé (`max-age=31536000; includeSubDomains; preload`)
- 🔒 Certs Let's Encrypt rotation automatique (`certbot --nginx`)

### Docker production

```yaml
services:
  server:
    user: "1000:1000"          # non-root
    read_only: true            # FS read-only (nécessite tmpfs sur /tmp)
    security_opt:
      - no-new-privileges:true
    cap_drop: [ALL]
    deploy:
      resources:
        limits: { memory: 512m, cpus: "1.0" }
  postgres:
    expose: ["5432"]            # pas `ports:` → réseau interne uniquement
  redis:
    expose: ["6379"]
    command: redis-server --requirepass ${REDIS_PASSWORD}
```

### Headers HTTP (Nginx — déjà configuré)

```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self' wss:; frame-ancestors 'none'" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;
```

### Backup

- ✅ Postgres : `pg_dump` quotidien chiffré GPG (à scripter selon hébergeur)
- ✅ FERNET_KEY backupé séparément (sinon backups DB inutiles)
- ⚠️ Tester `pg_restore` trimestriellement

---

## 9. Incident response sécurité

### Procédure de containment (suspicion de compromission)

1. **Geler** les secrets actifs :
   ```bash
   # Génère un nouveau SECRET_KEY (invalide tous les JWT)
   openssl rand -hex 32
   # Mettre à jour .env, redéployer
   docker compose up -d --force-recreate server
   ```
2. **Révoquer** toutes les sessions : `redis-cli FLUSHDB` (DB des refresh tokens) — force re-login global
3. **Audit log** : exporter et conserver hors-DB
   ```sql
   COPY (SELECT * FROM audit_logs WHERE timestamp > NOW() - INTERVAL '7 days') TO '/tmp/audit_export.csv' CSV;
   ```
4. **Snapshot** : `pg_dump` immédiat + image Docker avant intervention
5. **Communiquer** : status page + email subscribers

### Forensics check-list

- [ ] `docker logs` server depuis l'incident (chercher `auth.failed`, `429`, `403`)
- [ ] `audit_log` : actions par utilisateur compromis
- [ ] `SELECT * FROM users WHERE updated_at > <fenêtre>;` — escalade priv ?
- [ ] `SELECT * FROM probes WHERE created_at > <fenêtre>;` — sondes pirates ?
- [ ] `SELECT * FROM alert_channels WHERE updated_at > <fenêtre>;` — exfil via webhook ?
- [ ] CodeQL re-run sur le commit suspect

### Communication post-mortem

- ✅ Annoncer dans `CHANGELOG.md` section `### Security`
- ✅ Si CVE assignée : remplir GitHub Security Advisory
- ✅ Crédit du reporter si demandé
- ✅ Bump version mineure obligatoire (jamais patch silencieux)

---

## 10. Supply chain

### Surveillance

- ✅ Dependabot — `.github/dependabot.yml` (server, probe, frontend, mobile, GH Actions)
- ✅ pip-audit hebdo — `security-audit.yml`
- ✅ npm audit hebdo — `security-audit.yml`
- ✅ CodeQL `security-extended` — `codeql.yml`
- ⏳ **À ajouter** : génération SBOM (`anchore/sbom-action`) sur `release.yml`
- ⏳ **À ajouter** : signature des images GHCR via Cosign keyless (OIDC GitHub)

### Verrouillage versions

- ✅ Server : `pyproject.toml` borne haute (`fastapi>=0.125,<0.140`)
- ✅ Probe : idem
- ✅ Frontend : `package-lock.json` versionné
- ✅ GH Actions pinnées `@v6` minimum (jamais `@main`)
- ⏳ **À durcir** : pin par SHA pour les actions critiques (`actions/checkout@<sha>`)

### Vérification reporter (extension probe Docker)

- Image probe construite from `python:3.12-slim` officielle
- Playwright browsers pinnés (`PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`)
- Pas de `pip install` from URL ou git+

---

## 11. Contrôles cryptographiques

| Usage | Algorithme | Paramètres | Source |
|---|---|---|---|
| Hash mot de passe | bcrypt | 12 rounds | `bcrypt` |
| Hash refresh token | SHA-256 (slice 32 chars Redis) | n/a | `hashlib` |
| Chiffrement secrets channels | Fernet (AES-128-CBC + HMAC-SHA256) | clé 32 bytes urlsafe-b64 | `cryptography` |
| JWT | HS256 | secret 256 bits | `pyjwt` |
| TLS | TLS 1.2 minimum, 1.3 préféré | ciphers ANSSI | nginx |
| HSTS | `max-age=31536000; includeSubDomains; preload` | n/a | nginx |
| Webhook signature | HMAC-SHA256 | clé partagée | `hmac` |
| Probe API key | bcrypt 12 rounds | 32-byte urlsafe random | `secrets` |

### À éviter

- ❌ MD5, SHA-1 (sauf hash non-cryptographique)
- ❌ Chiffrement symétrique sans IV/nonce aléatoire (Fernet le fait correctement)
- ❌ JWT RS256 sans rotation (préférer rotation HS256 ou OIDC PKCE pour fédération)
- ❌ TLS 1.0 / 1.1 / SSLv3
- ❌ Cipher suites RC4 / 3DES / EXPORT

---

## 12. Rate limiting (table de référence)

Toute modification de cette table doit être reportée dans `FEATURES.md` §11.

| Endpoint | Méthode | Limite | Justification |
|---|---|---|---|
| `/auth/login` | POST | **10/min** | Anti brute-force credential |
| `/auth/register` | POST | **5/min** | Anti enum + spam |
| `/auth/refresh` | POST | **30/min** | Mobile + multi-tab |
| `/auth/me` | PATCH | **30/min** | Self-update |
| `/probes/heartbeat` | POST | **30/min** | Probe health beats |
| `/probes/results` | POST | **60/min** | Probe results push (bursts ok) |
| `/probes/register` | POST | **3/min** | Anti scan |
| `/monitors` | POST | **10/min** | Anti spam monitor |
| `/monitors/{id}/trigger-check` | POST | **20/min** | Évite trigger storm |
| `/config` | GET | **5/min** | Probe config pull |
| `/silences` | POST/DELETE | **20–60/min** | Catch-all silences |
| `/incidents/bulk-ack` | POST | **20/min** | Anti boucle |
| `/incidents/{id}/snooze` | POST | **30/min** | UX bulk |
| `/alerts/channels/{id}/test` | POST | **5/min** | Anti spam canal |
| `/api/v1/extension/download` | GET | **10/min** | Anti scrape |

> **Tout nouvel endpoint public ou écrit DOIT avoir un rate-limit explicite.** Le défaut implicite n'existe pas.

---

## 13. Pre-commit & hooks locaux

### Hooks recommandés

Voir `.pre-commit-config.yaml` à la racine du repo.

### Activation

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

### Commits signés (recommandé)

```bash
git config --global commit.gpgsign true
git config --global user.signingkey <YOUR_GPG_KEY_ID>
```

---

## 14. Politique de mise à jour de ce document

Ce document est **vivant**. Il doit être mis à jour :

- À chaque release **majeure ou mineure** : revue complète § 1, 3, 4, 12
- À chaque ajout d'endpoint avec rate-limit : §12
- À chaque incident sécurité résolu : §9 enrichi du retour d'expérience
- À chaque ajout de canal d'alerte : §11 (chiffrement) + §6 (patterns)
- À chaque rotation de dépendance crypto majeure : §11

### TODO / améliorations identifiées

- [ ] Publier `/.well-known/security.txt` (RFC 9116)
- [ ] Activer signature Cosign keyless sur images GHCR
- [ ] Pin GH Actions par SHA (au minimum sur `release.yml` et `mobile-release.yml`)
- [ ] Générer SBOM (CycloneDX) à chaque release
- [ ] Mettre en place 2FA TOTP côté serveur (mobile = biometric, web = TOTP)
- [ ] Chiffrement at-rest Postgres (TDE ou disque chiffré LUKS)
- [ ] Audit log export S3 immuable (Object Lock) — compliance SOC2

---

## 15. Références

| Document | Lien | Applicable à |
|---|---|---|
| OWASP Top 10 2021 | https://owasp.org/www-project-top-ten/ | §3 |
| OWASP API Security Top 10 2023 | https://owasp.org/API-Security/ | §3, §5 |
| ANSSI RGS v2.0 | https://www.ssi.gouv.fr/entreprise/reglementation/confiance-numerique/le-referentiel-general-de-securite-rgs/ | Auth, JWT |
| ANSSI Recommandations TLS | https://www.ssi.gouv.fr/uploads/2020/06/anssi-guide-recommandations_de_securite_relatives_a_tls12_tls13-v1.2.pdf | Nginx, HSTS |
| ANSSI Programmation Python | https://www.ssi.gouv.fr/guide/regles-de-programmation-pour-le-developpement-securise-de-logiciels-en-langage-python/ | Pydantic, validation |
| NIST SP 800-63B | https://pages.nist.gov/800-63-3/sp800-63b.html | Bcrypt, password policy |
| NIST SP 800-132 | https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-132.pdf | Hash itérations |
| CWE Top 25 | https://cwe.mitre.org/top25/ | Code review |
| CIS Docker Benchmark | https://www.cisecurity.org/benchmark/docker | §8 hardening |
| RFC 9116 (security.txt) | https://datatracker.ietf.org/doc/html/rfc9116 | §14 |

---

*Maintenu par l'équipe WhatIsUp. Tout contributeur peut proposer un amendement par PR — la revue est obligatoire par un mainteneur ayant déjà revu sécurité.*
