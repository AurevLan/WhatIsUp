# Plan — Vague γ (TLS + DNS + BGP)

> Lot : V2-02-03 TLS chain analyzer + grade A-F · V2-02-04 DNS authoritative consistency · V2-02-05 BGP looking-glass · V2-02-08 TLS fleet dashboard.
> Stratégie : 3 commits Conventional Commits, release `v1.9.0`. Une seule migration Alembic (3 colonnes JSONB sur `check_results`).

## V2-02-03 — TLS chain analyzer + grade A-F (M)

### Données collectées (probe, par check HTTPS)
- `tls_version` : `TLSv1.2` / `TLSv1.3` (`ssock.version()`)
- `cipher_suite` : `(name, version, bits)` (`ssock.cipher()`)
- `cipher_aead` : bool — vérifie présence "GCM"/"CHACHA"/"POLY1305" dans le nom
- `san_list` : `list[str]` (parse via `cryptography.x509.SubjectAlternativeName`)
- `san_match` : bool — hostname ∈ san_list (wildcard `*.` aware)
- `sct_present` : bool (OID `1.3.6.1.4.1.11129.2.4.2` dans extensions cert)
- `signature_algorithm` : `sha256WithRSAEncryption` etc.
- `key_size_bits` : RSA 2048+ / EC 256+
- `is_self_signed` : `subject == issuer`
- `days_remaining` (déjà collecté, T2-05)
- `grade` : `"A+"|"A"|"B"|"C"|"D"|"E"|"F"`

### Logique de grade (simplifiée SSLLabs)
- `F` si self-signed OU SAN mismatch
- `E` si TLS < 1.2
- `D` si cipher non-AEAD ET TLS 1.2
- `C` si pas de SCT (CT log) OU `days_remaining < 14`
- `B` si TLS 1.2 + AEAD + SAN match + SCT
- `A` si TLS 1.3 + AEAD + SAN match + SCT + `days_remaining > 30`
- `A+` si A + key_size ≥ 4096 (RSA) ou ≥ 384 (EC) + `days_remaining > 90`

### Persistance
- `CheckResult.tls_audit` JSONB nullable (migration `t6u7v8w9x0y1`)

### Frontend
- `MonitorRow.vue` : badge grade (A+/A vert, B jaune, C orange, D-F rouge) — visible si check_type http-like
- `MonitorDetailView.vue` : nouvelle carte "TLS audit" avec breakdown des champs

### Alerting
- Nouvelle `AlertCondition.tls_grade_below` avec param `min_grade` ("B" par défaut) — fire si grade < min sur 3 checks consécutifs

### Tests
- 5 pytest probe (`test_tls_audit.py`) : grade matrix par cas
- 2 vitest skipped (build only)

## V2-02-04 — DNS authoritative consistency (S)

### Données collectées
- Pour un check `dns`, résoudre `NS` du domaine via cached `_dns_nameservers`
- Pour chaque NS, query A/AAAA/CNAME/etc. (selon `dns_record_type`) avec `dnspython`
- Comparer réponses : `dns_consistency = {"ns_count", "consistent", "ns_responses": [{ns, values, ttl}], "drift": {...}}`

### Persistance
- `CheckResult.dns_consistency` JSONB nullable (même migration)

### Frontend
- `MonitorDetailView.vue` (DNS check) : encart "DNS consistency" listant les NS + valeurs + warning si drift

### Tests
- 4 pytest probe (`test_dns_consistency.py`)

## V2-02-05 — BGP looking-glass (M)

### Backend
- Nouveau endpoint `GET /api/v1/incidents/{id}/bgp` qui :
  - Vérifie `Incident.network_verdict in {network_partition_asn, network_partition_geo}`
  - Cache Redis 60s sur clé `bgp:lg:{target_ip}`
  - Appelle RIPEstat data API (`https://stat.ripe.net/data/looking-glass/data.json?resource={ip}`)
  - Retourne `{rrcs: [{rrc, peer_asn, as_path}], cached_at}`

### Frontend
- `IncidentDetailView.vue` : bouton "Show BGP path" (visible si verdict `network_partition_*`)
- Modal avec table `peer_asn → AS-path` + couleur par RRC

### Tests
- 3 pytest server (`test_bgp_lookup.py`) : parse, cache hit, fallback timeout

## V2-02-08 — TLS fleet dashboard (S)

### Backend
- Nouveau endpoint `GET /api/v1/tls-fleet` qui agrège `latest_results_subq` filtré sur `tls_audit IS NOT NULL` + JOIN Monitor
- Query params : `grade_below` (A-F), `expires_within_days` (int), `san_mismatch` (bool)
- Réponse : `[{monitor_id, monitor_name, url, grade, expires_at, days_remaining, san_match}]`

### Frontend
- Nouvelle route `/tls-fleet` + entrée sidebar "TLS Fleet"
- `TlsFleetView.vue` : table sortable + filtres + bouton "Export CSV"

### Tests
- 2 pytest server (filter, sort)
- 1 vitest (export format)

## Vérification finale

- `docker run --rm ruff:latest check .` server + probe
- `pytest` server + probe
- Frontend `vite build`
- Migration `t6u7v8w9x0y1` testée up/down
- Stack Docker rebuild + restart
- Push → CI verte → release-please → merge → tag `v1.9.0`

## Hors scope (à reprendre)

- OCSP staple validation (nécessite `cryptography.x509.ocsp` requests sur OCSP responder du CA)
- Chain length / key reuse intermédiaires (Python ssl ne donne pas le chain complet — workaround `openssl s_client` subprocess trop coûteux)
- BGP graph SVG visualisation (table simple suffit en MVP)
