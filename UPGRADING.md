# Upgrading WhatIsUp

## Correctifs de sécurité — lot S6 (déploiement)

Deux changements de comportement, sans migration de base.

**`/api/metrics` refuse les appels anonymes en production.** L'endpoint était
ouvert tant que `METRICS_AUTH_TOKEN` restait vide, en supposant un filtrage par
le reverse proxy — hypothèse fausse pour l'installation par défaut. Désormais :
le `nginx.conf` livré refuse `/api/metrics`, et sans jeton configuré le serveur
répond `401` en production.

- Scraper Prometheus **sur le réseau Docker** (`http://server:8000/api/metrics`,
  sans passer par nginx) : définir `METRICS_AUTH_TOKEN` dans `.env` et ajouter
  `Authorization: Bearer <jeton>` à la configuration du scrape.
- Environnements de dev/test (`ENVIRONMENT != production`) : inchangés, ouverts.

**La sonde locale ne monte plus tout `/shared`.** Le mot de passe superadmin du
premier boot y vit ; la sonde, composant le plus exposé, n'a besoin que de sa
clé d'API. Un nouveau volume `probe_secrets` porte la clé, seul volume monté
dans `probe-local`. Une clé écrite avant la séparation est **migrée
automatiquement** au démarrage du serveur (`/shared/PROBE_API_KEY` →
`/probe-secrets/PROBE_API_KEY`) : aucune action requise. Le fichier
`/shared/ADMIN_PASSWORD` est par ailleurs supprimé automatiquement à la première
connexion superadmin réussie, au lieu d'une simple recommandation.

## Correctifs de sécurité — lot S7 (connexion SSO)

Aucune migration de base, aucune configuration à changer pour l'installation
par défaut (nginx sert le front et proxifie `/api`).

**Le retour SSO ne transporte plus de jetons.** `/auth/oidc/callback`
redirigeait vers `/oidc-callback#access_token=…&refresh_token=…` : n'importe
qui pouvait terminer sa propre connexion SSO et envoyer ce lien à une victime,
dont le navigateur ouvrait alors la session de l'attaquant. Le callback rend
désormais un code opaque à usage unique (`#code=…`), que le front échange
contre les jetons via `POST /auth/oidc/exchange`. Un cookie nonce HttpOnly
(`wiu_oidc_nonce`), posé avant la redirection vers l'IdP, est exigé au retour
**et** à l'échange : un lien fabriqué ailleurs ne mène nulle part.

- **Front hébergé sur un hôte distinct de l'API** : le cookie passe
  automatiquement en `SameSite=None; Secure` (donc **HTTPS obligatoire** — déjà
  imposé en production, où les origines HTTP sont refusées au démarrage), et
  `CORS_ALLOWED_ORIGINS` doit lister l'origine exacte du front, comme
  auparavant.
- **Reverse proxy** : le proxy doit relayer les en-têtes `Cookie` et
  `Set-Cookie` sur `/api/v1/auth/oidc/*` — c'est le comportement par défaut du
  `nginx.conf` livré, à vérifier seulement si vous avez le vôtre.
- **Connexions SSO en vol pendant la mise à jour** : les tentatives entamées
  avant le redémarrage sont refusées (`?error=invalid_state`) — l'utilisateur
  relance la connexion. Fenêtre maximale : 5 minutes.

> **Upgrading to any version ≥ v1.1?** Migrations run automatically at server
> startup (or via `alembic upgrade head`) and every 1.x release is
> backward-compatible — see [CHANGELOG.md](CHANGELOG.md) for per-version detail.
> Special procedures live in [SECURITY.md](SECURITY.md): zero-downtime
> `FERNET_KEY` rotation (§7, v1.16+), account lockout runbook (§9).
> The guide below only covers the historical v0.12.x → v1.0.0 migration.

## SSO / OIDC — `email_verified` now required

Since the security fix for audit finding F16, the OIDC callback refuses to link
or auto-provision an account when the provider does not assert
`email_verified: true` in its userinfo response (a missing claim counts as *not
verified*). Users already bound to an `oidc_sub` are unaffected — only the first
binding is gated.

If SSO logins start failing with `error=email_not_verified`, add `email` to the
configured scopes and make sure the IdP emits the claim (Keycloak, Auth0,
Google, Okta and Entra ID all do by default). For an address the IdP cannot
vouch for, the binding has to be written directly in the database
(`UPDATE users SET oidc_sub = '<sub>' WHERE email = '…'`) — there is
deliberately no API to do it.

## Upgrading to v1.0.0 (from v0.12.x)

## Breaking changes

None. v1.0.0 is fully backward-compatible with v0.12.x data and APIs.

## New features requiring migration

### Database migration

Run Alembic migrations after upgrading the server image:

```bash
docker compose exec server alembic upgrade head
```

Two new migrations will run:
- `m1n2o3p4q5r6` — Creates `teams` and `team_memberships` tables, adds `team_id` column to monitors, groups, channels, maintenance windows, and templates
- `n1o2p3q4r5s6` — Adds `onboarding_completed_at` column to users

### Teams (optional)

Teams are opt-in. Existing installations continue to work exactly as before with single-user ownership. To start using teams:

1. Any user can create a team via `POST /api/v1/teams`
2. The creator becomes the team owner
3. Invite members with `POST /api/v1/teams/{id}/members`
4. Assign resources to teams by setting `team_id` when creating monitors, groups, or alert channels

Team roles: `owner` > `admin` > `editor` > `viewer`

### Onboarding wizard

New users (with no monitors and `onboarding_completed_at = NULL`) will see an onboarding wizard on first login. Existing users with monitors are unaffected.

### Infrastructure-as-Code API

New endpoints for declarative configuration management:
- `GET /api/v1/config` — Export full config as JSON
- `PUT /api/v1/config` — Import declarative config (diff + apply)
- `PUT /api/v1/config?dry_run=true` — Preview changes without applying

### Plugin architecture (internal)

The checker and alert channel dispatch has been refactored into a plugin system. This is an internal change — the API is unchanged. Custom check types and alert channels can now be added by creating a module in the `checkers/` or `channels/` package.

### Light theme

A light theme is now available. Toggle via the sun/moon button in the top bar. The theme is auto-detected from `prefers-color-scheme` on first visit and persisted in `localStorage`.

## Docker upgrade

```bash
docker compose pull
docker compose up -d
# Migrations run automatically on server startup
```

## API stability commitment

Starting with v1.0.0, the `/api/v1/` endpoints are considered stable. Breaking changes will be introduced under `/api/v2/` with a 6-month deprecation period for v1 endpoints.

## Reverse proxy — `TRUSTED_PROXY_IPS`

The server used to trust the `X-Forwarded-For` header of every caller. It now
believes it only from the addresses listed in `TRUSTED_PROXY_IPS`, which
defaults to loopback plus the private ranges docker networks use — the bundled
`docker-compose` + nginx stack needs no change.

Set it if your reverse proxy reaches the API from a public address (a proxy on
another host, a cloud load balancer): `TRUSTED_PROXY_IPS=203.0.113.10` — or add
the LB's range. Getting it wrong is visible, not silent: every request is then
attributed to the proxy's own IP, so per-IP rate limits apply to all clients at
once and audit entries all show the same source.

If you run your own nginx, mirror the shipped config and **overwrite** the
header at the edge — `proxy_set_header X-Forwarded-For $remote_addr;` — rather
than appending with `$proxy_add_x_forwarded_for`. Details in
[SECURITY.md](SECURITY.md) §8.

`TRUSTED_PROXY_IPS=*` restores the old behaviour and is refused at startup in
production.
