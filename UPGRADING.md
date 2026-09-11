# Upgrading WhatIsUp

## v2.0.0 — le grand dégraissage

La v2 **retire** beaucoup et n'ajoute presque rien : une revue produit a arbitré que
plusieurs fonctionnalités coûtaient une entrée de navigation permanente, un concept de
plus ou un verdict faux, pour un usage nul ou mieux servi ailleurs. Presque tout est
migré automatiquement. **Deux choses, et deux seulement, exigent une action de ta part
AVANT de monter** — sans quoi la migration s'arrête net et ne change rien.

### ⛔ À faire avant de monter

Les deux migrations ci-dessous **refusent de tourner** plutôt que d'inventer une
conversion qui perdrait de l'information. Elles lèvent une erreur explicite, ne
modifient rien, et se rejouent une fois le terrain dégagé.

**1. Moniteurs `udp` ou `composite`.** Il n'existe aucune conversion sans perte — une
agrégation composite de N moniteurs ne devient pas un moniteur unique. Vérifie :

```sql
SELECT count(*) FROM monitors WHERE check_type IN ('udp', 'composite');
SELECT count(*) FROM composite_monitor_members;
```

Si ce n'est pas `0` partout : retype ou supprime ces moniteurs et leurs liens. Un `udp`
se remplace par `ping` (joignabilité de l'hôte), `dns` (pour DNS) ou `heartbeat` poussé
par l'application. Un `composite` se remplace par un **groupe** (affichage agrégé), une
**dépendance** + `suppress_on_parent_down` (causalité), ou une `SLORule` `quorum_down`
(consensus multi-sondes).

**2. Règles d'alerte sur métrique poussée.** `metric_above` / `metric_below` /
`metric_absent` disparaissent. Vérifie :

```sql
SELECT count(*) FROM alert_rules
 WHERE condition IN ('metric_above', 'metric_below', 'metric_absent');
SELECT count(*) FROM incidents WHERE alert_rule_id IS NOT NULL;
```

Si ce n'est pas `0` : supprime ces règles, et laisse leurs incidents se résoudre ou
supprime-les. Le besoin se replace mieux ailleurs — un endpoint applicatif qui répond
`500` passé son propre seuil, surveillé par un check `http` ordinaire (le seuil vit
alors dans le code qui le connaît, pas dans un second système), ou un `heartbeat` pour
« l'agent est mort ».

⚠️ **L'ingestion de métriques et la corrélation métrique↔incident ne bougent pas.**
`POST /metrics/{monitor_id}`, les tables `custom_metrics` / `metric_series` et le
panneau de corrélation dans le post-mortem restent intacts. Seul le *déclenchement
d'alerte* sur une métrique disparaît.

### 🐳 L'image de sonde n'embarque plus de navigateur

`whatisup-probe` passe de **1,97 Go à ~480 Mo**. Déployer une sonde est le geste que
l'on refait pour chaque point d'observation ; Chromium y pesait pour la fonctionnalité
la moins utilisée du produit.

- **Tu n'utilises pas de moniteur `scenario`** : rien à faire, l'image maigrit.
- **Tu utilises des scénarios Playwright** : bascule sur `ghcr.io/aurevlan/whatisup-probe:2.0.0-browser`
  (ou `:latest-browser`). La fonctionnalité est identique, seule l'image change.

Une sonde sans navigateur à qui l'on confie un moniteur `scenario` **ne plante pas** :
le check échoue avec un message qui nomme l'image `-browser` à utiliser.

### 🔌 L'extension navigateur disparaît

`GET /api/v1/extension/download` et le panneau de téléchargement dans les Réglages sont
retirés. Pour enregistrer un parcours plutôt que l'écrire : `playwright codegen`
(officiel, maintenu par Microsoft), puis **« Importer »** dans le Scenario Builder, qui
accepte désormais un script codegen en plus de son propre format JSON.

### 🔁 Migrations automatiques — rien à faire

Tout ce qui suit est converti au démarrage, sans perte, et **sans changement de
comportement observable** pour qui passe par l'interface.

| Ce qui disparaît | Ce que ça devient |
|---|---|
| `any_down`  | `availability` avec `quorum_ratio` NULL — « au moins une sonde » |
| `all_down` | `availability` avec `quorum_ratio = 1.0` — « toutes les sondes » |
| `response_time_above` · `response_time_above_baseline` · `anomaly_detection` | `latency_anomaly`, le mode se déduisant du champ renseigné (`threshold_value` / `baseline_factor` / `anomaly_zscore_threshold`) |
| `renotify_after_minutes` | une politique d'escalade à un barreau par canal, même cadence, répétition indéfinie |
| `AlertSilence` | une `MaintenanceWindow` avec `is_maintenance = false` (l'incident s'ouvre et compte, seul l'envoi est coupé) |
| `check_type` `keyword` / `json_path` | `check_type = http`, les champs d'assertion conservés tels quels |
| `MonitorTemplate` | un bouton **« Dupliquer »** sur la fiche moniteur, disponible pour *tous* les types |

### 🧭 L'interface bouge, rien n'est perdu

La navigation passe de **17 à 11 entrées**. Aucune fonctionnalité n'est retirée — elles
changent de place :

- **Graphe de dépendances** → replié dans la fiche moniteur et le panneau d'incident.
- **Flotte TLS** → vue « Certificats » de la liste des moniteurs. L'endpoint reste.
- **Audit** → sous Réglages. Le journal est intact (c'est une exigence de conformité).
- **Astreinte** → onglet d'Alertes.
- **Silences** → fusionné dans « Suppressions », avec une case « compter comme
  maintenance planifiée » qui porte la seule différence de fond entre les deux objets.
- Le geste « je touche à ça, tais-toi 30 minutes » est désormais offert **depuis la
  fiche du moniteur**, avec des presets de durée.

### 🔧 Appelants d'API — ce qui renvoie maintenant 4xx

Si tu pilotes WhatIsUp par script, par import/export de configuration ou par IaC :

- `check_type` `udp` · `composite` · `keyword` · `json_path` → rejetés. Utiliser
  `http` avec les champs d'assertion pour les deux derniers.
- `condition` `any_down` · `all_down` · `response_time_above` ·
  `response_time_above_baseline` · `anomaly_detection` · `metric_above` ·
  `metric_below` · `metric_absent` → rejetés. Voir la table ci-dessus.
- `renotify_after_minutes` dans un payload de règle → **422**.
- `GET /api/v1/extension/download` → **404**.

### ↩️ Revenir en arrière

Chaque migration est réversible (`alembic downgrade`), **sauf ce qu'elles ont refusé de
faire** : les deux garde-fous ci-dessus ne créent rien, il n'y a donc rien à défaire.
Comme pour toute montée de version majeure, **sauvegarde la base avant** :

```bash
docker compose exec -T postgres pg_dump -U whatisup -d whatisup | gzip > avant-v2.sql.gz
```


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

Optional but recommended: verify the release before pulling it. Starting with
the first release built after the supply-chain-signing change, `whatisup-server`
and `whatisup-probe` images (and the release APK) are signed keylessly with
[Cosign](https://docs.sigstore.dev/cosign/overview/) — see
[SECURITY.md § Vérifier une release](SECURITY.md#10-supply-chain) for what the
signature does and does not prove.

```bash
scripts/verify-release.sh 1.25.0   # requires cosign — fails loudly on a missing/invalid signature
```

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
