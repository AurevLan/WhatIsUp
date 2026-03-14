# Politique de Sécurité — WhatIsUp

> Conforme aux recommandations ANSSI (Agence nationale de la sécurité des systèmes d'information)
> Dernière mise à jour : 2026-03-12

---

## Table des matières

1. [Versions supportées](#versions-supportées)
2. [Signalement d'une vulnérabilité](#signalement-dune-vulnérabilité)
3. [Mesures de sécurité implémentées](#mesures-de-sécurité-implémentées)
4. [Recommandations de déploiement](#recommandations-de-déploiement)
5. [Checklist développeur](#checklist-développeur)
6. [Références ANSSI](#références-anssi)

---

## Versions supportées

| Version | Support sécurité | Notes |
|---------|-----------------|-------|
| 0.3.x   | ✅ Actif        | Version courante |
| 0.2.x   | ⚠️ Correctifs critiques uniquement | |
| 0.1.x   | ❌ Non supportée | Migrer vers 0.3.x |

---

## Signalement d'une vulnérabilité

**Ne pas ouvrir d'issue publique GitHub pour les vulnérabilités de sécurité.**

### Procédure de divulgation responsable (Responsible Disclosure)

1. **GitHub Private Vulnerability Reporting** (recommandé) :
   Onglet `Security` → `Report a vulnerability` → formulaire privé

2. **Email direct** : contacter les mainteneurs via la page GitHub

### Informations à fournir

- Description précise de la vulnérabilité
- Étapes de reproduction (PoC si possible)
- Impact estimé (CVSS si connu)
- Environnement affecté (version, OS, configuration)
- Correctif suggéré (optionnel)

### Délais de traitement

| Étape | Délai |
|-------|-------|
| Accusé de réception | **72 heures** |
| Évaluation initiale | **7 jours** |
| Patch correctif — critique | **30 jours** |
| Patch correctif — élevé | **60 jours** |
| Divulgation publique | Après patch + délai convenu |

---

## Mesures de sécurité implémentées

### Authentification et contrôle d'accès

| Mesure | Détail | Référence ANSSI |
|--------|--------|-----------------|
| JWT HS256 | Access token 15 min, refresh 7 j révocable Redis | RGS Auth |
| Claims JWT obligatoires | `sub`, `exp`, `iss`, `type` validés à chaque requête | — |
| bcrypt 12 rounds | Hachage mots de passe utilisateurs | ANSSI PG-078 |
| Probe API keys | Format `wiu_<32-byte urlsafe>`, hashé bcrypt | — |
| WebSocket auth | Auth par message JSON dans les 5 s (jamais dans l'URL) | ANSSI WS |
| RBAC | `owner_id` sur toutes les ressources, `is_superadmin` pour admin | Moindre privilège |
| Rate limiting | Register: 5/min, Login: 10/min, Probes: 30-60/min | Anti brute-force |

### Protection des données

| Mesure | Détail |
|--------|--------|
| Fernet AES-128-CBC | Chiffrement des secrets alert (bot_token, webhook secret) en base |
| TLS 1.2+ | Chiffrement transport en production (Nginx) |
| Pas de secrets en dur | Toutes les valeurs sensibles via variables d'environnement |
| Hachage irréversible | Mots de passe et API keys jamais stockés en clair |
| `SECRET_KEY` obligatoire | Refus de démarrage en production si valeur par défaut |

### Validation et injection

| Mesure | Détail | Référence |
|--------|--------|-----------|
| Pydantic v2 | Validation stricte à toutes les frontières API | OWASP A03 |
| SQLAlchemy ORM | Requêtes paramétrées — pas d'injection SQL possible | OWASP A03 |
| SSRF webhook | Validation URL + résolution DNS → rejet RFC 1918/loopback | OWASP A10 |
| XSS | Pas de rendu HTML côté serveur, Vue 3 auto-escaping | OWASP A03 |

### En-têtes HTTP de sécurité

```
Content-Security-Policy: default-src 'self'; script-src 'self';
                         style-src 'self' 'unsafe-inline'; img-src 'self' data: https:;
                         connect-src 'self' wss:; frame-ancestors 'none'
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload  (HTTPS only)
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
```

### CORS

- Origines explicitement autorisées (jamais `*` avec `credentials: true`)
- Liste validée au démarrage de l'application

### CI/CD et supply chain

| Mesure | Déclencheur |
|--------|-------------|
| Dependabot | Alertes + MAJ auto (hebdomadaire) |
| pip-audit | Chaque push `main` + lundi 08h UTC |
| npm audit | Chaque push `main` |
| ruff (lint + format) | Chaque push / PR |

---

## Recommandations de déploiement

### Variables d'environnement obligatoires en production

```bash
# Sécurité — OBLIGATOIRES
SECRET_KEY=<256-bit aléatoire>        # openssl rand -hex 32
FERNET_KEY=<clé Fernet valide>        # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
DATABASE_URL=postgresql+asyncpg://... # Connexion sécurisée
ENVIRONMENT=production

# Sécurité — RECOMMANDÉES
CORS_ALLOWED_ORIGINS=https://mon-domaine.example.com
REGISTRATION_OPEN=false               # Désactiver l'inscription publique après bootstrap
```

### Infrastructure

```
[ Navigateur ] ──HTTPS/WSS──► [ Nginx (TLS 1.2+) ] ──► [ FastAPI ]
                                                         ├──► [ PostgreSQL ] (réseau interne)
                                                         └──► [ Redis ]     (réseau interne)
                               [ Probe distante ] ──HTTPS──► [ FastAPI /api/v1/probes/* ]
```

**Règles réseau recommandées :**
- PostgreSQL et Redis : accessibles uniquement depuis le réseau Docker interne
- API : exposée uniquement derrière le reverse proxy Nginx
- Ports 5432/6379 : jamais exposés publiquement
- Healthcheck : `/api/health` sans auth, `/api/metrics` protégé ou réseau interne seulement

### Hardening Docker

```yaml
# docker-compose.prod.yml — bonnes pratiques
services:
  api:
    user: "1000:1000"           # Non-root
    read_only: true             # Filesystem read-only
    security_opt:
      - no-new-privileges:true
    deploy:
      resources:
        limits:
          memory: 512m
          cpus: "1.0"
```

### Rotation des secrets

| Secret | Fréquence recommandée | Procédure |
|--------|----------------------|-----------|
| SECRET_KEY | À compromission + 1 an | Invalide tous les JWT actifs |
| FERNET_KEY | À compromission | Re-chiffrer les configs alert |
| Probe API keys | À compromission + 6 mois | `DELETE + re-register` via deploy wizard |
| DB password | À compromission + 1 an | Rotation Postgres sans interruption |

---

## Checklist développeur

### Avant chaque PR

- [ ] **Validation Pydantic** sur tout paramètre externe (body, query, path, header)
- [ ] **Vérifier l'ownership** : `current_user.id` ou `require_superadmin` sur toute ressource
- [ ] **Aucun secret** dans le code, les logs ou les messages d'erreur API
- [ ] **`.is_(True)`** et jamais `is True` dans les filtres SQLAlchemy
- [ ] **Rate limiter** `@limiter.limit(...)` sur tout endpoint public ou sensible
- [ ] **Audit log** `log_action()` pour les opérations sensibles (CRUD, config)
- [ ] **SSRF** : valider les URLs externes avec `_validate_webhook_url()` ou équivalent
- [ ] **Fernet** : `encrypt_channel_config()` avant stockage des secrets de canaux
- [ ] **WebSocket** : jamais de token dans l'URL, toujours par message JSON
- [ ] **CORS** : pas de `*` avec `allow_credentials=True`

### Patterns interdits

```python
# ❌ INTERDIT — injection potentielle
cursor.execute(f"SELECT * FROM users WHERE email = '{email}'")

# ✅ OK — requête paramétrée SQLAlchemy
await db.execute(select(User).where(User.email == email))

# ❌ INTERDIT — token JWT dans l'URL (apparaît dans les logs)
ws = new WebSocket(`/ws/dashboard?token=${token}`)

# ✅ OK — auth par message
ws.send(JSON.stringify({ type: 'auth', token }))

# ❌ INTERDIT — secret en clair en base
channel.config = {"bot_token": "1234:abcdef"}

# ✅ OK — chiffrement Fernet
channel.config = encrypt_channel_config({"bot_token": "1234:abcdef"})

# ❌ INTERDIT — filtre SQLAlchemy Python
select(Monitor).where(Monitor.enabled is True)  # toujours False !

# ✅ OK — filtre SQL correct
select(Monitor).where(Monitor.enabled.is_(True))
```

---

## Références ANSSI

| Document | Lien | Applicable à |
|----------|------|-------------|
| Guide authentification — RGS | [ANSSI RGS](https://www.ssi.gouv.fr/entreprise/reglementation/confiance-numerique/le-referentiel-general-de-securite-rgs/) | JWT, bcrypt, API keys |
| Recommandations TLS | [ANSSI TLS](https://www.ssi.gouv.fr/uploads/2020/06/anssi-guide-recommandations_de_securite_relatives_a_tls12_tls13-v1.2.pdf) | Nginx, HSTS |
| Guide développement sécurisé | [ANSSI DevSec](https://www.ssi.gouv.fr/guide/regles-de-programmation-pour-le-developpement-securise-de-logiciels-en-langage-python/) | Python, validation |
| OWASP Top 10 2021 | [OWASP](https://owasp.org/www-project-top-ten/) | Toutes catégories |
| NIST SP 800-132 | Password hashing | bcrypt, itérations |

---

*Ce document est maintenu par l'équipe de développement WhatIsUp et doit être mis à jour à chaque release majeure ou lors de la correction d'une vulnérabilité.*
