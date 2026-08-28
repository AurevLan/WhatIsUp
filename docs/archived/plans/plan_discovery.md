# Plan Discovery — la sonde qui découvre (chantier D)

> Créé le 2026-08-17. Suite du plan V2 (terminé). Tenu à jour à chaque phase livrée.

## Thèse

Le produit ne manque plus de profondeur, il manque de **couverture** : chaque monitor est déclaré à la
main, donc la puissance déployée est proportionnelle au temps humain passé dans les formulaires. L'angle
mort structurel du monitoring en mode sonde : il ne voit que ce qu'on lui a nommé — et l'incident le plus
coûteux est sur le service que personne n'a déclaré.

Le chantier retourne l'atout unique du produit : une sonde est déjà *dans* le réseau du client
(interne/externe, ASN-enrichie, scope-bindée). Elle devient **l'unité de déploiement du produit entier** :
poser une sonde à côté de la prod → l'inventaire est découvert, des monitors pré-câblés sont *proposés*
(jamais créés en silence), et la couverture reste vivante (service disparu → orphelin, nouveau → proposition).

Chaque pilier existant est démultiplié sans être modifié : TLS fleet, Health Engine, templates d'alertes,
status pages couvrent soudain le parc entier au lieu des monitors qu'on a bien voulu saisir.

## ⚠️ Mode d'exécution — IMPÉRATIF

**Chaque lot est conçu pour être exécuté par un agent moins coûteux** (modèle plus petit, contexte frais),
pas par la session qui a écrit ce plan. Conséquences :

- Ce plan est le **contrat** : prémisses déjà vérifiées ici (ne pas les re-dériver), fichiers cibles nommés,
  garde-fous explicites. L'agent exécutant lit ce plan + `CLAUDE.md` + `.claude/codemap.md`, puis exécute
  son lot **uniquement** (pas d'initiative hors périmètre du lot).
- Un lot = une PR = tests dans la foulée (règle du dépôt) + mise à jour de `FEATURES.md`, `CHANGELOG.md`
  (`## [Unreleased]`), `.claude/codemap.md`, et de la table « Suivi » de ce plan.
- Tout ce qui est marqué **[décision]** dans D-0 doit être tranché *avant* de lancer les agents sur D-1+.
- Gates CI non négociables à rappeler dans chaque prompt d'agent :
  - nouveau modèle → import dans `models/__init__.py` + `__all__` (sinon le gate model-drift propose de
    dropper la table) ; migration Alembic testée up/down ; relancer `autogenerate` sur base migrée = 0 diff ;
  - tout endpoint `api/v1` → `@limiter.limit(...)` + `request: Request` (gate rate-limit, GET compris) ;
  - toute string UI → `i18n/en.js` **et** `fr.js` ;
  - vitest via Node 22 (Docker, cf. CLAUDE.md), lint frontend avec `npx eslint . --max-warnings 0` ;
  - `.is_(True)`, imports top-level, pas d'`index=True` sur PK — cf. CLAUDE.md § Patterns SQLAlchemy.

## Prémisses vérifiées (2026-08-17, main `e5dd3f9`)

1. **Le canal de contrôle de la sonde est la réponse au heartbeat.** `scheduler.sync_monitors`
   (`probe/whatisup_probe/scheduler.py:185`) appelle `reporter.heartbeat()` et lit `monitors` +
   `pending_diagnostics` dans la réponse. La découverte se greffe au même endroit : la réponse portera les
   **sources de découverte actives** de la sonde. Aucun nouveau canal à inventer.
2. **Le pattern push existe déjà** : `POST /probes/results` (600/min) et `POST /probes/diagnostics`
   (202 Accepted) dans `server/whatisup/api/v1/probes.py`. Le push d'inventaire est un miroir de
   `/probes/diagnostics` : `POST /probes/discovery`, auth `get_current_probe`, 202, rate-limité.
3. **Les propositions peuvent être pré-câblées avec l'existant** : `MonitorTemplate`
   (`api/v1/templates.py`) et `AlertMatrixTemplate` (presets de canaux par check_type,
   `services/alert_matrix_templates.py`) existent. Ne rien réinventer : une proposition acceptée passe par
   la même logique de création que le CRUD monitors (chiffrement `custom_headers`, audit log, etc.).
4. **Asymétrie de tenancy** : les probes sont enregistrées par un superadmin et partagées via `ProbeGroup` ;
   les monitors sont ownés user/team. Une source de découverte doit donc porter un **propriétaire**
   (user + team_id nullable, comme les monitors) *et* une sonde d'exécution — c'est l'objet de la décision
   D-0-1. L'inventaire découvert est une donnée sensible : scopé au propriétaire de la source, jamais
   cross-tenant (superadmin voit tout, comme partout).
5. **`Probe` n'a pas de champ capabilities** (`models/probe.py`) — la sonde devra déclarer au heartbeat ce
   qu'elle *peut* découvrir (socket Docker monté ? binaires présents ?) pour que l'UI n'offre pas une
   source inopérante.
6. **La sonde a déjà les garde-fous réseau** : `_ssrf_resolve_pinned_sync`, validation host, bornes CPU
   (`checkers/_regex_guard.py`). Tout scan de découverte réutilise ces primitives — aucune connexion
   sortante hors de ce chemin (règle absolue CLAUDE.md § Sécurité).

## Décisions D-0 (à trancher avant D-1)

1. **[décision] Où vit la config de source.** Recommandation : table `discovery_sources`
   (`id, owner_id, team_id nullable, probe_id FK, source_type, params JSONB, enabled, created/updated`).
   Le heartbeat renvoie les sources `enabled` de la sonde. Alternative écartée : config par sonde dans
   `Probe` (pas de propriétaire → impossible de router les propositions vers un tenant).
2. **[décision] Types de sources du premier lot.** Recommandation : `docker` (socket read-only : conteneurs,
   labels, ports publiés) + `port_scan` (CIDR **déclaré** + liste de ports bornée) en D-1 ;
   `dns_zone` (AXFR ou liste d'enregistrements via résolveur déclaré) en D-4. Kubernetes = hors premier
   lot (surface d'auth trop large pour démarrer).
3. **[décision] Transport de l'inventaire.** Recommandation : la sonde pousse un **snapshot complet par
   source** à chaque run (`POST /probes/discovery`, payload borné : cap N services/source, champs typés
   `host, port, proto, hints {tls, http_status, server_header, container_labels…}`). Le serveur fait le
   diff — snapshot idempotent, pas de delta à réconcilier côté sonde.
4. **Non négociable (pas une décision)** : la découverte **propose, n'écrit jamais seule**. États d'un
   service découvert : `proposed → accepted | dismissed`, plus `orphaned` (lié à un monitor dont la cible a
   disparu de l'inventaire). Un refus est mémorisé (ne plus re-proposer le même service). Un mode
   auto-adopt opt-in par source est envisageable **après** D-4, jamais avant.
5. **Non négociable** : scan borné et déclaré. `port_scan` refuse un CIDR plus large que /24 par défaut
   (knob), liste de ports explicite (pas de 1-65535), rythme limité côté sonde. Le socket Docker est monté
   read-only et **absent par défaut** du compose (opt-in documenté).

## Phases

| Phase | Contenu | Surface |
|---|---|---|
| **D-0** | Cadrage + modèle. Trancher les [décisions]. Tables `discovery_sources` + `discovered_services` (migration Alembic, modèles importés, schemas In/Out/Update), CRUD `api/v1/discovery.py` (sources : owner-scoped ; services : liste + accept + dismiss), rate-limits, audit log sur mutations, tests serveur. Pas encore de sonde ni d'UI. | serveur |
| **D-1** | Moteur de découverte côté sonde : module `probe/whatisup_probe/discovery/` (registre par `source_type`, même pattern que `checkers/`), sources `docker` + `port_scan`, capabilities au heartbeat, push `POST /probes/discovery`, bornes (cap services, rythme, CIDR/ports), tests probe. Le serveur stocke le snapshot tel quel (réconciliation en D-2). | probe + endpoint ingest |
| **D-2** | Réconciliation serveur (`services/discovery.py`) : normalisation de cible (host:port:proto), matching inventaire ↔ monitors existants du tenant, calcul des états (`proposed`/`orphaned`/disparition), **pré-remplissage de proposition** (check_type déduit — 443→http+TLS, 5432→tcp, 25→smtp…, groupe/tags depuis labels, template applicable). Accept = création via la logique CRUD existante + matrice d'alertes via `AlertMatrixTemplate`. Tests : matching, idempotence du snapshot, cross-tenant impossible. | serveur |
| **D-3** | UI : vue `DiscoveryView` (CRUD sources + revue en masse des propositions, bulk accept/dismiss, raison du refus), badge « orphelin » sur `MonitorsView`/`MonitorDetailView`, i18n en+fr, empty states (`EmptyState`), conventions responsive (cartes < md, cf. CLAUDE.md § Responsive), tests vitest. | frontend |
| **D-4** | Dérive continue + finitions : re-proposition quand un service refusé *change* (port/nature), source `dns_zone`, événement d'audit sur accept en masse, docs (README/FEATURES §), compose opt-in socket Docker documenté. | transverse |

## Sécurité (à traiter comme B-3 : l'ordre des vérifications *est* la conception)

- **Le socket Docker est un privilège** : montage `:ro`, jamais monté par défaut, capability déclarée au
  heartbeat — l'UI n'offre la source que si la sonde la déclare.
- **L'inventaire est une donnée sensible** : `discovered_services` scopé au propriétaire de la source
  (owner/team, superadmin bypass explicite), jamais exposé via probe ou endpoints publics.
- **La sonde ne reçoit que ses propres sources** (jointure `probe_id` dans le heartbeat), et le serveur
  **rejette un push de découverte pour une source qui n'appartient pas à la sonde authentifiée** — même
  principe que le scope-binding des résultats (v1.15, H1/H2).
- **Aucune connexion sortante hors des primitives durcies** de la sonde (résolution épinglée, validation
  host). Un CIDR déclaré ne dispense pas de refuser loopback/metadata.
- **Payload borné** : cap services/source, tailles de champs, labels filtrés (pas de valeurs d'env, jamais
  de secrets Docker) — le filtrage se fait **côté sonde**, avant transport.
- Endpoints : rate-limits partout (gate CI), `extra="forbid"` sur les schemas In/Update.

## Hors périmètre D (backlog assumé)

| Item | Pourquoi |
|---|---|
| Source Kubernetes | Surface d'auth (ServiceAccount, RBAC K8s) = un lot à part entière, après la preuve sur Docker/scan |
| Auto-adopt sans revue | Contraire au principe « jamais silencieux » tant que la réconciliation n'a pas prouvé sa précision en réel |
| Découverte applicative (endpoints HTTP internes, OpenAPI) | Dépend d'une source réseau fiable d'abord |
| Suppression automatique des orphelins | On signale, on ne détruit jamais de config utilisateur |

## Suivi

| Phase | État | PR |
|---|---|---|
| D-0 cadrage + modèle | ✅ 2026-08-17 (mergée, main `7f3ed96`) | #368 |
| D-1 moteur sonde (docker + port_scan) | ✅ 2026-08-23 (mergée, main `d1289fd`) | #369 |
| D-2 réconciliation + propositions | ✅ 2026-08-23 (mergée, main `d1ac1a2`) | #371 |
| D-3 UI revue + orphelins | ✅ 2026-08-24 (mergée, main `191edb5` ; l'audit bulk prévu en D-4 est soldé ici) | #372 |
| D-4 dérive continue + dns_zone | ✅ 2026-08-24 (mergée, main `f6beb58`) — **CHANTIER D COMPLET** | #373 |

## Reprise D-1 — SOLDÉE le 2026-08-23 (PR #369, main `d1289fd`)

Runbook déroulé intégralement : validations synchrones vertes (probe 223 passed, serveur 1199 passed
hors les 2 `test_trusted_proxy` locaux connus, ruff, round-trip alembic + drift 0), revue sécurité du
contrat D-1 conforme. Trois correctifs sortis de la validation, à connaître pour la suite :
- **Dédup intra-payload** dans `push_discovery` : deux services normalisant vers la même cible
  (`HOST` vs `host`) violaient `uq_discovered_services_source_target` au commit → 500. Set `seen_targets`,
  premier gagne (+ test).
- **Hang infini de la suite probe** : le listener de `test_open_port_detected_on_real_listener` avait un
  handler `lambda r, w: None` qui ne fermait jamais la connexion acceptée ; depuis Python 3.12,
  `Server.wait_closed()` attend toutes les connexions actives → suite bloquée pour toujours (local ET CI).
  Fix : `lambda r, w: w.close()`. **Règle : tout `start_server` de test doit fermer ses writers.**
- **CodeQL high** sur `os.chmod(path, 0o666)` en cleanup de test → `0o600` (suffisant pour le unlink).

**Leçon d'exécution (à intégrer aux prompts D-2+)** : l'agent Sonnet s'est arrêté deux fois en se mettant
« en attente » d'une tâche de fond (Monitor/`docker run -d`) sans commiter. Tout prompt d'agent doit
interdire explicitement Monitor/run_in_background/`docker run -d` pour les tests et exiger l'exécution
synchrone (timeout Bash 600000 ms), avec l'ordre « ne termine pas ton tour avant que le commit existe ».

## Reprise D-4 — validée le 2026-08-24, branche `feat/discovery-d4`

Périmètre livré : (1) re-proposition d'un `dismissed` dont la nature change — colonne
`dismissed_fingerprint`, fonction pure `dismissal_fingerprint(hints)` (sous-ensemble stable
`image`/`container_name`/`server_header`, sha256 tronqué, même recette que `series_hash` C-1), capturée
au dismiss (jamais relue plus tard — l'ingestion D-1 rafraîchit `hints` en place), transition ajoutée à
`reconcile_source_push` ; (2) source `dns_zone` (sonde + serveur + UI) — AXFR contre un résolveur
déclaré par IP, aucun fallback de scan au refus, cap 500 enregistrements, `_ssrf_resolve_pinned_sync`
avant toute connexion, `relativize=False` pour lire des noms absolus sans reconstruction manuelle ; (3)
finitions — bloc opt-in commenté (socket Docker) dans `docker-compose.yml`, section README « Automatic
discovery », FEATURES.md/CHANGELOG.md à jour. L'item « audit accept en masse » était déjà soldé en D-3,
non repris ici.

Validations synchrones vertes : serveur 1261 passed / 30 skipped (suite complète, aucune régression),
probe 238 passed / 1 skipped (suite complète), frontend vitest 500 passed / 53 fichiers (le seul échec
observé — `extensionPlaywrightExport.test.js` — est un artefact du montage Docker limité à `frontend/`
seul, qui ne voit pas `../../extension/background.js` ; confirmé disparu en montant tout le repo), eslint
`--max-warnings 0` vert, ruff check+format verts, round-trip alembic (`upgrade head` → `downgrade -1` →
`upgrade head`) + `check_model_drift.py` = 0 diff sur Postgres 16 jetable.

Écart mineur au prompt : le prompt suggérait des clés de hints `target`/`adresse` pour `dns_zone` ; le
code utilise une seule clé `value` (couvre IP comme nom CNAME sans distinguer les deux), documenté dans
`dns_zone.py` et les tests. Aucun autre écart.

## Règle de mise à jour

Cocher chaque phase à la merge de sa PR, avec le numéro. Toute phase livrée = tests dans la foulée +
`FEATURES.md` + `CHANGELOG.md` + `.claude/codemap.md`. Si un pattern ou un knob d'exploitation apparaît,
le documenter dans `CLAUDE.md` (nouvelle section « Découverte (plan D) »).
