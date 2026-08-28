# Plan V2 — 2026-07-28

> Prise de recul post-v1.17.0. Le produit est **complet en tant qu'uptime monitor blackbox self-hosted**
> (18 piliers, 181 endpoints, 67 migrations, 24,5k LOC serveur / 3,6k probe / 29,7k front).
> Une V2 n'est donc pas « plus de checks » — c'est un **changement de catégorie**.
> Ce document ne retient que 3 chantiers structurants. Tout le reste est listé en « hors périmètre ».

**Verdict langage** (question amont, tranchée) : Python reste le bon choix côté serveur — la charge est
I/O-bound (asyncpg / Redis / dispatch HTTP), le goulot est Postgres, pas le GIL. Réécrire déplacerait
24,5k LOC pour gagner là où ça ne coince pas. Le seul cas défendable est la **probe** (binaire Go statique,
empreinte × N déploiements) — voir « hors périmètre ». **Le langage n'est pas le problème de perf : la couche
de données l'est.** D'où le chantier A en prérequis.

---

## Vue d'ensemble

| # | Chantier | Nature | Effort | Dépendance |
|---|---|---|---|---|
| **A** | Fondation time-series (partitionnement + rollups) | Prérequis technique, **non négociable** | L | — |
| **B** | On-call & escalade | Feature produit, **meilleur ratio valeur/effort** | M-L | aucune (parallélisable avec A) |
| **C** | Ingestion push (métriques applicatives) | Pari de catégorie | L | **A obligatoire** |

Séquencement : `A-0` (mesure) d'abord. Puis **A et B en parallèle** (B ne touche pas la couche données).
**C strictement après A** — sinon on reproduit la table plate qu'on vient de corriger.

---

## Chantier A — Fondation time-series

### Constat (vérifié)

- `check_results` (`server/whatisup/models/result.py:42-97`) : **table plate, non partitionnée**, 2 index seulement
  (`ix_cr_monitor_checked_at`, `ix_cr_probe_checked_at`), et des colonnes JSONB lourdes par ligne
  (`scenario_result`, `tls_audit`, `dns_authoritative`, `dns_resolved_values`).
- **Aucun rollup, aucune vue matérialisée, aucun agrégat continu.** Un seul `date_trunc` dans tout le backend
  (`services/stats.py:432`, `compute_percentile_timeseries`) — calculé à la volée sur le brut.
- `compute_daily_history` (`stats.py:343`), `compute_daily_history_bulk` (`:382`), `compute_uptime_in_range` (`:263`)
  scannent tous le brut.
- Unique mécanisme de rétention : `purge_old_results` (`services/retention.py:16`) — un `DELETE` global par âge,
  tâche nightly (`main.py:120`), défaut 90 j.

**Conséquence** : tout plafonne ici — rétention longue, SLO trimestriels, comparaisons année/année,
status pages historiques, et le chantier C. Le `DELETE` massif nightly est en plus le pire profil d'écriture
possible pour Postgres (bloat + autovacuum).

### Phases

| Phase | Contenu | Effort |
|---|---|---|
| **A-0** | ✅ **FAIT le 2026-07-28** — mesures ci-dessous. | S |
| **A-0 bis** | ✅ **FAIT le 2026-07-29** — quick wins découverts par A-0 (voir « Résultats A-0 bis »). | S |
| **A-1** | ✅ **FAIT le 2026-08-06** — voir « Résultats A-1 ». Partitionnement mensuel `PARTITION BY RANGE (checked_at)`, PK `(id, checked_at)`. La copie par lots annoncée ici s'est révélée **évitable** : l'ancienne table est attachée telle quelle. | L |
| **A-2** | ✅ **FAIT le 2026-08-07** — voir « Résultats A-2 ». Table `check_rollups_1h` + tâche de fond incrémentale (lock leader). Grain **`(monitor_id, bucket)`** et non `(…, probe_id, …)` : l'uptime est un consensus cross-probe et les percentiles ne se poolent pas. | M |
| **A-3** | ✅ **FAIT le 2026-08-07** — voir « Résultats A-3 ». Les 4 fonctions analytiques lisent les rollups pour les heures couvertes, le brut pour le reste (heure en cours, sliver de tête, retard du builder). Frontière **dérivée** de `max(bucket)`, pas configurée. | M |
| **A-4** | ✅ **FAIT le 2026-08-07** — voir « Résultats A-4 ». `DATA_RETENTION_DAYS` ne régit plus que le brut, `ROLLUP_RETENTION_MONTHS` (13) régit les rollups. **Écart au plan** : le défaut brut reste 90 j (raccourcir = choix par déploiement, pas un effet de bord de mise à jour), et il a fallu ajouter un **interlock** que le plan n'avait pas vu. | S |

### Résultats A-0 (mesuré le 2026-07-28 sur la prod live)

**Volumétrie** — régime stable atteint (rétention 90 j saturée) :

| Métrique | Valeur |
|---|---|
| Lignes `check_results` | **4 916 730** |
| Taille totale | **3 065 Mo** — heap 1 538 Mo · **index 1 527 Mo** · toast 8 ko (vide) |
| Débit | **~60 500 lignes/jour** (stable sur 10 j) |
| Fenêtre | 2026-04-29 → 2026-07-28 (90 j) |
| Largeur moyenne | 328 octets/ligne |
| Périmètre | 16 monitors, 3 probes |
| `shared_buffers` | **128 Mo** (défaut PG) pour une table de 3 Go |

**Constat n°1 — les index pèsent autant que les données (1 527 Mo vs 1 538 Mo), et ~850 Mo sont morts ou redondants :**

| Index | Taille | `idx_scan` | Verdict |
|---|---|---|---|
| `ix_check_results_monitor_checked` `(monitor_id, checked_at DESC)` | 428 Mo | **1 703 109** | ✅ le vrai index de travail |
| `ix_cr_monitor_checked_at` `(monitor_id, checked_at)` | **480 Mo** | 3 849 | ❌ **redondant** — un btree se parcourt dans les deux sens, le DESC le couvre |
| `ix_cr_probe_checked_at` `(probe_id, checked_at)` | **372 Mo** | **0** | ❌ **jamais scanné** (stats jamais reset, ≥5 j d'uptime) |
| `check_results_pkey` `(id)` | 247 Mo | 1 511 512 | ✅ |
| `ix_cr_checked_at_brin` BRIN | 216 ko | 749 | ✅ coût nul |

→ **~852 Mo (28 % de la table) récupérables sans aucun refactor.**

⚠️ **Divergence modèle ↔ base** : `models/result.py:94-97` ne déclare que **2** index ; la base en a **5**.
Trois ont été ajoutés par migration hors du modèle. À réaligner (sinon `autogenerate` proposera de les dropper).

**Constat n°2 — les 1,5 Go d'index ne servent pas les requêtes analytiques.** `EXPLAIN ANALYZE` de
`compute_daily_history` (90 j, 1 monitor, `monitor_id` littéral) :

```
Parallel Seq Scan on check_results  (rows=114639, Rows Removed by Filter: 1523449)
  Buffers: shared hit=15986 read=180922        -- 1,4 Go relus depuis le disque
  Sort Method: external merge  Disk: 2472kB    -- tri sur disque
Execution Time: 2777 ms
```
Le planner **ignore** `(monitor_id, checked_at)` : 7 % de sélectivité sur un heap éparpillé ⇒ le seq scan
est moins cher. Les index ne servent que les point-lookups « derniers N résultats ». **C'est la justification
centrale des rollups** : un rollup 1 h ferait ~110 k lignes (quelques Mo) au lieu de 4,9 M.

**Constat n°3 — le pire chemin est public, non authentifié et non caché.**
`compute_daily_history_bulk` (90 j × tous les monitors) = **9 535 ms** mesuré.
Appelé par `api/v1/public.py:170` — page de statut publique, `@limiter.limit("60/minute")`, **aucun cache**.
Aggravant : `_fetch_check_rows` (`stats.py:197-223`) ne fait **aucune agrégation SQL** — il rapatrie toutes
les lignes brutes en Python et les groupe avec un `defaultdict` (`stats.py:356-362`, `:398-404`).
60 req/min × 9,5 s ⇒ amplification triviale. **À traiter en A-0 bis, pas en A-3.**

**Constat n°4 — JSON `null` au lieu de SQL NULL.** `scenario_result`, `tls_audit`, `dns_resolved_values`
stockent la valeur JSON `null` (5-9 octets, `pg_column_size` vérifié) plutôt que SQL NULL sur la quasi-totalité
des lignes ⇒ aucun gain de NULL-bitmap. Ordre de grandeur : ~100 Mo. Basse priorité, mais à corriger côté probe.

### Ce que A-0 change au plan

Le diagnostic de départ est **confirmé** (table plate, zéro rollup, purge par `DELETE`), mais la mesure révèle
qu'une part importante du gain est atteignable **sans** le refactor lourd. D'où l'insertion de **A-0 bis** :

| Action | Gain | Risque |
|---|---|---|
| `DROP INDEX ix_cr_probe_checked_at` (0 scan) | −372 Mo | Faible — recréable ; vérifier d'abord `ProbeTimelineView` / `latest_results_subq(group_col=probe_id)` |
| `DROP INDEX ix_cr_monitor_checked_at` (redondant) | −480 Mo | Faible — le DESC couvre le même usage |
| Réaligner `models/result.py` sur les 5 index réels | — | Nul — évite un drop accidentel par `autogenerate` |
| Cache Redis sur la page publique (TTL 60 s) | 9,5 s → ~0 ms | Faible — invalidation déjà outillée (`invalidate_uptime_cache`) |
| `shared_buffers` 128 Mo → 1 Go | Moins de relecture disque | Nul — paramètre compose |

Ces cinq actions ne rendent **pas** A-1→A-4 inutiles : le seq scan analytique et le `DELETE` nightly restent.
Mais elles retirent l'urgence, et permettent de faire A-1 proprement plutôt que dans l'urgence.

### Résultats A-0 bis (livré le 2026-07-29)

| Action | Livraison | Écart au plan |
|---|---|---|
| `DROP INDEX ix_cr_probe_checked_at` + `ix_cr_monitor_checked_at` | migration `f2a3b4c5d6e7` — upgrade/downgrade/upgrade testés sur PG 16 réel | conforme (−852 Mo) |
| Réaligner `models/result.py` | `__table_args__` déclare les 2 index réels (`ix_check_results_monitor_checked`, `ix_cr_checked_at_brin`) | **piège trouvé** — voir ci-dessous |
| Cache Redis page publique | `PUBLIC_MONITORS_CACHE_TTL = 60` sur `/public/pages/{slug}/monitors`, helpers **fail-open** (`redis_get_safe` / `redis_setex_safe`) | page vide volontairement **non** cachée : sinon un 1er moniteur reste invisible 60 s |
| `shared_buffers` | `command:` postgres paramétré par `.env` : `shared_buffers` 128 Mo → **256 Mo**, `work_mem` 4 → 16 Mo, `effective_cache_size` 768 Mo, `maintenance_work_mem` 128 Mo | **la limite mémoire du conteneur était à 512 Mo** — 1 Go de `shared_buffers` aurait fait OOM. Limite passée à 1 g, tout est surchargeable (`POSTGRES_SHARED_BUFFERS`, `POSTGRES_MEM_LIMIT`…). Pour l'hôte de prod : viser `SHARED_BUFFERS=1GB` / `MEM_LIMIT=3g` |

**Piège vérifié (à retenir pour A-1)** : contrairement à ce qu'on supposait, cette version d'alembic **compare
bien les expressions d'index**. Déclarer `ix_check_results_monitor_checked` comme un simple couple
`(monitor_id, checked_at)` fait dire à `autogenerate` :
`Detected changed index ... expression #2 'checked_at DESC' to 'checked_at'` → il proposait de **reconstruire
les 428 Mo de l'index et de perdre l'ordre DESC** dont dépend le LATERAL de `fetch_latest_results`. Le modèle
déclare donc `text("checked_at DESC")`. `postgresql_using` (BRIN), lui, n'est pas comparé.
Vérifié en réel : `alembic revision --autogenerate` sur une base migrée ne produit **plus aucun diff** sur
`check_results` (le reste du dépôt en produit — divergence modèle↔base plus large, hors périmètre).

### Résultats A-0 ter — resync modèle ↔ schéma (livré le 2026-08-05)

Prérequis explicite d'A-1 : `autogenerate` produisait **23 diffs** sur une base à `head`, aucun voulu. Avec ce
bruit, un vrai diff introduit par le partitionnement serait passé inaperçu.

Réparti en deux : **17 diffs corrigés côté modèles seuls** (aucune DDL) et **3 opérations en base**
(migration `d5e6f7a8b9c0`, upgrade/downgrade/upgrade + `downgrade base` testés sur PG 16).

| Diff | Cause | Correctif |
|---|---|---|
| drop `audit_logs` + `maintenance_windows` (7 diffs) | modèles jamais importés dans `models/__init__.py`, donc absents de `Base.metadata` | import + `__all__` |
| add `ix_<table>_id` × 6 | `UUIDPrimaryKeyMixin` déclarait `index=True` **sur la PK** | flag retiré + drop des **16 index morts** réellement présents en base |
| add `ix_slo_rules_monitor_id` | `index=True` sur une colonne déjà en tête de `ix_slo_rules_monitor_enabled` | flag retiré |
| drop `ix_incidents_affected_probes_gin` + `uq_incidents_monitor_open` | index PG-only créés par migration, jamais déclarés | déclarés en `__table_args__` avec `.ddl_if(dialect="postgresql")` |
| `probes.ixp_membership` JSONB→JSON | modèle typé `JSON` nu, colonne en `jsonb` | modèle aligné sur le pattern `_JSON` |
| `monitors.dns_nameservers` | modèle `_JSON` (donc `jsonb` sur PG) mais colonne créée en `json` — seule de son espèce sur `monitors` | `ALTER … TYPE jsonb` |
| `users.oidc_sub` (3 diffs) | base porte à la fois `uq_users_oidc_sub` (UNIQUE) **et** `ix_users_oidc_sub` (non unique, mort) | index droppé, `UniqueConstraint` nommée déclarée |

**Gain concret** : 17 index morts supprimés (16 sur PK + `ix_users_oidc_sub`) — écriture et disque payés pour
rien sur presque toutes les tables. Cinq d'entre eux dataient de la migration B-0 : le flag du mixin
continuait de se propager à chaque nouvelle table.

**Garde-fou permanent** : le job CI `Alembic migrations` se termine désormais par
`python scripts/check_model_drift.py` — sur une base à `head`, `compare_metadata` doit retourner 0. La dérive
ne peut plus se réaccumuler silencieusement.

**Piège méthodologique coûteux** : lancer le comparateur par `python <chemin>/script.py` met le dossier du
script en tête de `sys.path`, pas le repo → `import whatisup` tombe sur la **copie installée** dans l'image
(périmée) et le diff compare le schéma à un modèle qui n'est pas celui du checkout. Résultat : 47 faux diffs,
dont le drop de toutes les tables d'astreinte. Aucune erreur levée. `alembic.ini` s'en protège avec
`prepend_sys_path = .` ; tout script ajouté doit faire l'équivalent.

### Résultats A-1 — partitionnement (livré le 2026-08-06)

**Décision n°1 tranchée : Postgres nu.** Partitionnement déclaratif `PARTITION BY RANGE (checked_at)`,
une partition par mois UTC. Rien ne change pour les self-hosters : même image, même `docker compose up`.

**Migration `e6f7a8b9c0d1` — aucune copie de données.** Le plan prévoyait « table neuve + copie par lots +
swap ». Écarté : sur la prod mesurée ça veut dire 3 Go dupliqués sur disque et une fenêtre où il faut
rejouer les écritures. À la place, l'ancienne table est **renommée et attachée telle quelle** comme
première partition :

    check_results ──rename──► check_results_legacy ──ATTACH──► [MINVALUE, cutover)

Le cutover est le **début du mois suivant**, donc aucun mois n'est coupé en deux. La partition legacy
s'éteint toute seule quand sa plage entière sort de rétention. Le tas n'est touché que par les scans que
PostgreSQL exige : validation du CHECK de plage (qui permet à `ATTACH` de sauter le sien), un scan par FK
clonée, et la construction de la nouvelle PK. **Les 428 Mo de `ix_check_results_monitor_checked` ne sont pas
reconstruits** : l'index parent est créé `ON ONLY` et l'index existant de la partition lui est attaché
(`ALTER INDEX … ATTACH PARTITION`).

| Choix | Pourquoi |
|---|---|
| PK `(id, checked_at)` | Imposé (la clé de partition doit être dans toute contrainte unique). `id` seul n'est plus unique globalement — uuid4 client, aucune FK ne référence la table. Vérifié : `grep ForeignKey("check_results` est vide |
| Partition `DEFAULT` | Une sonde à l'horloge décalée ne doit pas pouvoir casser l'ingestion. Sans elle, `INSERT` échoue et le résultat est perdu ; avec elle il atterrit quelque part de récupérable |
| Drainage de la `DEFAULT` | Corollaire obligatoire : PG **refuse** de créer une partition dont la plage a des lignes coincées dans la `DEFAULT`. Sans drainage, un mois pollué serait à jamais incréable et tout finirait dans la `DEFAULT` |
| Cutoff de drop = rétention **la plus longue** | Une partition mélange les moniteurs. Dropper sur le cutoff global détruirait l'historique d'un moniteur à `data_retention_days = 365`. Le `DELETE` ligne à ligne subsiste pour ce que le drop ne sait pas exprimer |
| Parking des lignes futures (§1b de la migration) | Rien ne garantit que la table s'arrête au cutover (horloge décalée, re-upgrade après downgrade). Sans ce parking la migration **échoue** sur le CHECK de plage — reproduit en réel lors du test de round-trip |

**Deux pièges trouvés en les provoquant :**

1. **`alembic upgrade head` peut mentir.** Interroger la connexion dans `env.py` *avant*
   `context.begin_transaction()` (ce que faisait la première version du filtre `include_object`) ouvre une
   transaction implicite ; alembic considère alors qu'elle ne lui appartient pas et **ne commite jamais**.
   Sortie : toutes les migrations annoncées, exit 0, **base vide**. Aucune erreur. Le filtre est désormais
   paresseux. Consigné dans `CLAUDE.md`.
2. **Les partitions sont des tables réflectées** absentes de `Base.metadata` → sans filtre, `autogenerate`
   propose de **toutes les dropper** et le gate A-0 ter tombe sur un schéma correct. D'où
   `make_alembic_include_object` (filtre `relispartition`), partagé par `env.py` et `check_model_drift.py`.

**Vérifié en réel** (PG 16 jetable, base migrée avec données) : upgrade → downgrade → upgrade avec des
lignes réparties dans legacy / mois futur / `DEFAULT`, round-trip `downgrade base` → `upgrade head`,
`check_model_drift.py` à 0, routage des lignes vers la bonne partition, drainage de la `DEFAULT`, drop
sélectif. 13 tests PG (`tests/test_partitions_pg.py`, nouveau job step dans `Alembic migrations` — seule
CI avec un vrai PostgreSQL) + 21 tests SQLite/unitaires, suite complète verte (995 tests).

**Contrepartie, vérifiée au plan d'exécution** : une requête *non bornée* dans le temps ne peut rien élaguer.
`… WHERE monitor_id = ? ORDER BY checked_at DESC LIMIT 1` (le LATERAL de `fetch_latest_results`) devient un
`Merge Append` sur **toutes** les partitions — index scan sur chacune, donc toujours pas de seq scan, mais
6 sondes d'index au lieu d'une. Négligeable aujourd'hui ; **à surveiller en A-4** : passer la rétention brute
à 13 mois ferait 14 partitions par lookup. Si ça devient sensible, la réponse est de borner la requête
(`checked_at > now() - interval`), pas de revenir en arrière.

**Reste à faire ici** : la purge par drop ne devient réellement O(1) qu'une fois la partition legacy éteinte
(≈ une rétention après la migration). Entre-temps le `DELETE` nightly continue de la traiter.

### Résultats A-2 — rollups horaires (livré le 2026-08-07)

Table `check_rollups_1h` (migration `f7a8b9c0d1e2`) + `services/rollup.py`, boucle de fond
`rollup_builder` (leader, 5 min, `initial_delay=180`). **Rien ne la lit encore** : A-3 rebranche `stats.py`.
La migration crée la table vide ; le backfill de l'historique existant se fait par la boucle, une semaine
par run (~13 runs pour 90 j), donc la migration est instantanée quelle que soit la volumétrie.

**Écart au plan : le grain est `(monitor_id, bucket)`, pas `(monitor_id, probe_id, bucket)`.** Deux raisons,
toutes deux fatales au grain par sonde pour les fonctions que A-3 doit rebrancher :

1. **L'uptime est un consensus cross-probe.** `_aggregate_consensus` groupe par (vue réseau, minute) et
   déclare la minute *up* si **une** sonde l'a vue up. Des compteurs par sonde perdent l'information de
   coïncidence — impossible de savoir si l'échec de A était couvert par le succès de B **dans la même
   minute**. Les fenêtres de consensus sont donc résolues à la construction, et stockées en compteurs
   additifs : sommer 24 lignes horaires redonne exactement le chiffre du jour.
2. **Les percentiles ne se poolent pas.** Le p95 de deux lignes-sonde n'est pas le p95 de leur union ;
   garder le grain par sonde imposerait une approximation sur le seul endpoint (`compute_percentile_timeseries`)
   qui est exact aujourd'hui.

| Exact à toute largeur de fenêtre | Approché |
|---|---|
| `sample_count`, compteurs de statut, fenêtres de consensus (uptime), avg (`rt_sum`/`rt_count`, pas une moyenne de moyennes), min/max | p50/p95/p99 au-delà d'une heure — réagrégés depuis les percentiles horaires |

**Agrégation en Python, pas en SQL.** La règle de consensus n'est pas un GROUP BY, et la suite de tests
tourne sur SQLite, qui n'a ni `date_trunc` ni `percentile_cont`. Deux implémentations dériveraient, et
c'est celle de PostgreSQL — la seule qui tourne en prod — qui serait la non testée. Le coût est borné :
régime stable = une heure de lignes par run (~2 500), backfill découpé par jour. `percentile_cont` est
réimplémenté à l'identique (interpolation linéaire) et **la parité avec le `percentile_cont` de PostgreSQL
est un test**, pas une intention : sans elle, A-3 décalerait toutes les courbes de latence le jour du
rebranchement.

**Deux invariants tenus par la reprise (pas de table de watermark) :**

- reprise = `max(bucket)` + 1 h − `rollup_recompute_hours`. Le rewind rattrape les résultats poussés
  **après la clôture de leur heure** (retry, sonde revenue en ligne) ; le `+1 h` évite de reconstruire
  éternellement le dernier bucket — écrit en premier jet, et attrapé parce que le test s'est mis à boucler
  à l'infini ;
- le départ est **avancé au premier `checked_at` réel**. Sans ce saut, un trou de données plus long que
  `rollup_max_buckets_per_run` (serveur arrêté un mois) fait qu'un run n'écrit rien, donc le watermark
  n'avance pas, donc la boucle ne rattrape **jamais** les lignes récentes.

L'heure en cours n'est jamais agrégée (elle bouge encore) : le temps réel reste servi par le brut, ce qui
est exactement le fallback prévu en A-3. `rebuild_range(db, start, end)` expose la reconstruction forcée
d'une plage (import a posteriori, correction d'un bug d'agrégation).

**Vérifié** : 13 tests SQLite (dont la parité rollup ↔ `compute_daily_history` sur les mêmes données — le
contrat que A-3 va consommer) + 4 tests PG (`tests/test_rollups_pg.py`, ajoutés au step PG du job
`Alembic migrations`) : parité `percentile_cont`, chemin `ON CONFLICT`, lecture à travers les partitions,
reprise sur datetimes *aware* d'asyncpg. Round-trip alembic + `check_model_drift.py` à 0 sur PG 16 jetable.
Suite serveur complète verte (1005 tests).

**Pas de purge** : ~140 k lignes/an à la volumétrie mesurée (quelques dizaines de Mo). Donner aux rollups
leur propre rétention est le sujet de A-4 — survivre à la fenêtre brute est tout l'intérêt de la table.

### Résultats A-3 — rebranchement de `stats.py` (livré le 2026-08-07)

`compute_daily_history`, `compute_daily_history_bulk`, `compute_percentile_timeseries` et
`compute_uptime_in_range` lisent `check_rollups_1h` pour les heures qu'il couvre et `check_results` pour
le reste. **Aucun nouveau knob** : la frontière est `max(bucket) + 1 h`, donc une base sans rollups
(installation neuve, `ROLLUP_ENABLED=false`) retombe intégralement sur le chemin d'avant A-3.

**Le découpage est toujours sur une frontière d'heure**, et c'est ce qui rend le résultat exact : une
fenêtre de consensus (vue réseau, minute) appartient à une seule heure, donc à une seule des deux sources,
donc les compteurs s'additionnent sans double compte ni trou. Trois morceaux de brut possibles autour du
bloc rollup : le sliver de tête (fenêtre qui commence en milieu d'heure), l'heure en cours, et le retard
éventuel du builder — traités par le même accumulateur (`_Aggregate`), qui replie les lignes brutes en
fenêtres minute exactement comme `_aggregate_consensus`.

**Une seule grandeur devient approchée : le p95 d'une fenêtre plus large qu'une heure**, moyenne des p95
horaires pondérée par le nombre d'échantillons. Plutôt que de le taire, `compute_uptime_in_range` renvoie
**`p95_is_estimate`**, remonté tel quel par `GET /monitors/{id}/report` et affiché en `≈` dans l'onglet
SLA. Tout le reste — compteurs, uptime consensus par vue, avg, min, max — est exact.
`compute_percentile_timeseries` n'approxime rien du tout : le grain du rollup **est** celui du bucket, les
heures couvertes sont relues verbatim.

Effets de bord assumés :

- `compute_daily_history` n'est plus qu'un appel à la version bulk (même code, même sortie) — les deux
  avaient divergé en copie/collé.
- `_fetch_check_rows` accepte une borne droite ; c'est ce qui permet de ne scanner que la tranche non
  couverte au lieu de `checked_at >= cutoff` sur toute la fenêtre.
- Le chemin *tout-brut* garde le p95 nearest-rank historique (`_legacy_p95`) : une installation sans
  rollups ne voit **aucun** chiffre bouger le jour de la mise à jour.

**Vérifié** : `tests/test_stats_rollup_parity.py` — chaque figure est calculée deux fois sur les mêmes
données, table de rollups vide puis remplie, et comparée. Le cas qui compte est la fenêtre **mixte**
(heures closes en rollup + heure en cours en brut), c'est-à-dire la production. Un test couvre le builder
**en retard** (run plafonné à 12 buckets) : l'historique doit rester identique, sinon une status page perd
silencieusement ses plus vieilles barres. Suite serveur complète verte (1011 tests ; les 2 échecs
`test_trusted_proxy` sont un artefact du montage Docker qui n'expose pas `nginx/`, reproduits sur `main`
intact).

**Non mesuré ici** : le gain réel sur la prod (le 9,5 s de `compute_daily_history_bulk` mesuré en A-0) —
il demande une base avec les rollups backfillés, donc une observation post-déploiement.

### Résultats A-4 — rétention différenciée (livré le 2026-08-07)

`DATA_RETENTION_DAYS` ne régit plus que `check_results` ; `ROLLUP_RETENTION_MONTHS` (13, `0` = infini)
régit `check_rollups_1h`, purgé par `purge_old_rollups` dans le même job nightly. `DELETE` simple et pas de
partitionnement pour les rollups : à ~140 k lignes/an la table entière pèse moins qu'un jour de brut, la
partitionner coûterait plus qu'elle ne rapporte. Découpe en **mois calendaires** (`_months_before`) et non
`mois × 30 j` — sinon « 13 mois » dérive de deux semaines et une comparaison année/année perd son début.

**Le défaut brut reste 90 j** (le plan disait « cible courte », 7 ou 30 j). Raccourcir supprime le détail
par résultat — `scenario_result`, `tls_audit`, `dns_*`, l'horodatage exact vu par chaque sonde — que les
rollups ne portent pas, donc que rien ne peut reconstruire. C'est un arbitrage par déploiement, pas quelque
chose qu'un `docker compose pull` doit faire dans le dos de l'exploitant au premier purge nocturne. Le knob
est là pour ceux qui le veulent ; A-4 le rend **sûr**, ce qu'il n'était pas.

**L'interlock, que le plan n'avait pas vu.** Une fois l'historique porté par les rollups, un purge du brut
qui dépasse le builder ne compacte plus : il **détruit**. La ligne brute supprimée avant d'avoir été repliée
disparaît des deux tables à la fois — le rollup censé lui survivre n'est jamais écrit. Le cas se produit
exactement quand on se sert du nouveau knob : raccourcir `DATA_RETENTION_DAYS` pendant que le backfill
initial tourne encore. Tous les cutoffs (drop de partition, `DELETE` global, `DELETE` par moniteur) sont
donc plafonnés par `rollup_boundary()` — extrait de `stats.py` vers `rollup.py`, propriétaire de la table,
et désormais lu par les deux côtés pour des raisons opposées : `stats.py` lit *en dessous* (c'est agrégé),
`retention.py` refuse de supprimer *au-dessus* (ça ne l'est pas encore).

Deux échappatoires, parce qu'un garde-fou qui gèle le purge pour toujours remplit le disque :
`ROLLUP_ENABLED=false` (watermark figé, sans signification) et table de rollups vide (builder qui n'a pas
encore écrit son premier bucket — il le fait dans l'intervalle qui suit le boot, bien avant le job de 03:00 ;
si ça persiste, le builder est cassé et le log `retention_no_rollup_floor` le dit).

La rétention **par moniteur** reste brut uniquement. « Je n'ai pas besoin du détail de ce moniteur » n'est
pas « efface son historique d'uptime » — c'est précisément la séparation que A-4 institue.

**Vérifié** : `tests/test_retention_rollups.py` — arithmétique calendaire (mois court, année bissextile,
13 mois > 365 j quel que soit le mois de départ), purge au-delà de l'horizon, rollups qui survivent à une
fenêtre brute de 7 j, et les quatre cas d'interlock (builder en retard, chemin par moniteur, rollups
désactivés, table vide). Les tests de rétention existants passent inchangés : en régime stable la frontière
est à ~`now`, l'interlock ne mord jamais.

**Chantier A terminé.** Reste hors A : la partition legacy s'éteint d'elle-même une rétention après A-1.

### Décision bloquante : TimescaleDB ou Postgres nu ?

| | TimescaleDB | Postgres nu |
|---|---|---|
| Coût de dev | Faible (hypertable + continuous aggregates couvrent A-1→A-3) | Élevé (A-1→A-3 à écrire) |
| Coût d'exploitation | **Change l'image Docker de tous les self-hosters** | Zéro — `docker compose up` inchangé |

**Recommandation : Postgres nu.** Le produit est self-hosted et versionné pour être déployé par des tiers ;
imposer une image Postgres différente casse l'installation existante de tout le monde pour un gain de dev
interne. Le partitionnement déclaratif est standard depuis PG 12.

### Garde-fous

- Tests obligatoires (règle projet) : migration réversible testée, égalité des résultats `stats.py` avant/après
  rebranchement (tests de non-régression sur données synthétiques), purge par drop de partition.
- Attention pattern projet : `func.date_trunc` + asyncpg exige `text("'hour'")` en 1er argument (cf. CLAUDE.md).
- Après toute migration touchant un index : vérifier qu'`autogenerate` ne propose **rien** sur une base à
  `head` (cf. piège A-0 bis ci-dessus). Désormais automatisé — `scripts/check_model_drift.py` en CI (A-0 ter).

---

## Chantier B — On-call & escalade

### Constat (vérifié)

**Existe déjà** — la moitié de la plomberie est là :
- 11 canaux + `dispatch_alert` (`services/alert.py:824`), digest Redis (`:337`, `:519`), silences (`AlertSilence`),
  snooze (`models/incident.py:81-83`).
- `renotify` (`services/renotify.py:19`, tâche `main.py:138`) — relance périodique sur incident ouvert.
- **Plages horaires** : `AlertRule.schedule` (`models/alert.py:146-147`) + `_is_within_business_hours`
  (`services/alert.py:563`) avec timezone, jours, `offhours_suppress`.
- **Ack** : `Incident.acked_at` / `acked_by_id` (`models/incident.py:74-77`).

**Manque** — et c'est le delta le plus visible face à Grafana OnCall / PagerDuty :
| Manque | Détail |
|---|---|
| Rotation d'astreinte | Aucun calendrier, aucune notion de « qui est d'astreinte maintenant », aucun override ponctuel |
| Escalade temporisée | `renotify` relance *le même* canal ; pas de « L1 → L2 après N min sans ack » |
| Ack depuis le canal | L'ack est **UI-only** — pas de callback Slack/Telegram, donc pas d'ack depuis le téléphone |
| Routage personne-centré | Le routage est **canal-centré** (`AlertChannel`), pas dirigé vers une personne |

### Phases

| Phase | Contenu | Effort |
|---|---|---|
| **B-0** | Modèle : `EscalationPolicy` (niveaux ordonnés, délai par niveau, cible) · `OnCallSchedule` (participants, rotation, overrides) · `UserContact` (email / push perso / handle canal). FK `AlertRule.escalation_policy_id`. Décision de rattachement **tranchée** — voir « Prémisses vérifiées B-0 ». | M |
| **B-1** | ✅ **FAIT le 2026-08-09** — voir « Résultats B-1/B-2 ». | M |
| **B-2** | ✅ **FAIT le 2026-08-09** — voir « Résultats B-1/B-2 ». **Écart au plan** : la difficulté n'était pas l'injection mais les maths de rotation (dérive DST) et le comportement quand une cible ne joint personne. | M |
| **B-3** | ✅ **FAIT le 2026-08-09** — voir « Résultats B-3 ». **Écart au plan** : la signature du fournisseur ne suffit pas ; il a fallu un second jeton, signé par nous, liant l'incident au canal. | M |
| **B-4** | ✅ **FAIT le 2026-08-09** — page Astreinte (rotations + politiques + « d'astreinte en ce moment »). **Écart au plan** : pas de calendrier mensuel — la question qu'on se pose est « qui maintenant ? », pas « qui le 17 ». | M |

> **Chantier B terminé le 2026-08-09** : B-0 → B-4 livrés. La pause n'avait introduit aucune dette — le
> modèle B-0 a été repris tel quel, sans retouche.

### Prémisses vérifiées B-0 (2026-07-29) — 2 corrections au constat

**1. `Team` est un vrai mécanisme de scoping, mais `AlertRule` n'en fait pas partie.**
Le RBAC d'équipe est réel et appliqué (`api/deps.py` : `get_user_team_ids`, `assert_can_own`,
`assert_can_assign_team`, hiérarchie `owner > admin > editor > viewer`). Les ressources porteuses d'un
`team_id` nullable sont : `Monitor`, `MonitorGroup`, `AlertChannel`, `MaintenanceWindow`, `MonitorTemplate`.
**`AlertRule` porte uniquement `owner_id`** (NOT NULL depuis la migration `a0b1c2d3e4f5`) — pas de `team_id`.

→ **Décision (n°3 du plan) : rattachement par `Team`, `team_id` nullable, exactement comme `AlertChannel`.**
L'option « globale » du plan n'est en réalité pas ouverte : tout le produit est scopé par tenant, et une
rotation d'astreinte visible de tous serait une fuite cross-tenant par construction (cf. règle absolue
`AlertRule delete / list_events` dans CLAUDE.md). Un utilisateur solo laisse `team_id` à NULL et obtient une
astreinte personnelle — dégradation naturelle, aucun cas particulier à coder.

**2. Le point d'injection est `fire_alerts`, pas `dispatch_alert`.**
`services/incident_alerts.py:40` `fire_alerts()` est le **funnel unique** : tous les chemins y passent
(standard `incident.py:124/145/168/223`, heartbeat `heartbeat.py:70/81`, renotify `renotify.py:75`). C'est là
que les règles sont résolues en `rule.channels`, et donc là que l'escalade doit se greffer.
`dispatch_alert` est un cran trop bas (il ne voit qu'un canal déjà choisi) — le plan B-2 disait « injectée dans
`dispatch_alert` », à corriger.

**3. Conséquence de conception : atteindre une *personne* suppose un canal porteur.**
Livrer à un humain par Telegram/Slack exige le `bot_token` / webhook, qui vit sur un `AlertChannel`. Donc
`UserContact` porte `via_channel_id` (nullable) : NULL pour `email` et `push` (transports déjà autonomes —
`User.email`, `device_tokens`, `push_subscriptions`), renseigné pour les handles de messagerie. Sans ça,
« router vers une personne » serait irréalisable en B-2.

### Résultats B-3 — ack depuis le canal (livré le 2026-08-09)

`POST /callbacks/slack` et `/callbacks/telegram`, plus un bouton « Acquitter » dans les messages Slack et
Telegram. Ce sont **les seuls endpoints mutants non authentifiés du produit**.

**Écart au plan, et c'est le cœur du lot.** Le plan disait « endpoint de callback signé », comme si
vérifier la signature du fournisseur suffisait. Ça ne suffit pas. Une signature Slack prouve que la
requête vient de Slack ; elle ne prouve **pas** de quel incident le bouton parlait — l'identifiant voyage
dans le corps, et le corps ne vaut que ce que vaut celui qui l'a composé.

Concrètement : un attaquant qui exploite sa propre app Slack connaît son propre secret de signature. Il
peut produire une interaction parfaitement signée nommant l'incident **d'un autre tenant**. Un serveur qui
ne vérifierait que la signature l'acquitterait — c'est-à-dire ferait taire la page de quelqu'un d'autre,
la chose la plus dommageable que cet endpoint puisse faire.

D'où un **second jeton, signé par nous**, porté par chaque bouton et liant l'incident au canal sur lequel
il a été annoncé. Deux preuves indépendantes : la signature dit que ça vient bien du fournisseur, notre
jeton dit que ce bouton est un bouton que *nous* avons émis, pour cet incident, sur ce canal. Aucune des
deux ne suffit seule, et l'ordre compte — le jeton est vérifié **en premier**, parce que c'est lui qui
désigne le canal donc le secret contre lequel vérifier la signature.

Autres décisions :
- **Format contraint par Telegram** : `callback_data` plafonne à 64 octets. D'où un encodage binaire
  compact (16+16+4 octets + HMAC tronqué à 10) tenant en 62 caractères, plutôt qu'un jeton lisible ou un
  identifiant court adossé à Redis — ce dernier aurait mis un acquittement derrière la disponibilité de
  Redis.
- **Le jeton n'est pas un porteur de session** : il autorise une action sur un incident, sans identité.
  *Qui* acquitte est résolu séparément, depuis l'identité de messagerie, via `UserContact`. Un jeton fuité
  laisse acquitter un incident dont on était déjà en train d'être prévenu — rien d'autre.
- **Pas de bypass superadmin** sur ce chemin : il n'est pas authentifié, et un superadmin a l'UI.
- **Toutes les erreurs répondent pareil.** Un endpoint non authentifié qui distingue « incident inconnu »
  de « utilisateur inconnu » de « jeton expiré » est un oracle.
- **Jamais « accepter du non signé »** : un canal sans secret n'affiche aucun bouton et refuse tout
  callback. Un bouton mort est pire qu'aucun bouton — l'ingénieur cesse de chercher un autre moyen.

**Ceci termine le chantier B, et avec lui le plan V2.**

### Résultats B-4 — UI d'astreinte (livré le 2026-08-09)

Page `Astreinte` : rotations, politiques d'escalade, et « d'astreinte en ce moment » en tête. Nouvel
endpoint `GET /oncall/schedules/on-call-now`. L'API CRUD de B-0 n'a eu besoin d'aucune retouche.

**Écart au plan** : pas de calendrier mensuel. Le plan disait « calendrier d'astreinte », mais la question
qu'on se pose devant cet écran est « qui est joignable *maintenant* », pas « qui sera d'astreinte le 17 » —
et la seconde se répond déjà en lisant la rotation et ses exceptions. Un calendrier serait du travail
d'affichage pour une question que personne ne pose à 3 h du matin.

**Ce que l'UI dit à voix haute**, dans la continuité du moteur :
- une rotation qui ne désigne personne affiche **« personne d'astreinte »**, jamais une case vide — une
  rotation non couverte ne doit pas se lire comme une rotation couverte ;
- une politique **sans barreau** dit qu'elle retombe sur les canaux de la règle, plutôt que de ressembler
  à une échelle ;
- une astreinte tenue par une **exception ponctuelle** est signalée comme telle : on lit alors le plan ou
  une dérogation au plan, et ce n'est pas la même information.

Détail d'implémentation qui a failli coûter un 422 : `on-call-now` est déclaré **avant** `/{schedule_id}`,
sinon FastAPI matche le littéral comme un UUID — même piège que `/metrics/{monitor_id}/summary`.

### Résultats B-1/B-2 — astreinte et escalade (livré le 2026-08-09)

B-0 avait posé le modèle et l'avait laissé **inerte** : `alert_rules.escalation_policy_id` était stocké et
validé, mais aucun chemin de dispatch ne le lisait. Ce lot l'allume. Migration `f5a6b7c8d9e0`
(`escalation_states`), plus deux services : `oncall.py` (qui est d'astreinte) et `escalation.py`
(l'échelle temporisée).

**Le modèle B-0 a été repris tel quel.** C'est la meilleure nouvelle du lot : une pause de cinq jours sur
un chantier n'a coûté aucune retouche de schéma. Les décisions de B-0 — contrainte CHECK sur le
discriminant de cible, `delay_minutes` compté depuis le barreau précédent, positions contiguës — se sont
toutes révélées être exactement ce dont le moteur avait besoin.

**Où était la difficulté réelle**, une fois de plus pas là où le plan la voyait :

- Le plan disait « résolution injectée dans `fire_alerts` » comme si c'était le morceau. L'injection fait
  six lignes. La difficulté était les **maths de rotation** : `floor((now - start) / period)` dérive d'une
  heure à chaque changement d'heure, et un relais à 09:00 Paris changerait alors de titulaire du mauvais
  côté de la matinée, une fois, à 3 h du matin, sans que personne ne relise le code ensuite. On compte
  donc des **dates calendaires locales** — un jour de 23 h ou 25 h vaut un jour.
- Et le **comportement quand une cible ne joint personne**, que le plan ne mentionnait pas du tout. Trois
  décisions en sont sorties, toutes du même principe : *attacher une politique ne doit jamais rendre une
  alerte plus silencieuse que ne pas en attacher*.
  - Un barreau injoignable est sauté **immédiatement**, sans consommer son délai — sinon une échelle à
    trois barreaux avec un milieu cassé met deux fois plus longtemps à atteindre la personne joignable.
  - Une échelle qui ne joint **personne du tout** retombe sur les canaux de la règle.
  - Une personne sans contact déclaré est jointe sur `User.email` : quelqu'un nommé sur une échelle ne
    doit pas être injoignable faute de ligne en base.

**État persisté, pas en mémoire**, pour la même raison que les fenêtres de digest : un redémarrage en
pleine escalade nocturne ne doit pas laisser un incident coincé entre deux barreaux. `next_fire_at` **est**
l'ordonnanceur, donc le coût de la boucle suit le nombre d'incidents *en escalade*, pas le nombre
d'incidents ouverts.

**Piège rencontré** : un `db.rollback()` nu dans la garde d'unicité annulait toute la session — incident
compris — parce qu'`arm_escalation` est appelé depuis `fire_alerts`. Remplacé par une pré-vérification
explicite plus un `db.begin_nested()` qui borne le repli, la contrainte unique restant la vraie garantie
contre deux réplicas qui arment au même instant.

**Reste du chantier** : B-3 (ack depuis le canal — surface d'attaque nouvelle, signature obligatoire,
rate-limit, scoping `owner_id`) et B-4 (UI : calendrier, éditeur de politique, widget « d'astreinte en ce
moment »).

### Résultats B-0 (livré le 2026-07-29)

Migration `c4d5e6f7a8b9` — **écrite à la main**, pas autogénérée : `autogenerate` propose aussi de
supprimer `audit_logs` et `maintenance_windows` (leurs modèles ne sont pas importés dans
`models/__init__.py`) plus une douzaine de changements d'index et de types JSON. Divergence préexistante,
laissée en l'état, mais **à traiter avant A-1** — le partitionnement sera bien plus pénible avec ce bruit.

Tables : `user_contacts` · `oncall_schedules` + `oncall_participants` + `oncall_overrides` ·
`escalation_policies` + `escalation_levels` · colonne `alert_rules.escalation_policy_id` (FK **SET NULL** :
supprimer une politique doit faire retomber la règle sur ses canaux, jamais la détruire).

Choix de conception notables :
- **Contrainte CHECK en base** sur `escalation_levels` : le discriminant `target_type` doit s'accorder avec la
  FK renseignée. Pas seulement en Pydantic — un niveau qui prétend viser un `schedule` alors que seul
  `target_channel_id` est rempli ne préviendrait **personne, en silence**. C'est le pire mode de défaillance
  possible pour une échelle d'astreinte.
- **`delay_minutes` compté depuis le niveau précédent**, pas depuis l'ouverture de l'incident : insérer un
  échelon au milieu ne décale plus silencieusement tous ceux du dessus.
- **Positions contiguës obligatoires** (0,1,2…) : une échelle qui saute de 0 à 2 se lit comme « il existe un
  niveau 1 » pour qui l'a écrite.
- Index redondants évités dès l'écriture (leçon A-0 bis) : pas d'index sur `oncall_participants.schedule_id`
  (couvert par la PK composite) ni sur `escalation_levels.policy_id` (couvert par la contrainte unique).

Deux gardes de sécurité propres à ce module, testées :
- **Emprunt de porteur** — `via_channel_id` / `target_channel_id` désignent un `AlertChannel` dont la config
  contient un bot token chiffré Fernet. Sans contrôle, n'importe quel compte enverrait des messages via le bot
  d'un autre tenant. → `_assert_can_use_channel`.
- **Paging d'inconnus** — rotations, overrides et niveaux `target_user` désignent un `User`. Sans contrôle,
  configurer une astreinte devient une primitive de spam authentifiée. → `_assert_can_page_users`
  (soi-même ou un membre d'une de ses équipes).

**Bug préexistant corrigé au passage** : `anomaly_zscore_threshold` et `schedule` étaient déclarés sur
`AlertRuleCreate` / `AlertRuleUpdate` mais **jamais assignés** par `POST /alerts/rules` ni
`PATCH /alerts/rules/{id}` — seul l'endpoint matrice les honorait. Les envoyer aux endpoints unitaires les
jetait silencieusement. Même famille que le « sweep toggles orphelins » de la PR #172.

### Pourquoi ce chantier d'abord (à effort égal)

Il ne dépend de rien, réutilise `alert.py` / `renotify.py` / le pattern de tâches de fond tels quels, et comble
le manque fonctionnel le plus cité face à la concurrence. B-0→B-2 seuls livrent déjà l'essentiel de la valeur.

---

## Chantier C — Ingestion push (métriques applicatives)

### Constat (vérifié)

- **Zéro OTLP, zéro OpenTelemetry, zéro StatsD** dans tout le dépôt (grep vide sur serveur + front).
  Le produit ne voit le monde que **de l'extérieur**.
- `CustomMetric` (`models/custom_metric.py:14`) existe mais reste minimal : `monitor_id`, `metric_name`,
  `value`, `unit`, `pushed_at` — pas de dimensions/labels, pas d'histogrammes, table plate.
- Le Health Engine V2 (`services/health.py`, `slo.py`) sait déjà agréger et juger des séries : la couche de
  décision est là, seule la **source** manque.

### Phases

| Phase | Contenu | Effort |
|---|---|---|
| **C-0** | **Cadrer le périmètre : métriques uniquement.** Pas de traces, pas de logs — sinon le scope explose et le produit devient un Datadog qu'on ne peut pas maintenir. | S |
| **C-1** | ✅ **FAIT le 2026-08-09** — voir « Résultats C-1 ». Batch, labels et quotas sur l'endpoint existant. **Écart au plan** : pas d'OTLP ni de nouvelle clé d'ingestion — l'auth par clé existait déjà (correctif C-0), et le vrai coût fut la cardinalité, pas le transport. | M |
| **C-2** | ✅ **FAIT le 2026-08-07** — voir « Résultats C-2 ». `custom_metrics` partitionné mensuellement + rétention `METRICS_RETENTION_DAYS`. **Écart au plan** : pas de rollups (rien n'agrège encore, et le grain dépend des labels de C-1), et pas de labels non plus — ils appartiennent à C-1. | M |
| **C-3** | ✅ **FAIT le 2026-08-09** — voir « Résultats C-3 ». Classement des séries par mouvement autour de l'incident, exposé en API et intégré au post-mortem. **Écart au plan** : calcul à la demande et non « à l'ouverture », et greffe à côté de `diagnostics.py` plutôt que dedans — les deux n'ont pas la même durée de vie. | M |
| **C-4** | ✅ **FAIT le 2026-08-09** — voir « Résultats C-4 ». Conditions `metric_above` / `metric_below` / `metric_absent` + évaluateur de fond. **Écart au plan** : la moitié « graphes » était déjà livrée (`MonitorCustomMetricsPanel.vue`), et le vrai coût n'était pas le prédicat mais l'ancrage sur `Incident` — voir ci-dessous. | M |

### Constat C — corrigé le 2026-08-07 (C-0)

Les prémisses ci-dessus étaient **trop pessimistes**. Vérification faite avant d'écrire une ligne :

- **Un endpoint de push existe déjà** : `POST /api/v1/metrics/{monitor_id}` (`api/v1/metrics.py`), et il
  accepte déjà une **clé API utilisateur** (`wiu_u_*` en `X-Api-Key`, avec portées). Une application peut
  donc pousser aujourd'hui. Ce que C-1 doit apporter n'est pas « l'auth par clé » mais le **batch**, les
  **labels** et le quota : un point par requête à 120/min ne tient pas un agent.
- **L'UI existe déjà en partie** : `MonitorCustomMetricsPanel.vue`, `MetricsDashboard.vue`, un composable.
  La moitié « graphes » de C-4 est faite.
- **Aucune alerte sur métrique poussée** : `alert_conditions.py` ne connaît que ssl_expiry, response_time,
  baseline, anomaly, schema_drift. On peut pousser et regarder ; **rien ne se déclenche jamais**. C'est le
  vrai trou fonctionnel, et il rend la feature inerte.
- **`custom_metrics` n'était purgé nulle part.** Table plate, sans limite, pour la durée de vie du
  déploiement. Défaut actif, pas dette théorique — corrigé en C-2.

D'où l'ordre retenu : **C-2 avant C-1**. Faire le batch et les labels d'abord aurait multiplié le volume
dans une table plate non purgée — précisément le risque énoncé ci-dessous.

### Résultats C-2 — stockage et rétention des métriques (livré le 2026-08-07)

`custom_metrics` devient `PARTITION BY RANGE (pushed_at)`, une partition par mois UTC, PK composite
`(id, pushed_at)` (migration `c2d3e4f5a6b7`). Même bascule que A-1 : la table existante est **renommée et
attachée telle quelle** comme partition `[MINVALUE, cutover)`, donc aucune ligne copiée, index legacy adopté
plutôt que reconstruit. Le faire **maintenant** est le point : après C-1 ce serait une migration de données,
aujourd'hui c'est un rename instantané.

**`core/partitions.py` est généralisé.** Tout passe désormais par une `PartitionSpec(parent, time_column)` —
`CHECK_RESULTS`, `CUSTOM_METRICS`, `ALL_SPECS` — et les fonctions `*_check_result_*` deviennent des wrappers.
Une troisième table partitionnée coûtera une déclaration, pas une copie du module.

**Effet de bord instructif** : `test_partitions_pg.py` neutralisait `list_check_result_partitions` pour
borner la liste des candidats au `DROP` — ce test **fait de vrais DROP TABLE**. Le wrapper ne traversant plus
ce point, la neutralisation ne bornait plus rien et le test a droppé la partition legacy et quatre mois réels
sur la base de test. Corrigé en patchant `list_partitions` (le vrai seam), mais c'est la démonstration qu'un
test peut cesser de protéger sans cesser de s'exécuter.

**Rétention** : `METRICS_RETENTION_DAYS` (90 j, `0` = infini), purgée par `purge_old_metrics` dans le job
nocturne, avec la **rétention par moniteur honorée** — une métrique poussée *est* du détail brut, donc
« garder 2 jours pour ce moniteur » la concerne. Le purge partagé avec le brut est factorisé
(`_purge_partitioned_table`) plutôt que dupliqué : une seconde copie serait un second endroit où oublier
l'override par moniteur. ⚠️ **Changement de comportement à la mise à jour** : la table n'était purgée nulle
part, le premier run nocturne supprime donc ce qui dépasse 90 j. `METRICS_RETENTION_DAYS=0` restaure l'ancien
comportement.

**Écart au plan : pas de rollups pour les métriques.** Le plan disait « partitions + rollups ». Le grain
d'agrégation dépend des labels que C-1 introduira ; le figer avant serait à refaire, et le volume actuel ne
le justifie pas. Pas de rollups ⇒ pas d'interlock de rétention non plus (rien à dépasser).

**Vérifié** : 5 tests SQLite (`test_retention_metrics.py` — fenêtre, `0` = infini, override par moniteur, et
les deux sens de l'étanchéité résultats ↔ métriques) + 13 tests PG (`test_partitions_metrics_pg.py` :
`pg_get_partkeydef` = `RANGE (pushed_at)`, PK portant la clé de partition, index adopté et valide, routage,
DEFAULT, drainage, drop, non-contamination de `check_results`). **Ces tests PG ciblent la généralisation
précisément là où elle pouvait échouer** : un spec qui aurait gardé `checked_at` passerait tous les tests
existants. Round-trip alembic (upgrade → downgrade → upgrade, `relkind` revenu à `r`) + `check_model_drift`
à 0 sur PG 16 jetable. Suite serveur complète verte (1033 tests). CI : le job PG liste les fichiers un par
un — `test_partitions_metrics_pg.py` y a été ajouté, sans quoi il n'aurait jamais tourné.

### Risque principal

Sans A, on stocke des métriques haute cardinalité dans une table plate — exactement l'erreur qu'on corrige.
**Dépendance dure, pas une préférence.**

### Résultats C-3 — corrélation métrique ↔ incident (livré le 2026-08-09)

La thèse de valeur du plan, et elle tient : le blackbox dit *que* c'est cassé, les métriques poussées
disent *ce qui bougeait au même moment*. `GET /incidents/{id}/metric-correlation` classe les séries du
moniteur par ampleur de mouvement, et le post-mortem embarque la même table.

**Deux écarts au plan, tous deux délibérés.**

Le plan disait « à l'ouverture d'un incident, joindre les métriques de la fenêtre ». À l'ouverture il
n'y a précisément rien à corréler — le mouvement intéressant arrive *pendant*. Et contrairement à un
traceroute, dont la valeur est éphémère, les échantillons restent en base : le calcul se fait donc à la
demande, et c'est le **post-mortem qui fige** le verdict, parce que ce document-là est censé survivre à
`METRICS_RETENTION_DAYS`.

Le plan disait aussi « se greffe sur `services/diagnostics.py` ». Le module voisin plutôt que dedans :
`diagnostics.py` orchestre une collecte asynchrone par les sondes via Redis, avec une sémantique
at-most-once et un stockage dédié. La corrélation est une requête synchrone sur des données déjà là.
Les mêmes murs autour de deux choses aussi différentes n'auraient aidé personne.

**Le vrai travail était de savoir quand refuser de répondre.** Classer des séries par écart est facile ;
la valeur de la feature tient à ce qu'elle n'invente pas de chiffre. Un SRE qui lit un post-mortem à 3 h
du matin n'a aucun moyen de distinguer un nombre mesuré d'un nombre fabriqué. D'où trois refus
explicites : série née avec l'incident (`no_baseline` — +∞ ou 100 % seraient des inventions),
échantillonnage insuffisant (`too_few_samples`), et référence à zéro (`zero_baseline` → on rapporte
l'écart absolu, forme honnête de la même observation). Les non-comparables trient en dernier, jamais au
milieu, pour qu'un +20 % mesuré passe toujours devant un mouvement inquantifiable.

Autres décisions :

- **Référence = même durée, immédiatement avant.** Une série à forme journalière est comparée à
  elle-même une heure plus tôt, pas à une moyenne qui aplatit la forme.
- **Fenêtres disjointes** — la référence est bornée en exclusif à `started_at`. Un échantillon pris
  exactement au démarrage appartient à l'incident ; le compter des deux côtés tire la référence vers
  l'incident et rétrécit l'écart qu'on cherche à révéler. Bug attrapé par les tests.
- **Plancher et plafond de fenêtre** (5 min / 6 h). Sur un incident très long on garde la **tête** : ce
  qu'une série faisait pendant que ça cassait est plus informatif que pendant l'astreinte.
- **Corrélation, jamais causalité**, tenu jusqu'à l'UI qui affiche l'avertissement à chaque rendu — un
  tableau classé invite à inférer une cause que ce panneau ne peut pas soutenir.

**Reliquat assumé** : la corrélation ne couvre que les séries du moniteur concerné. C'est aussi ce qui
garantit qu'elle ne traverse jamais un tenant. Corréler entre moniteurs (« l'incident sur l'API
coïncide avec la file de la base ») demanderait un modèle de voisinage explicite — c'est une autre
feature, pas une extension.

### Résultats C-1 — batch, labels et quotas (livré le 2026-08-09)

Migration `e4f5a6b7c8d9`. `POST /metrics/{monitor_id}` accepte désormais un objet **ou** une liste ;
les points portent des `labels` ; deux quotas par moniteur bornent l'ingestion.

**Le plan visait encore le mauvais coût.** Il annonçait « endpoint OTLP/HTTP JSON + clé d'ingestion
dédiée ». Le correctif C-0 avait déjà retiré l'auth du périmètre (une clé API utilisateur poussait
depuis toujours), et OTLP est une grosse surface — imbrication resource/scope/metric, sommes, jauges,
histogrammes, exemplars — pour un problème qu'une liste JSON règle. Arbitrage retenu : liste simple
maintenant, adaptateur OTLP possible plus tard au-dessus du même stockage.

**Le vrai sujet était la cardinalité.** Ajouter des labels transforme un *nom* en *famille de séries*,
et c'est la façon classique de détruire ce genre de table : un seul label à valeurs non bornées — id
d'utilisateur, de requête, URL contenant un id — et le nombre de lignes cesse d'être gouverné par la
fréquence de push pour l'être par ce que l'application observe. Ni le partitionnement (C-2) ni la
rétention n'y peuvent quoi que ce soit ; seul un plafond.

D'où `metric_series`, un registre d'une ligne par série. Il rend le plafond vérifiable par un
`COUNT(*)` sur une petite table au lieu d'un `COUNT(DISTINCT)` sur toutes les partitions — et il gagne
sa place deux fois de plus : l'UI y liste les séries **y compris celles devenues muettes** (ce qu'il
faut pour configurer un `metric_absent`), et le sélecteur de C-4 s'y résout.

Décidé en route, avec les raisons :

- **Les deux quotas refusent en 429**, jamais en silence. Une métrique jetée sans bruit est le pire
  mode de panne d'un produit de supervision : le graphe continue de se tracer, l'alerte continue de ne
  pas partir, et rien nulle part ne dit pourquoi. Même raisonnement que « le silence ne résout jamais »
  en C-4.
- **Un lot est tout-ou-rien.** Accepter la moitié laisserait l'appelant incapable de dire quoi renvoyer,
  et un lot à moitié appliqué est indiscernable d'un lot perdu au scrape suivant.
- **Le compteur de quota ne fail-open pas**, contrairement aux caches d'auth : Redis est ici la source
  de vérité, et un endpoint d'ingestion sans plafond est la façon de remplir la base.
- **Le hash de série trie ses clés.** Sans ça `{a,b}` et `{b,a}` seraient deux séries — la même donnée
  coupée en deux, chacune avec sa courbe et son alerte.
- **Une règle C-4 sans sélecteur surveille toutes les séries du nom** et se déclenche si l'une
  correspond. L'alternative — ne surveiller que la série sans labels — rendrait une alerte existante
  définitivement silencieuse le jour où l'application se met à labelliser.

**Deux pièges rencontrés.** Un `server_default` sur `series_hash` force SQLAlchemy à relire la ligne
(RETURNING) et casse l'insert par lot sur cette table (PK composite + datetime que SQLite rend naïf) —
résolu par un `default` Python calculé depuis la ligne, ce qui rend l'invariant auto-portant. Et les
tests de C-4 fabriquaient leurs points à la main : sans passer par l'ingestion, le registre restait
vide et ils validaient un évaluateur devenu aveugle. Ils passent désormais par `ingest_points`.

**Reliquats assumés** : pas d'OTLP ; pas de rollups de métriques (C-2 les avait reportés en attendant
le grain, qui est maintenant connu — c'est un lot à part) ; le rate-limit slowapi reste par IP, le
quota par moniteur vient en complément, pas en remplacement.

### Résultats C-4 — alertes sur métrique poussée (livré le 2026-08-09)

Migration `d3e4f5a6b7c8`. Trois conditions (`metric_above`, `metric_below`, `metric_absent`) évaluées par
`services/metric_alerts.py`, boucle leader à 60 s.

**Le plan visait la mauvaise moitié du travail.** Il annonçait « UI : graphes + nouvelles conditions
(étendre `alert_conditions.py`) ». Les graphes existaient déjà, et étendre `alert_conditions.py` a coûté
40 lignes de prédicats purs. Le vrai coût était ailleurs : **tout le pipeline d'alerte est ancré sur
`Incident`** — `alert_events.incident_id` est NOT NULL, et ack / snooze / renotify / escalade / silences /
digest / storm en dépendent tous. Une métrique poussée n'a ni `CheckResult` ni incident, donc alerter
dessus veut dire en ouvrir un.

**Et ça entrait en collision frontale avec `uq_incidents_monitor_open`** (un seul incident ouvert par
moniteur). Pas une gêne : un bug de corruption. Un incident métrique ouvert aurait été retrouvé par
`process_check_result` via son `scalar_one_or_none()` comme *l'*incident du moniteur — la panne réelle
n'aurait ouvert aucun incident, envoyé aucun `incident_opened`, et aurait été datée du dépassement de
seuil. Perte silencieuse de la fonction centrale du produit.

Le Health Engine vit avec la même contrainte depuis V2 (`open_incident_from_health` attrape
l'`IntegrityError` et abandonne le second incident), et c'est acceptable **là** : un incident legacy et un
incident SLO affirment tous deux « ce moniteur va mal ». « queue_depth > 1000 » ne l'affirme pas.

D'où `Incident.alert_rule_id` (NULL = disponibilité) et le dédoublement de l'index unique. Coût réel :
l'**audit** des ~15 requêtes qui voulaient dire « ce moniteur est down », toutes passées sous
`IS_AVAILABILITY_INCIDENT`. C'est la partie risquée du lot — un site oublié se manifeste soit par un
`MultipleResultsFound`, soit par du downtime SLA fantôme, soit par une page de statut rouge à tort.

Décidé en route, avec les raisons :

- **Boucle de fond, pas évaluation au push.** Dispatcher = requête HTTP sortante ; la mettre sur le chemin
  d'ingestion laisserait un webhook lent freiner l'agent qui pousse, et le batch de C-1 aggraverait ça.
  L'intervalle est donc la latence d'alerte pire cas, assumée.
- **Le silence ne résout jamais.** Sans échantillon frais, tous les prédicats de seuil répondent False —
  résoudre là-dessus annoncerait le rétablissement au moment où l'on cesse d'observer. Attrapé par un test
  qui contredisait ma propre docstring.
- **`min_duration_seconds` sans état stocké**, en interrogeant les échantillons : le dépassement commence
  après le dernier échantillon qui contredit la condition. Le test naïf (« tout ce qui est dans la dernière
  minute dépasse ») passe dès qu'un seul mauvais point tombe dans une plage vide.
- **Rien de public** : exclu de la page de statut, des mails aux abonnés et du web push.
- **Hors matrice d'alertes** : elle indexe une règle par condition et supprime ce qu'elle ne voit pas ; un
  moniteur a légitimement plusieurs `metric_above`.

**Reliquats assumés** : pas d'événement WebSocket (le dashboard temps réel les lirait comme des pannes) ;
règles limitées à un moniteur (les métriques sont poussées par moniteur) ; pas de labels — ils arrivent
avec C-1 et changeront la sélection de série.

---

## Hors périmètre V2 (backlog assumé)

| Item | Pourquoi hors V2 |
|---|---|
| Remédiation exécutable (runbooks actionnables) | Incrémental ; les runbooks texte existent, les diagnostics aussi |
| Flotte de probes gérée (auto-enrollment, OTA, régions publiques) | Incrémental ; `ProbeGroup` + enrichment ASN déjà là |
| Provider Terraform / CLI | `services/config_sync.py` fait déjà l'export/import IaC — c'est un wrapper, pas un chantier |
| Post-mortem auto-rédigé (synthèse LLM des diagnostics) | Le matériau est collecté ; seule la couche synthèse manque → petit, à faire quand C-3 existe |
| Multi-tenant SaaS (quotas, facturation, self-service) | Vérifié absent. Pertinent **seulement** si l'objectif devient commercial — décision produit, pas technique |
| **Probe en Go** | Gain réel (binaire statique ~15 Mo, pas de runtime Python, RAM/probe divisée) mais gain d'**exploitation**, pas de perf serveur. N'a de sens qu'en scindant : probe Go pour http/tcp/udp/dns/smtp/ping/domain_expiry + image « scenario runner » Python/Playwright séparée (Chromium ancre un runtime lourd de toute façon). Projet à part entière |

---

## Décisions à prendre avant de démarrer

1. ~~**A-1 — TimescaleDB ou Postgres nu ?**~~ **Tranchée le 2026-08-06 : Postgres nu**, livré (voir « Résultats A-1 »).
2. ~~**A-4 — rétention du brut cible** (7 j ? 30 j ?)~~ **Tranchée le 2026-08-07 : le défaut reste 90 j.**
   Raccourcir détruit le détail par résultat que les rollups ne portent pas — c'est un arbitrage par
   déploiement, pas un défaut à imposer. A-4 rend le knob sûr (interlock), il ne le tourne pas.
3. ~~**B-0 — astreinte rattachée à `Team` ou globale ?**~~ **Tranchée le 2026-07-29 : `Team`, `team_id` nullable** (cf. « Prémisses vérifiées B-0 »). L'option globale n'était pas réellement ouverte.
4. **C — on y va, ou le produit reste blackbox ?** C'est la seule vraie question de positionnement des trois.

---

## Suivi

| Chantier | Phase | État | PR |
|---|---|---|---|
| A | A-0 mesure | ✅ 2026-07-28 | — (mesure, pas de code) |
| A | A-0 bis quick wins | ✅ 2026-07-29 | #328 |
| A | A-0 ter resync modèle↔schéma | ✅ 2026-08-05 | #339 |
| A | A-1 partitionnement | ✅ 2026-08-06 | #342 |
| A | A-2 rollups | ✅ 2026-08-07 | #343 |
| A | A-3 rebranchement stats | ✅ 2026-08-07 | — |
| A | A-4 rétention différenciée | ✅ 2026-08-07 | — |
| B | B-0 modèle | ✅ 2026-07-29 | #329 |
| B | B-1 moteur d'escalade | ✅ 2026-08-09 | — |
| B | B-2 résolution d'astreinte | ✅ 2026-08-09 | — |
| B | B-3 ack par canal | ✅ 2026-08-09 | — |
| B | B-4 UI | ✅ 2026-08-09 | — |
| C | C-0 cadrage | ✅ 2026-08-07 | — (prémisses re-vérifiées, voir « Constat C — corrigé ») |
| C | C-1 endpoint d'ingestion | ✅ 2026-08-09 | — |
| C | C-2 stockage | ✅ 2026-08-07 | — |
| C | C-3 corrélation incident | ✅ 2026-08-09 | — |
| C | C-4 UI + conditions d'alerte | ✅ 2026-08-09 | — |

## Règle de mise à jour

Cocher chaque phase à la merge de sa PR, avec le numéro. Toute phase livrée = tests dans la foulée
(serveur / probe / frontend selon la surface) + mise à jour de `FEATURES.md` et de `CLAUDE.md` si un
pattern ou un knob d'exploitation change.
