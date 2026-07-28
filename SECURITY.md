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
| **A01 — Broken Access Control** | Probe forge résultat cross-monitor | `POST /probes/results` : la sonde ne peut pousser un résultat que pour un monitor de son `network_scope` (scope `all` = servi par toutes) — sinon 403 ; idem `serves_monitor` sur `/probes/diagnostics` | `api/v1/probes.py`, `test_probe_trust.py` |
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
- [ ] **Mass-assignment** : tout endpoint qui écrit depuis du JSON brut (import, bulk) rejoue les mêmes gardes que l'endpoint typé (`assert_can_assign_group`, `assert_can_assign_team`) et chiffre les mêmes champs
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
- 🔴 Endpoint d'import/bulk qui applique un `group_id`/`team_id` du payload sans `assert_can_assign_*` → poisoning de la status page d'un autre tenant
- 🔴 Liaison d'identité SSO sur un `email` dont le provider n'affirme pas `email_verified` → takeover de compte local

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

### Mass-assignment depuis du JSON brut (import / bulk)

```python
# ❌ INTERDIT — group_id vient du payload, aucune vérification d'accès
data = {k: v for k, v in entry.items() if k in config_fields}
monitor = Monitor(owner_id=current_user.id, **data)   # ← group_id d'un autre tenant

# ✅ OK — mêmes gardes que create_monitor / update_monitor
await assert_can_assign_group(db, current_user, uuid.UUID(entry["group_id"]))
data["scenario_variables"] = encrypt_scenario_variables(data["scenario_variables"])
```

Un endpoint qui contourne les schemas Pydantic (`list[dict[str, Any]]`) contourne
aussi tous les validateurs : rejouer explicitement les contrôles d'accès **et**
le chiffrement des secrets.

### Liaison d'identité SSO (OIDC)

```python
# ❌ INTERDIT — l'email suffit à lier/créer un compte
user = await db.scalar(select(User).where(User.email == userinfo["email"]))
user.oidc_sub = sub

# ✅ OK — le provider doit affirmer la vérification de l'adresse
if not _email_is_verified(userinfo):      # claim absent = non vérifié
    return _fail("email_not_verified")
```

Sans ce contrôle, un IdP qui autorise l'inscription sans vérification d'adresse
permet à un attaquant de s'inscrire avec `victime@corp.com` et de récupérer le
compte local de la victime.

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
PROBE_API_KEY=wiu_<prefix>.<secret>  # uniquement côté probe (format émis à l'enrôlement)
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
| `FERNET_KEY` | Compromission uniquement | procédure zéro-downtime ci-dessous : `FERNET_KEY_PREVIOUS` + `python -m whatisup.tools.rotate_fernet` | aucune (déchiffrement multi-clés pendant la transition) |
| Probe API key | Compromission ou 6 mois | `POST /probes/{id}/rotate-key` | sonde re-enroll requise |
| User API key | Compromission ou selon politique | `DELETE /api-keys/{id}` (révocation) | invalidation **immédiate** (éviction cache auth après commit, pas d'attente du TTL 60 s) ; émettre les clés d'intégration en **lecture seule** (scope `read` seul) limite d'emblée les dégâts d'une fuite |
| DB password | Compromission ou 12 mois | `ALTER USER` + redéploiement | brève coupure |
| OIDC client_secret | Selon politique IdP | UI Settings → OIDC | re-login users |
| Android keystore | **JAMAIS** sans pré-publication majeure | rotation impossible post-Play Store | crash auto-update |

#### Rotation `FERNET_KEY` (zéro downtime)

Le déchiffrement est **multi-clés** (MultiFernet) : `FERNET_KEY` = clé **primaire** (seule clé utilisée pour chiffrer) ; `FERNET_KEY_PREVIOUS` = ancienne(s) clé(s), séparées par des virgules, acceptées **en déchiffrement uniquement** pendant la transition. Données concernées : `alert_channels.config` (champs secrets), `monitors.scenario_variables` (variables `secret: true`), `users.totp_secret`, `system_settings.oidc_client_secret`.

1. **Générer** la nouvelle clé : `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. **Redéployer** avec les deux clés : `FERNET_KEY=<nouvelle>` + `FERNET_KEY_PREVIOUS=<ancienne>`. Aucune coupure : les secrets existants restent lisibles via l'ancienne clé, tout nouveau secret est chiffré avec la nouvelle.
3. **Dry-run** (compte-rendu sans écriture) :
   ```bash
   docker compose exec server python -m whatisup.tools.rotate_fernet --dry-run
   ```
4. **Rotation** (re-chiffre tout avec la clé primaire ; idempotent ; ne loggue jamais les valeurs) :
   ```bash
   docker compose exec server python -m whatisup.tools.rotate_fernet
   ```
5. **Vérifier** le compte-rendu : `0 unreadable` attendu (une valeur `unreadable` = plaintext legacy pré-chiffrement, ou clé absente de `FERNET_KEY_PREVIOUS` — jamais modifiée). Relancer l'outil au besoin : un second passage doit rapporter `0 rotated`.
6. **Retirer** `FERNET_KEY_PREVIOUS` de la config et redéployer **toutes** les répliques (aucune ne doit conserver l'ancienne clé). En déploiement multi-répliques, une réplique encore en ancienne config a pu chiffrer un nouveau secret avec l'ancienne clé pendant la transition : **avant de détruire l'ancienne clé**, relancer une dernière fois l'outil et exiger une sortie `0 rotated / 0 unreadable` (code de sortie `0`) — c'est la garantie qu'aucune valeur ne dépend plus de l'ancienne clé. Une sortie non nulle (`unreadable > 0`) = ne PAS détruire la clé, investiguer. Enfin, détruire l'ancienne clé et **re-backuper la nouvelle** séparément de la DB (cf. §8).



Les clés sonde utilisent le format **`wiu_<prefix>.<secret>`** :

- `<prefix>` = identifiant **non secret** (`secrets.token_urlsafe(8)`) stocké en clair dans la colonne indexée `probes.api_key_prefix` (unique). Il permet à `get_current_probe` de résoudre l'**unique** sonde candidate par index et de ne lancer **qu'une seule** vérification bcrypt — au lieu de scanner toute la flotte (ancien coût O(n) bcrypt par requête non cachée).
- `<secret>` = `secrets.token_urlsafe(32)` (~256 bits). Le hash bcrypt couvre **toute** la clé (prefix + secret) : la connaissance du seul préfixe n'autorise rien. Le séparateur `.` est sans ambiguïté (`token_urlsafe` n'émet jamais de point).

**Chemin de migration (rétrocompatible, sans re-hash de masse)** :

1. Les sondes provisionnées avant ce schéma ont `api_key_prefix = NULL` et une clé legacy `wiu_<secret>` (sans point). Elles continuent de s'authentifier via un **scan bcrypt de repli**, désormais restreint aux seules lignes `api_key_prefix IS NULL` (les sondes migrées en sont exclues — un scan qui rétrécit à mesure que la flotte tourne, jusqu'à zéro).
2. Une rotation (`POST /probes/{id}/rotate-key`) — ou tout ré-enrôlement — émet une clé au nouveau format et **remplit `api_key_prefix`** : la sonde bascule alors sur le fast path indexé (une seule bcrypt).
3. Aucune action opérateur requise au-delà de la rotation normale de sécurité. Pour forcer la migration d'une flotte legacy, faire tourner les clés (rotation planifiée à 6 mois du tableau ci-dessus suffit).

> **Limite connue (acceptée)** : sur le slow path nouvelle génération, une clé au préfixe inconnu est rejetée sans lancer de bcrypt (candidat introuvable), alors qu'un préfixe connu au secret invalide en lance une. Ce différentiel de timing ne révèle que l'existence d'un préfixe — un identifiant non secret qui n'autorise aucune authentification (schéma standard des clés API préfixées type GitHub/Stripe). Pas de bcrypt factice ajouté.

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

### Déverrouillage manuel d'un compte (lockout SA2)

Le verrouillage par compte (`services/lockout.py`) est un anti-brute-force :
10 échecs de mot de passe en 15 min → compte verrouillé 15 min. Le verrou
n'est **pas prolongeable** (`SET … NX`) et est **réinitialisé** au premier
login réussi, donc il expire seul. Mais c'est aussi un **vecteur de DoS
ciblé** : quiconque connaît l'email d'une victime peut la verrouiller. Pour
déverrouiller immédiatement (support / faux positif), supprimer les deux clés
Redis. L'index de clé est `sha256(email_normalisé)[:32]` où
`email_normalisé = email.strip().lower()` :

```bash
# Calculer l'index (email en minuscules, sans espaces de bord)
IDX=$(printf '%s' "victime@example.com" | tr 'A-Z' 'a-z' \
      | sha256sum | cut -c1-32)

# Supprimer le compteur d'échecs ET le verrou actif
redis-cli DEL "whatisup:lockout:fail:${IDX}"
redis-cli DEL "whatisup:lockout:lock:${IDX}"
```

> ⚠️ Supprimer les **deux** clés : `fail:` (compteur) et `lock:` (verrou
> actif). Ne retirer que `lock:` laisserait le compteur près du seuil → le
> compte se re-verrouillerait au prochain échec.

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
| Probe API key | bcrypt 12 rounds | format `wiu_<prefix>.<secret>`, secret 32-byte urlsafe ; préfixe non secret indexé (`api_key_prefix`) → 1 bcrypt à l'auth, pas de scan O(n) | `secrets` |

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
| `/auth/register` | POST | *sans limite* | Endpoint désactivé — 403 systématique (invite-only) |
| `/auth/refresh` | POST | **30/min** | Mobile + multi-tab |
| `/auth/me` | PATCH | **30/min** | Self-update |
| `/auth/oidc/login` | GET | **20/min** | Anti spam redirect provider |
| `/auth/oidc/callback` | GET | **20/min** | Anti brute-force state/code |
| `/probes/heartbeat` | POST | **120/min** | Probe health beats |
| `/probes/results` | POST | **600/min** | Probe results push (bursts ok) |
| `/probes/register` | POST | *sans limite* | Superadmin only (JWT) — pas de limite explicite |
| `/probes/{id}/rotate-key` | POST | **10/min** | Rotation clé — superadmin only |
| `/monitors` | POST | **10/min** | Anti spam monitor |
| `/monitors/{id}/trigger-check` | POST | **10/min** | Évite trigger storm |
| `/config` | GET / PUT | **10/min** / **10/min** | Export config complet (requête lourde) / import déclaratif |
| `/silences` | GET / POST / PATCH / DELETE | **60 / 20 / 30 / 30/min** | Catch-all silences |
| `/incidents/bulk-ack` | POST | **20/min** | Anti boucle |
| `/incidents/{id}/snooze` | POST | **30/min** | UX bulk |
| `/alerts/channels/{id}/test` | POST | **10/min** | Anti spam canal |
| `/api/v1/extension/download` | GET | **10/min** | Anti scrape |
| `/alerts/rules` | POST | **30/min** | Création de règle d'alerte — alignée sur PATCH/DELETE existantes |
| `/teams` | GET / POST | **60 / 20/min** | Liste teams / création team |
| `/teams/{id}` | GET / PATCH / DELETE | **60 / 30 / 30/min** | Lecture, renommage, suppression team |
| `/teams/{id}/members` | GET / POST | **60 / 20/min** | Liste membres / ajout membre |
| `/teams/{id}/members/{user_id}` | PATCH / DELETE | **30 / 30/min** | Changement de rôle / retrait membre |
| `/onboarding/status` | GET | **60/min** | Poll d'état onboarding |
| `/onboarding/complete` | POST | **30/min** | Bascule ponctuelle d'état |
| `/audit` | GET | **30/min** | Liste audit log — superadmin only, requête lourde |
| `/groups` | POST | **20/min** | Anti spam group (parité avec `/teams` POST) |
| `/api-keys/{id}` | DELETE | **30/min** | Révocation clé API |
| `/auth/logout` | POST | **30/min** | Aligné sur `/auth/refresh` (session mgmt) |
| `/monitors/{id}/dependencies/{dep_id}` | DELETE | **30/min** | Aligné sur le POST de création (add_dependency) |
| `/monitors/{id}/composite-members/{member_id}` | DELETE | **30/min** | Aligné sur le POST/PATCH de composite members |
| `/public/pages/{slug}/unsubscribe` | GET | **10/min** | Action d'état (désabonnement) exposée sans auth via token |
| `/public/pages/{slug}/subscribe` | POST | **5/min** | Inscription publique — le double opt-in empêche d'abonner un tiers, la limite freine l'envoi en masse de mails de confirmation |
| `/public/pages/{slug}/confirm` | GET | **10/min** | Activation d'un abonnement via jeton à usage unique (aligné sur unsubscribe) |
| GET standard `/api/v1` (listes + détail : alerts channels/rules/events/presets/matrix-templates/matrix, api-keys, auth/me, groups ×3, maintenance, probes + stats, status/monitors/{id}, monitors uptime/history/health-state/probes/incidents/annotations/slo-rules/correlated) | GET | **60/min** | Harmonisation SEC-3 — lecture authentifiée standard, alignée sur le précédent teams/silences |
| `/monitors` + `/monitors/{id}` + `/monitors/{id}/results` | GET | **120/min** | Chemins chauds dashboard (vue principale, détail, polling results 3 s pendant un test) |
| `/monitors/{id}/incidents/{inc}/postmortem` | GET | **30/min** | Génération markdown coûteuse |
| `/auth/oidc/config` + `/push/vapid-public-key` | GET | **30/min** | Publics sans auth mais réponse statique triviale |
| `/api/health` + `/api/metrics` | GET | *sans limite* | Health checks LB/probe/app native + scrape Prometheus — hors routers v1, hors gate CI |

> **Tout nouvel endpoint public ou écrit DOIT avoir un rate-limit explicite.** Le défaut implicite n'existe pas. **Depuis SEC-3 (2026-07-21), les GET aussi** : le gate CI couvre désormais toutes les méthodes sous `api/v1/`.
>
> **Sweep S2 (2026-07-16)** : audit exhaustif de `api/v1/` — 130 fonctions endpoint avaient déjà un décorateur (vagues SA1-SA7), 19 en manquaient : 13 dans le périmètre initial de l'audit (`teams.py` : 9/9, le module n'importait même pas `limiter` ; `alerts.py` : `POST /rules` ; `onboarding.py` : les 2 endpoints ; `audit.py` : `GET /`) plus 6 trouvés hors périmètre pendant le balayage complet (`groups.py POST /`, `api_keys.py DELETE /{id}`, `auth.py POST /logout`, `monitors.py DELETE .../dependencies/{id}` et `.../composite-members/{id}`, `public.py GET .../unsubscribe`). Tous comblés ; `test_rate_limit_coverage.py` fait échouer la CI si un futur endpoint POST/PUT/PATCH/DELETE sous `/api/v1` est ajouté sans décorateur (hors `_EXEMPT_KEYS` documentée : `/auth/register` désactivé, `/probes/register` superadmin-only, tous deux déjà dans ce tableau).
>
> **Sweep SEC-3 (2026-07-21)** : les 30 GET restés sans décorateur sous `api/v1/` sont harmonisés — 60/min standard, 120/min chemins chauds monitors, 10/min export `/config`, 30/min postmortem et publics statiques (`/auth/oidc/config`, `/push/vapid-public-key`). Le gate CI est étendu aux GET (`test_all_get_v1_endpoints_have_rate_limit`), scoping module `whatisup.api.v1.*` — `/api/health` et `/api/metrics` restent volontairement sans limite (hors routers v1).

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
- [ ] Ajouter un rate-limit explicite sur `GET /config` (export) et `POST /probes/register` (actuellement protégés uniquement par JWT / superadmin — cf. §12)
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
