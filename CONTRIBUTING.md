# Contribuer à WhatIsUp

## Convention de commits — obligatoire

Le projet utilise [Conventional Commits](https://www.conventionalcommits.org/) pour piloter le versioning automatique (`release-please`) et la génération du `CHANGELOG.md`.

### Format

```
<type>(<scope>): <description courte impérative>

[corps optionnel — explique le pourquoi, pas le quoi]

[footer optionnel — BREAKING CHANGE, refs issues]
```

### Types reconnus

| Type | Effet sur la version | Section CHANGELOG |
|---|---|---|
| `feat` | bump **MINOR** | `Added` |
| `fix` | bump **PATCH** | `Fixed` |
| `perf` | bump **PATCH** | `Performance` |
| `security` | bump **PATCH** | `Security` |
| `refactor` | bump **PATCH** | `Changed` |
| `revert` | bump **PATCH** | `Reverted` |
| `docs` | pas de bump | `Docs` (visible) |
| `test` | pas de bump | masqué |
| `build`, `ci`, `chore`, `style` | pas de bump | masqué |

### Breaking change → bump MAJOR

Soit le `!` après le type/scope, soit `BREAKING CHANGE:` dans le footer :

```
feat(api)!: renommer /probes/list en /probes

BREAKING CHANGE: l'endpoint /api/v1/probes/list est supprimé.
Migration : utiliser /api/v1/probes (mêmes paramètres).
```

### Scopes recommandés

- `monitors`, `probes`, `alerts`, `incidents`, `auth`, `oidc`, `teams`, `tags`
- `frontend`, `mobile`, `probe`, `infra`, `deps`
- `ci`, `docs`, `lint`

### Exemples

```bash
git commit -m "feat(monitors): ajouter le check_type SSH"
git commit -m "fix(probe): SSRF guard manquant sur le checker UDP"
git commit -m "perf(stats): remplacer window function par LATERAL JOIN"
git commit -m "security(alerts): chiffrer Telegram bot_token au repos"
git commit -m "docs(security): ajouter matrice OWASP"
git commit -m "feat(api)!: renommer /probes/list en /probes"
```

## Flow de release

1. Tu pousses tes commits sur `main` (avec convention).
2. Le workflow `release-please.yml` ouvre automatiquement une **Release PR** qui agrège tous les commits depuis le dernier tag, met à jour `CHANGELOG.md`, `server/pyproject.toml`, `probe/pyproject.toml` et `frontend/package.json`.
3. Tu **mergeras cette Release PR** quand tu juges qu'il y a assez d'évolutions à publier.
4. Le merge crée automatiquement le tag `vX.Y.Z` et la GitHub Release.
5. Le workflow `release.yml` (déjà existant) se déclenche sur le tag → build & push images GHCR + APK signé.

> **Tu ne tagues plus à la main.** L'ancien `git tag -a vX.Y.Z -m "..."` reste possible en mode urgence (hotfix), mais le flow normal passe par la Release PR.

## Checklist PR — sécurité

Voir `SECURITY.md §5` — checklist obligatoire à cocher dans la description de toute PR touchant l'API ou la DB.

## Mise à jour `FEATURES.md`

Toute PR qui ajoute, modifie ou supprime une feature visible doit mettre à jour la section correspondante de `FEATURES.md` dans le **même commit**.

## Setup environnement

```bash
# Server / probe — dans Docker (recommandé) ou localement
cd server && pip install -e ".[dev]"
cd probe && pip install -e ".[dev]"

# Frontend
cd frontend && npm install

# Pre-commit hooks (lint + secrets scan)
pip install pre-commit
pre-commit install

# Stack complète
docker compose up -d
```

Voir `CLAUDE.md` et `README.md` pour les commandes détaillées.
