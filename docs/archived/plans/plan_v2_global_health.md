# V2 — Global Health Engine (option C)

> **Refonte** du modèle de détection d'incident : la **probe devient capteur**, le **serveur devient juge unique**.
> Effort prévu : **XL** (4-8 semaines, livrable en 6 jalons indépendants).
> Statut : 🟡 en cours · démarré 2026-05-05

## Objectif

Aujourd'hui, chaque probe décide localement si une vérification est `up` / `down` / `slow`, POST le résultat, et le serveur ouvre un incident dès que **K résultats consécutifs `down`** d'**une seule probe** convergent. Conséquences observées :

1. **Bruit en cascade** : N probes décalées → N alertes successives sur la même dégradation globale.
2. **Pas de consensus** : 1 probe défaillante = alerte, alors qu'un quorum aurait disqualifié son verdict.
3. **Pas de signal de perf agrégé** : `response_time_above` se déclenche par probe, jamais "le monitor est globalement lent vu de 6/8 probes".
4. **`Incident.scope=geographic` constaté a posteriori** mais pas exploité comme primitive de décision.

C inverse le pipeline : la probe stocke seulement la mesure brute. Un service serveur agrège en continu (p50/p95/p99 + état up/down par probe), évalue des règles SLO sur fenêtres glissantes, et ouvre **un seul** incident global avec sa portée (`scope`, `affected_probe_ids`) déjà exacte.

Bénéfices au-delà du symptôme initial :

- **Quorum natif** : "≥ 60% des probes voient down" devient configurable.
- **SLO multi-fenêtres** (1 h / 6 h / 24 h) avec **burn-rate** standard SRE — base pour l'error-budget.
- **Détection probe défaillante** : une probe systématiquement divergente du fleet est flaguée comme suspecte (n'incrémente plus de quorum).
- **Cohérence avec `network_verdict`** (V2-02-02) qui repose déjà sur l'agrégation cross-probe.

## Pourquoi pas A ni B

- **A (dédup côté `services/alert.py`)** : patche le symptôme (alertes en rafale) sans corriger la cause (détection per-probe). Devient dette quand C arrive.
- **B (étendre `_correlate_common_cause` à la perf)** : agrège des incidents perf déjà ouverts. On garde le bug "incident ouvert pour 1 probe lente". Demi-pas.
- **C** : refonte du modèle. Coût élevé mais aligné avec le standard du secteur (Datadog, Pingdom, Better Stack) et avec la roadmap V2 (vague Diagnostic Engine).

## Architecture cible

```
┌──────────────────────────────────────────────────────────────────┐
│                          PROBES (capteurs)                        │
│  HTTP/TCP/DNS/Keyword/JSONPath/Scenario                           │
│  Output : CheckResult brut (status, response_time_ms, etc.)       │
│  PAS de décision incident, PAS de seuil local                     │
└─────────────────────────────┬────────────────────────────────────┘
                              │ POST /api/v1/probes/results (inchangé)
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│         INGEST + ROLLING AGGREGATOR (nouveau, server-side)        │
│                                                                   │
│   À chaque CheckResult reçu :                                     │
│     1. persist CheckResult (inchangé)                             │
│     2. update MonitorHealthState[monitor_id] :                    │
│        - probes_state : { probe_id → (last_status, last_at,       │
│                            consecutive_down) }                    │
│        - rolling_p50/p95/p99 sur fenêtre 5 min (T-Digest)         │
│        - rolling_p95 sur fenêtre 1 h / 6 h / 24 h                 │
│        - probe_health_score : flag probes divergentes             │
│     3. evaluate_slo_rules() → décide (no-op | open | resolve)     │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                  INCIDENT DECISION (réécrit)                      │
│                                                                   │
│  Ouverture si :                                                   │
│    • quorum_down  : ≥ Q% probes down sur fenêtre F                │
│    • quorum_slow  : p95 fleet > seuil sur fenêtre F (perf)        │
│    • burn_rate    : SLO burn-rate > B sur fenêtre F (futur)       │
│  Sinon : bruit per-probe → log + WS event "probe_local_signal"    │
│  (visible UI mais ne crée pas d'incident, n'envoie pas d'alerte)  │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
        Incident (existant, enrichi) + AlertEvent + WebSocket
```

**Composants nouveaux** :

| Composant | Rôle | Localisation |
|-----------|------|--------------|
| `MonitorHealthState` | État rolling par monitor (probes, percentiles, SLO) | `models/monitor_health.py` |
| `services/health.py` | Agrégateur ingest-side | nouveau |
| `services/slo.py` | Évaluation SLO + burn-rate | nouveau |
| `core/percentile.py` | T-Digest streaming (lib `tdigest` ou `pytdigest`) | nouveau |

**Composants modifiés** :

| Composant | Changement |
|-----------|-----------|
| `api/v1/probes.py` `report_results` | Après persist, appel `health_service.ingest()` |
| `services/incident.py` | Suppression du décideur per-probe ; expose `open_incident_from_health()` |
| `services/alert.py` | Aucun changement de surface — déclenché par `Incident` comme aujourd'hui |
| `models/alert.py` `AlertRuleType` | Ajout `quorum_down`, `quorum_slow`, `slo_burn_rate` (legacy types restent pour compat) |

## Modèle DB

### Nouvelle table `monitor_health_state`

État courant **par monitor**, mis à jour à chaque ingest. Un seul row par monitor.

```python
class MonitorHealthState(Base):
    __tablename__ = "monitor_health_states"

    monitor_id: Mapped[UUID] = mapped_column(primary_key=True)  # 1-1 avec Monitor
    updated_at: Mapped[datetime]                                 # last ingest

    # Vue par probe — JSONB { probe_id: { last_status, last_at,
    #                                     consecutive_down, response_time_ms } }
    probes_state: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Percentiles fleet, fenêtre 5 min (recalculés à l'ingest)
    p50_5m: Mapped[float | None]
    p95_5m: Mapped[float | None]
    p99_5m: Mapped[float | None]
    sample_count_5m: Mapped[int]

    # T-Digest sérialisés pour fenêtres longues (1 h / 6 h / 24 h)
    tdigest_1h: Mapped[bytes | None]
    tdigest_6h: Mapped[bytes | None]
    tdigest_24h: Mapped[bytes | None]

    # Scope courant calculé
    quorum_down_ratio: Mapped[float]   # 0..1 — fraction probes down sur fenêtre
    current_scope: Mapped[str | None]  # global | geographic | None

    # Score santé probe (flag divergence systématique)
    probe_health: Mapped[dict] = mapped_column(JSONB, default=dict)
    # { probe_id: { divergence_score: 0..1, samples: int, last_eval_at: ts } }
```

**Choix volumétrie** : 1 row par monitor (pas une série temporelle) — tient quel que soit le nombre de monitors. Les T-Digest font ~1 KB chacun → ~3 KB par monitor.

### Nouvelle table `slo_rule`

Règles évaluées en continu par le serveur (remplacent à terme les `AlertRule` perf per-probe).

```python
class SLORule(Base):
    __tablename__ = "slo_rules"

    id: UUID
    monitor_id: UUID  # FK Monitor
    rule_type: str    # quorum_down | quorum_slow | burn_rate

    # quorum_down : ouvre si ≥ quorum_ratio probes down sur window_seconds
    quorum_ratio: float | None     # 0.6 = 60%
    window_seconds: int | None     # 300 = 5 min

    # quorum_slow : ouvre si p95 fleet > p95_threshold_ms sur window_seconds
    p95_threshold_ms: int | None

    # burn_rate (phase 2) : ouvre si burn-rate > burn_factor sur window
    slo_target: float | None       # 0.999 = 99.9% uptime
    burn_factor: float | None      # 14.4 (1 h burn = consume 1 % budget)

    # Paramètres communs
    min_probes: int                # plancher (sinon "indéterminé")
    cooldown_seconds: int          # anti-flapping
    enabled: bool
```

**À noter** : on garde `Monitor.failure_threshold` et `AlertRule` legacy pour compat — désactivés quand un `SLORule` actif existe sur le monitor (toggle dans la phase de migration).

### Champ ajouté à `Incident`

```python
slo_rule_id: Mapped[UUID | None]  # nullable → quel SLO a déclenché ; null pour incidents legacy
trigger_kind: Mapped[str]         # "quorum_down" | "quorum_slow" | "burn_rate" | "legacy"
```

## Pipeline détection

### Ingest (chaque CheckResult)

```python
async def ingest(check_result: CheckResult, db: AsyncSession) -> None:
    # 1. Persist CheckResult (déjà fait dans probes.py)
    # 2. Lock + load MonitorHealthState (FOR UPDATE) — un seul row, faible contention
    state = await db.execute(
        select(MonitorHealthState)
        .where(MonitorHealthState.monitor_id == check_result.monitor_id)
        .with_for_update()
    ).scalar_one_or_none()
    if state is None:
        state = MonitorHealthState(monitor_id=check_result.monitor_id, ...)
        db.add(state)

    # 3. Update probes_state[probe_id]
    update_probe_view(state, check_result)

    # 4. Update T-Digests (5m via samples, 1h/6h/24h via merge)
    update_percentiles(state, check_result)

    # 5. Recompute quorum_down_ratio + current_scope
    recompute_scope(state)

    # 6. Évaluer toutes les SLORule actives du monitor → potentiellement open/resolve
    await evaluate_slos(state, db)
```

**Concurrence** : `SELECT FOR UPDATE` sur la row du monitor sérialise les ingests pour ce monitor sans bloquer les autres. Pour un monitor à 8 probes × interval 60 s = 8 ingests/min — la sérialisation reste largement sous la latence de check.

### Évaluation SLO

```python
async def evaluate_slos(state, db):
    for rule in active_rules_for(state.monitor_id):
        decision = rule.evaluate(state)  # → open | close | hold

        match decision:
            case Open(reason, scope, affected_probes):
                # Idempotent : si un incident open existe déjà pour ce SLO, no-op
                await open_incident_from_health(
                    monitor_id=state.monitor_id,
                    slo_rule_id=rule.id,
                    trigger_kind=rule.rule_type,
                    scope=scope,
                    affected_probes=affected_probes,
                    reason=reason,
                )
            case Close():
                await resolve_incident_for_slo(state.monitor_id, rule.id)
            case Hold():
                pass
```

`open_incident_from_health` réutilise toute la chaîne existante : `_correlate_common_cause`, `services/alert.py.dispatch`, WS publish.

### Détection probe défaillante (phase 4)

À chaque ingest, comparer le verdict de la probe à celui du fleet sur la même fenêtre 5 min :

- Probe dit `down` mais ≥ 70% du fleet dit `up` sur les 10 derniers checks → `divergence_score += 0.1`
- Inverse → `divergence_score += 0.05` (perte de signal moins grave)
- Décay 5%/heure pour effacer les divergences passées.

Une probe avec `divergence_score > 0.5` ne **compte plus** dans le quorum (mais ses checks sont toujours stockés et visibles).

## Migration / compat

**Stratégie** : introduire alongside, opt-in par monitor, puis flip global.

1. **Phase introduction** (M0-M3) — Toutes les nouvelles tables/colonnes créées vides. Le code legacy continue d'ouvrir les incidents. Aucun comportement utilisateur ne change.
2. **Phase coexistence** (M4) — Toggle `monitor.health_engine_enabled` (default `False`). Quand activé : `services/incident.py` legacy court-circuité pour ce monitor, `services/health.py` prend la main. Permet d'A/B tester sur quelques monitors en prod.
3. **Phase migration** (M5) — Script idempotent qui crée une `SLORule` par défaut pour chaque monitor (`quorum_down` 60% sur 90 s = équivalent du legacy K-of-N), bascule `health_engine_enabled=True`. Settings backup-restore : un flag d'env `LEGACY_INCIDENT_ENGINE=true` force le retour au pipeline legacy en cas de problème prod.
4. **Phase nettoyage** (M6+, post-stabilisation) — Suppression du chemin legacy dans `services/incident.py`. AlertRule perf legacy migrées en SLORule.

**Compat AlertRule** : tant que `health_engine_enabled=False` sur un monitor, AlertRule fonctionne comme avant. Quand activé, AlertRule perf (`response_time_above`, `response_time_above_baseline`) sont **désactivées** au profit de SLORule. AlertRule status (`monitor_down`, `tls_grade_below`, `keyword_missing`) restent — elles s'attachent aux Incident émis par le nouveau pipeline.

## Phases livrables

Chaque phase est mergeable, testable en isolation, et n'introduit pas de régression. **Pas de big-bang.**

### M0 — Foundation (semaine 1)

- [ ] Migration Alembic : `monitor_health_states`, `slo_rules`, colonnes `Incident.slo_rule_id` / `trigger_kind`, `Monitor.health_engine_enabled` (default `False`)
- [ ] Modèles SQLAlchemy + schemas Pydantic
- [ ] `core/percentile.py` : wrapper minimal `tdigest` (lib `pytdigest`)
- [ ] `services/health.py` squelette : `ingest()` no-op qui persiste juste l'état
- [ ] Tests : migration round-trip, modèle CRUD

**Critère sortie** : `pytest tests/test_health_state_model.py` vert. Aucun changement comportemental en prod.

### M1 — Ingest agrégateur (semaine 2)

- [ ] `services/health.py` : `ingest()` complet — update `probes_state`, percentiles 5m, T-Digests 1h/6h/24h
- [ ] Hook dans `api/v1/probes.py` `report_results` : appel `await health_service.ingest(cr)` **après** persist (try/except → log si erreur, ne casse pas l'ingest)
- [ ] Endpoint debug `GET /api/v1/monitors/{id}/health-state` (admin-only) pour observer les rolling
- [ ] Tests : 10 CheckResults avec timing varié → percentiles cohérents

**Critère sortie** : Une UI debug montre les p95 fleet pour un monitor instrumenté manuellement. Aucun nouvel incident ouvert (pas de SLO actives).

### M2 — Évaluation SLO `quorum_down` (semaine 3) ✅

- [x] `services/slo.py` : `QuorumDownRule.evaluate(state)` → `Open|Close|Hold`
- [x] `services/incident.py` : `open_incident_from_health()` (réutilise `_open_incident` interne, set `slo_rule_id` et `trigger_kind="quorum_down"`)
- [x] CRUD endpoints `/api/v1/monitors/{id}/slo-rules`
- [x] Frontend : section "SLO" dans `MonitorDetailView` (lecture seule en M2, édition en M4)
- [x] Tests : ingest 10 résultats sur 3 probes → vérifier ouverture quand quorum atteint, fermeture quand revient

**Critère sortie** : sur un monitor de test marqué `health_engine_enabled=True` + une SLORule `quorum_down` 60% / 90 s, le pipeline ouvre/résout un seul incident global même si les probes alternent en décalé. Comparaison avec legacy : 5 alertes legacy → 1 alerte health-engine.

### M3 — Évaluation SLO `quorum_slow` (perf) (semaine 4) ✅

- [x] `QuorumSlowRule.evaluate(state)` : utilise `p95_5m` du fleet
- [x] Tests : injecter probes avec p95 décalés mais convergent vers > seuil → 1 incident perf, pas N
- [x] Frontend : afficher la valeur p95 fleet dans la card d'incident perf

**Critère sortie** : reproduit le scénario utilisateur initial (probes en décalé alertant le même problème global) → 1 seul incident émis. Validation manuelle sur un monitor à p95 dégradé.

### M4 — Coexistence opt-in + UI SLO (semaine 5) ✅

- [x] Toggle `health_engine_enabled` éditable via PATCH `/monitors/{id}` (exposé dans `MonitorOut` + `MonitorUpdate`) et toggle UI dans `MonitorDetailView`
- [x] Quand activé, court-circuit du décideur legacy dans `services/incident.py.process_check_result` (livré en M2)
- [x] Frontend : édition SLORule (CRUD complet) — modal pour create/edit, boutons pause/resume/delete inline
- [x] Section "Quorum & SLO" dans MonitorDetailView avec valeurs courantes vs seuils (livré en M2)
- [x] Tests : monitor legacy + monitor health-engine en parallèle → comportements distincts, pas d'interférence (livré en M2 via `test_health_engine_legacy_coexistence.py`) + nouveau `test_health_engine_toggle_roundtrip` qui vérifie le PATCH/MonitorOut

**Critère sortie** : 5 monitors prod activés en opt-in pendant 7 jours. Comparer volume d'alertes vs legacy. Aucune régression sur les autres monitors.

### M5 — Migration globale + détection probe défaillante (semaines 6-7) ✅

- [x] Script `scripts/migrate_to_health_engine.py` : idempotent, dry-run + apply (paramètres par défaut `quorum_down` 60%/5min/min2 — aucun `failure_threshold` per-monitor n'existe en fait, default cohérent avec le test prod Google)
- [x] Implémentation `probe_health_score` + exclusion du quorum si `divergence_score > 0.5`
- [x] Frontend : badge "probe divergente" dans le panel Quorum & SLO (warning amber, listant chaque probe + score%)
- [x] Flag d'env `LEGACY_INCIDENT_ENGINE=true` pour retour arrière
- [x] Tests : simulation probe défaillante → exclusion du quorum, pas d'incident faussement ouvert

**Critère sortie** : 100% des monitors basculés. Pas plus d'1 alerte par incident global observé sur 7 jours.

### M6 — Burn-rate SLO (futur, hors scope initial)

- [ ] `BurnRateRule` (multi-fenêtres standard SRE : 1h/14.4 + 6h/6)
- [ ] Page Error-Budget dans Frontend
- [ ] Out of scope du chantier C minimum-viable. À ouvrir après M5 stabilisé.

## Tests

**Couverture obligatoire pour chaque phase** (rappel : `feedback_tests_mandatory.md`) :

- `tests/test_health_state_model.py` — CRUD + propriétés
- `tests/test_health_ingest.py` — ingest update probes_state + percentiles
- `tests/test_slo_quorum_down.py` — décide open/close/hold avec scénarios :
  - 1 probe down, autres up → no-op
  - 6/8 probes down dans la fenêtre → open
  - 6/8 down puis 7/8 up → close
  - probes décalées (le bug initial) → 1 seul incident
- `tests/test_slo_quorum_slow.py` — idem pour perf
- `tests/test_health_engine_legacy_coexistence.py` — un monitor legacy + un health-engine
- `tests/test_probe_divergence.py` — probe systématiquement divergente exclue du quorum

**Tests de non-régression** : tous les `tests/test_incident_*.py` actuels doivent passer après M2-M3 (compat avec `health_engine_enabled=False`).

## Risques et mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Latence d'ingest accrue (lock SELECT FOR UPDATE) | Moyenne | Moyen | Bench M1 : si > 50 ms p95, switch vers update optimiste avec retry |
| T-Digest sérialisé volumineux | Faible | Faible | Cap 100 centroïdes/digest → ~1 KB. Compression zstd si besoin |
| AlertRule perf désactivée surprend des users | Élevée | Moyen | Banner UI + email annonce 30 j avant M5. Guide migration. |
| Pipeline cassé en prod après M5 | Faible | Élevé | Flag `LEGACY_INCIDENT_ENGINE=true` rollback en 1 ligne docker-compose |
| Concurrence ingest race condition | Moyenne | Moyen | `SELECT FOR UPDATE` + tests intégration multi-probe simultanés |
| Probe-divergence-score amplifie un bug | Faible | Moyen | Décay 5%/h + plancher `min_probes` dans SLORule |

## Hors scope

- ❌ Refonte de la collecte côté probe (les checkers restent inchangés)
- ❌ Changement du protocole `POST /probes/results` (compat probe existante)
- ❌ Burn-rate SLO complet (M6, après stabilisation)
- ❌ UI Error-Budget
- ❌ Suppression du modèle `AlertRule` legacy (séparé, post-M5)
- ❌ Multi-tenant SLO globaux (ex. SLO d'un team) — phase ultérieure

## Décisions à figer avant M0

- [ ] **Lib T-Digest** : `pytdigest` (pure Python, mainteneur actif) vs `tdigest` (C, plus rapide mais wheel manquante sur arm64). → **Choix `pytdigest`** sauf bench défavorable.
- [ ] **Granularité percentiles longue fenêtre** : merge incrémental (cheap, dérive) vs rebuild horaire depuis CheckResult (plus lourd, exact). → **Merge incrémental** + rebuild quotidien depuis CheckResult pour corriger la dérive.
- [ ] **Scope du toggle initial** : par-monitor (M4) puis global (M5), confirmé.

## Suivi

- ✅ M0 — livré 2026-05-05 (commit 7793a3a)
- ✅ M1 — livré 2026-05-05 (ingest agrégateur 5-min + endpoint debug `/health-state`)
  - Écart vs prévu : T-Digest 1h/6h/24h **non câblé** (pytdigest ne build pas sur Python 3.14).
    M3 devra trancher : `tdigest` pure-Python ou histogramme maison. Les colonnes
    `tdigest_*` restent dans le schema (zéro migration coût).
- ✅ M5 — livré 2026-05-06 (probe divergence + migration script + flag rollback)
  - `services/health.py` : `_update_probe_divergence` — score per-probe avec décroissance 5%/h, weights 0.10 (down divergent) / 0.05 (up divergent), seuil fleet ≥ 70% pour comptabiliser, min 2 peers pour évaluer.
  - `services/slo.py` : `_is_divergent` (seuil 0.5) + `_fresh_probes(exclude_divergent=True)` — la probe reste visible/loggée mais ne compte pas dans le ratio quorum_down ni dans `min_probes`.
  - `core/config.py` : flag `legacy_incident_engine` (env `LEGACY_INCIDENT_ENGINE=true`) — court-circuite la décision health-engine et force le legacy decider, sans changement de code ni migration.
  - `scripts/migrate_to_health_engine.py` : idempotent, dry-run/apply, restriction `--monitor-id` pour rollout progressif. Default rule `quorum_down` 60%/5min/min2 (paramètres validés sur le test Google).
  - Frontend : alerte amber "Probes divergentes (exclues du quorum)" listant chaque probe + score% dans le panel Quorum & SLO.
  - Tests : 4 nouveaux (`test_probe_divergence.py` 3 + `test_legacy_engine_flag.py` 1) — score qui grimpe au-delà du seuil, exclusion intégrée, evaluator pur, flag rollback. 331/331 passent.
- ✅ M4 — livré 2026-05-06 (toggle UI + édition SLO CRUD + validation prod sur Google.fr)
  - `schemas/monitor.py` : `health_engine_enabled` exposé dans `MonitorOut` + `MonitorUpdate` (sans ça le toggle UI ne pouvait pas round-tripper).
  - Frontend : toggle inline dans le panel "Quorum & SLO" + modal d'édition SLORule (rule_type figé en édition, formulaires conditionnels par type, validation côté API). Boutons inline pause/resume/delete par règle.
  - Suppression du hint "read-only M2" + i18n EN/FR (15 nouvelles clés).
  - Tests : `test_health_engine_toggle_roundtrip` (PATCH + MonitorOut). 327/327 passent.
  - **Validation E2E en prod** : monitor `Google` (https://www.google.fr/) — toggle activé via UI/SQL, SLORule `quorum_down` 60%/5min/min2 créée. Test panne synthétique (URL → port 9999) : 1 incident `quorum_down` ouvert (scope geographic, 2/3 probes), `network_verdict=service_down`, durée 91s, résolution auto sur revert URL. Pipeline complet OK.
- ✅ M3 — livré 2026-05-06 (SLO `quorum_slow` perf + UI badge `trigger_kind`)
  - `services/slo.py` : `_evaluate_quorum_slow()` — utilise `state.p95_5m` (recalculé exact à chaque ingest depuis CheckResult), filtre fraîcheur, scope global, affected_probes = toutes les probes fresh.
  - `schemas/incident.py` : `IncidentOut` expose `trigger_kind` + `slo_rule_id` (sans ça, frontend silencieusement borgne — cf. CLAUDE.md).
  - Frontend : badge `trigger_kind` (mono indigo) sur incident card timeline + list, p95 fleet affiché en temps réel quand `trigger_kind === 'quorum_slow'` + i18n EN/FR (`fleet_p95`).
  - Tests : 9 nouveaux (`test_slo_quorum_slow.py`) — pure evaluator (open/close/hold, no_signal, not_enough_probes, no_threshold, stale exclusion) + integration (open/resolve/staggered scenario). 326/326 passent.
  - **Décision T-Digest reportée à M6** : pas nécessaire pour quorum_slow car `p95_5m` est exact (recalculé sur les samples 5min). Les colonnes `tdigest_*` restent dans le schema.
- ✅ M2 — livré 2026-05-06 (SLO `quorum_down` opt-in + panel UI read-only)
  - `services/slo.py` : evaluator pur `Open|Close|Hold`, filtre fraîcheur, scope global vs geographic, cooldown via dernier incident résolu.
  - `services/incident.py` : `open_incident_from_health()` idempotent + `resolve_incident_for_slo()` ; legacy court-circuité quand `monitor.health_engine_enabled=True` ; side-effects (composite, schema-drift, anomaly, auto-pause) factorisés dans `_post_decider_side_effects`.
  - `services/health.py` : `evaluate_slos()` câblé après ingest, no-op si toggle off ou `publish_event` absent.
  - `api/v1/monitors.py` : CRUD `/monitors/{id}/slo-rules` (rate-limit 30/min, RBAC editor).
  - Frontend : panel "Quorum & SLO" read-only dans `MonitorDetailView` (quorum %, p50/p95/p99 5m, liste règles) + i18n EN/FR.
  - Tests : 13 nouveaux (`test_slo_quorum_down.py` 10 + `test_health_engine_legacy_coexistence.py` 3) — 317/317 passent, zéro régression sur `test_incident_*`.
  - Critère sortie atteint : scénario "probes décalées" → 1 seul incident global (vs 5 alertes legacy).
- M3, M4, M5, M6 — à venir

> Ce plan est vivant. Chaque jalon livré coche sa case et résume les écarts vs prévu en bas de section.
