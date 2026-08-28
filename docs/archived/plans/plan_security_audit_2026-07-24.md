# Plan — corrections audit claude-security (2026-07-24)

Source : `CLAUDE-SECURITY-20260724-114528/CLAUDE-SECURITY-RESULTS.md`
Révision scannée : `acaeda6` — 20 findings (1 HIGH, 14 MEDIUM, 5 LOW).

**SOLDÉ le 2026-07-28** : les 20 findings sont dans `main` (#300 puis #302, #303,
#319, #320, #321, #322, #323). `SECURITY.md` mis à jour dans la foulée — matrice
OWASP (login CSRF SSO, email non vérifié), checklist PR (jetons hors URL), §4
(gate Plumber, seuils de couverture réels 65/40), §10 (actions SHA-pinnées).

## État

| # | Sévérité | Titre court | Lot | Statut |
|---|----------|-------------|-----|--------|
| F1 | HIGH | tag_selector cross-tenant (dispatch) | — | ✅ mergé #300 |
| F3 | MEDIUM | create_rule tag_selector sans access check | S1 | ✅ clos par #300 — voir note ci-dessous |
| F2 | MEDIUM | import_monitors mass-assign group_id | S1 | ✅ mergé #302 |
| F16 | LOW | OIDC link sans email_verified | S1 | ✅ mergé #302 |
| F4 | MEDIUM | XFF spoofable (backend trusted_hosts="*") | S2 | ✅ mergé #303 |
| F13 | MEDIUM | nginx `$proxy_add_x_forwarded_for` (append) | S2 | ✅ mergé #303 |
| F14 | MEDIUM | XFF bout-en-bout → bypass rate-limit login | S2 | ✅ mergé #303 |
| F6 | MEDIUM | bot_token Telegram dans les logs (`str(exc)`) | S3 | ✅ mergé #319 |
| F10 | MEDIUM | variables scenario `secret` dans error_message | S3 | ✅ mergé #319 |
| F18 | LOW | custom_headers en clair (DB + API) | S3 | ✅ mergé #319 |
| F7 | MEDIUM | CRLF injection `report_emails` | S4 | ✅ mergé #320 |
| F17 | LOW | monitor_name non échappé dans l'email HTML | S4 | ✅ mergé #320 |
| F12 | MEDIUM | params numériques non échappés (extension Playwright) | S4 | ✅ mergé #320 |
| F9 | MEDIUM | diagnostics probe sans garde SSRF | S5 | ✅ mergé #321 |
| F20 | LOW | TLS audit / ssl_info re-résolvent le DNS (rebinding) | S5 | ✅ mergé #321 |
| F8 | MEDIUM | `jsonschema.validate` sur l'event loop, sans timeout | S5 | ✅ mergé #321 |
| F19 | LOW | ReDoS body_regex : `wait_for` ne tue pas le thread | S5 | ✅ mergé #321 |
| F5 | MEDIUM | `/api/metrics` non authentifié par défaut | S6 | ✅ mergé #322 |
| F15 | MEDIUM | probe-local monte tout `/shared` (ADMIN_PASSWORD) | S6 | ✅ mergé #322 |
| F11 | MEDIUM | OIDC callback : tokens en fragment, pas de state | S7 | ✅ mergé #323 |

## Lots (1 PR par lot)

- **S1 — cross-tenant / provisioning** ✅ : F3, F2, F16.
  - **F3 : aucun code à écrire.** Le finding proposait deux remèdes ; celui appliqué en #300 (scoper le matching au dispatch) est le bon. L'autre — valider le `tag_selector` à la création — casserait un usage légitime : créer une règle sur un tag avant de posséder un monitor portant ce tag. La couverture est déjà dans `test_alert_tag_cross_tenant.py`.
  - F2 : `assert_can_assign_group` + parsing UUID dans `import_monitors`, sur les deux branches (création **et** upsert par nom). Entrée refusée → erreur par entrée, pas d'abandon de l'import complet.
  - **Bug adjacent trouvé en corrigeant F2** : le chemin d'import stockait les `scenario_variables` `secret: true` en clair (les endpoints create/update les chiffrent via `encrypt_scenario_variables`). Corrigé dans le même lot.
  - F16 : helper `_email_is_verified` (claim absent = non vérifié, tolère `"true"`/`"1"`), appliqué à la liaison par email **et** à l'auto-provisioning. Note de migration dans `UPGRADING.md`.
- **S2 — chaîne de confiance IP** ✅ : un seul défaut (F4/F13/F14), corrigé des deux côtés.
  - nginx écrase `X-Forwarded-For` avec `$remote_addr` sur `/api/` **et** `/ws/`. `/ws/` ne posait aucun `proxy_set_header` : nginx relayait donc l'en-tête du client tel quel, et `ws.py` lit `websocket.client.host` — trou non mentionné par l'audit, trouvé en corrigeant F13.
  - Nouveau réglage `TRUSTED_PROXY_IPS` (défaut : loopback + plages privées) passé à `ProxyHeadersMiddleware`. uvicorn remonte alors la chaîne par la droite et s'arrête au premier hop non listé, au lieu de prendre l'entrée la plus à gauche (celle du client). `*` refusé au démarrage en production.
  - Portée du fix : rate-limits par IP (login inclus), IP d'audit log, métadonnées de session refresh, `client_ip` WebSocket, et l'IP publique observée des probes (`probes.py:214` → enrichissement ASN).
- **S3 — fuites de secrets** ✅ : F6, F10, F18.
  - F6 : le Bot API n'accepte son credential que dans le chemin d'URL, et httpx met l'URL de requête dans `HTTPStatusError` — un simple 401/429 écrivait donc le `bot_token` en clair dans les logs. Helper `telegram._post()` qui lève sur le seul code HTTP, plus un filet `redact_secrets(str(exc), config)` sur les trois sorties d'erreur de canal (`test_channel`, `_flush_digest`, `dispatch_alert`). **`webhook_url` est inclus dans les clés masquées** bien qu'il ne soit pas chiffré : une URL Slack/Discord fuitée suffit à poster à la place de l'intégration.
  - **Chemin dupliqué trouvé en corrigeant F6** : `_flush_digest` réimplémentait l'appel Telegram au lieu de passer par le canal — même fuite, non mentionnée par l'audit. Rebranché sur le helper.
  - F10 : `_substitute_vars` interpole les variables `secret: true` dans les params d'étape, donc une assertion en échec embarquait le mot de passe verbatim dans `error_message` / `scenario_result` — stockés serveur et relisibles via l'API, ce qui annulait le masquage write-only appliqué à ces mêmes valeurs. `_redact_secrets()` sur `error_message`, `final_url`, erreurs d'étape et logs. Seuil de 4 caractères : en dessous, la valeur n'est pas assez distinctive pour être remplacée sans mutiler du texte sans rapport.
  - F18 : chiffrement Fernet des **valeurs** de `custom_headers` (les noms restent en clair — non secrets, la config doit rester inspectable). **Aucune migration** : `decrypt_custom_headers` retombe sur la valeur brute par entrée (`InvalidToken`), donc les lignes antérieures continuent de fonctionner et se rechiffrent à la prochaine écriture. Pas de masquage à la lecture, contrairement aux variables scenario : le formulaire d'édition relit puis resoumet ces valeurs, un masque les effacerait à chaque sauvegarde. Couvert sur les 5 chemins d'écriture/lecture : create, update, import JSON, import/export IaC, heartbeat probe.
- **S4 — injections de contenu** ✅ : F7, F17, F12. Même défaut trois fois : une valeur choisie par un utilisateur recopiée telle quelle dans un format structuré (en-tête SMTP, document HTML, fichier de code) qui lui donne un sens.
  - F7 : validation stricte de `report_emails` au bord (`MonitorGroupCreate/Update`, max 20) **et** au point d'usage. Les deux sont nécessaires : l'import IaC `PUT /config/` prend un `dict[str, Any]` brut et ne passe par aucun schéma — trou non mentionné par l'audit — et les lignes déjà en base restent hostiles. Passage de `MIMEMultipart` (compat32, sérialise le CR/LF brut) à `EmailMessage` (policy moderne, refuse). Sujet aplati : il porte le nom du groupe, et une policy qui lève à l'envoi transformerait un nom hostile en blocage de tous les rapports.
  - Helper partagé `core/validators.py` : `schemas/alert.py` réimplémentait la même regex, elle y est maintenant réutilisée.
  - F17 : `html.escape()` sur `monitor_name`, `check_type` et la portée dans le corps HTML des alertes. **Même défaut dans le rapport SLA** (`reports.py` interpole nom de groupe, nom et type de monitor) — non signalé par l'audit, corrigé aussi. Sujet du canal email aplati pour la même raison qu'en F7.
  - F12 : `_num()` pour les positions **non entourées de guillemets** (`x`, `y`, `ms`) — les seules que `_escJs` ne peut pas protéger, puisqu'il protège l'intérieur des littéraux. Deux points adjacents durcis : le type de step inconnu était interpolé dans un commentaire (un saut de ligne en sort), et `_escJs` ne neutralisait pas les sauts de ligne (littéral cassé).
  - **Constaté sans corriger** (hors périmètre) : `create_group` ignore silencieusement `report_schedule`, `report_emails` et les champs de branding acceptés par `MonitorGroupCreate` — seul le PATCH les persiste.
- **S5 — probe : SSRF + DoS** ✅ : F9, F20, F8, F19. La sonde exécute de la configuration écrite par un tenant, depuis l'intérieur du réseau de supervision.
  - F9 : `run_collection` résout et valide la cible **une fois** (`_ssrf_resolve_pinned_sync`), puis épingle chaque collecteur sur l'IP obtenue — traceroute/ping reçoivent l'IP (`-n` était déjà là, le nom n'apportait rien), `openssl -connect ip:port -servername host`, `curl --resolve host:port:ip` (URL, Host et SNI inchangés). Seul `dig +trace` garde le nom : il interroge des résolveurs, il ne se connecte pas à la cible. Fail-closed : une résolution qui échoue annule la collecte.
  - F20 : même épinglage pour `_extract_tls_audit_sync` et `_extract_ssl_info_sync`, qui rouvraient une connexion avec leur propre résolution après le check HTTP déjà épinglé. Un blocage est loggé explicitement : sans ça, un audit TLS absent ressemble à une panne réseau.
  - F19 : le vrai défaut n'était pas l'absence de timeout mais son inefficacité — `asyncio.wait_for` annule la coroutine qui attend, pas le thread qui calcule. Passage au moteur `regex` avec `timeout=`, vérifié *pendant* le parcours, donc le thread est réellement rendu. **Découverte au test** : `^(a+)+$`, l'exemple canonique de ReDoS, est optimisé par `regex` et répond instantanément — il ne prouve rien. C'est l'alternance dupliquée (`^(a|aa)+$`) qui explose ; le test utilise celle-là.
  - F8 : `jsonschema.validate` tournait à même la boucle. Déporté dans le même pool isolé, avec `pattern` et `patternProperties` routés vers le moteur borné (jsonschema les évalue avec `re` en interne) et une échéance partagée par toute la validation — sinon N motifs × T secondes se cumulent. La classe de validateur est étendue à partir de celle que `jsonschema` aurait choisie, donc le draft déclaré par l'utilisateur reste respecté.
  - **Pool de threads isolé** (transverse F19/F8) : ce travail CPU non fiable ne tourne plus dans l'executor par défaut, celui du DNS, de l'épinglage SSRF et de l'extraction TLS. C'est ce qui borne l'impact au tenant fautif.
  - Versant serveur : `json_schema` plafonné à 64 Ko à l'entrée — sinon le monitor était accepté puis échouait à chaque cycle côté sonde.
  - Nouvelle dépendance sonde : `regex` (sur-ensemble de `re` en mode V0, les motifs existants sont inchangés).
- **S6 — déploiement** ✅ : F5, F15. Les deux portaient sur ce que l'installation livrée fait *sans* configuration de l'opérateur.
  - F5 : les deux remèdes proposés, pas un seul. `nginx.conf` refuse `/api/metrics` (bloc `= `, qui gagne sur le préfixe `/api/` quel que soit l'ordre), **et** le serveur répond 401 en production tant que `METRICS_AUTH_TOKEN` est vide. Hors production l'endpoint reste ouvert : c'est un outil de mise au point. Un scraper légitime tourne sur le réseau Docker et interroge `server:8000` directement, sans passer par le proxy — il lui suffit d'un jeton. **Changement de comportement documenté dans UPGRADING.md.**
  - F15 : nouveau volume `probe_secrets` (clé d'API seule), seul volume monté dans `probe-local` ; `shared` (mot de passe superadmin) redevient serveur-only. **Piège d'upgrade** : la clé n'est écrite qu'à la *création* de la sonde et n'est plus récupérable ensuite (seul son hash est en base), donc un nouveau volume vide couperait la sonde locale des installations existantes → migration automatique `/shared/PROBE_API_KEY` → `/probe-secrets/` au démarrage du serveur. Le `Dockerfile` crée les deux points de montage avec le bon propriétaire, sinon le process non-root ne peut pas écrire dans le volume.
  - Second volet de F15, celui que l'audit soulignait : la suppression d'`ADMIN_PASSWORD` était *conseillée*, jamais appliquée. Elle l'est désormais à la première connexion superadmin réussie (les deux chemins : avec et sans MFA) — c'est le moment où l'opérateur a prouvé qu'il avait lu le fichier.
- **S7 — OIDC login CSRF** ✅ : F11. Les deux remèdes proposés, pas un seul — ils ne tiennent pas séparément.
  - **Prémisse vérifiée, et le finding sous-estimait la portée** : le `state` existait bien (PKCE inclus), mais il ne prouvait que « ce flux a été initié par ce serveur », jamais « par ce navigateur ». Le vrai défaut n'est donc pas l'absence de state, c'est que la paire de jetons voyageait dans une URL : un attaquant terminait *sa* connexion SSO, copiait le fragment, et envoyait à la victime un `/oidc-callback#access_token=…` — le navigateur de la victime ouvrait la session de l'attaquant (login CSRF / fixation), et tout ce qu'elle saisissait ensuite atterrissait dans ce compte. Le fragment protégeait des logs serveur et du Referer, pas de la victime.
  - Cookie nonce `wiu_oidc_nonce` (HttpOnly, `Path=/api/v1/auth/oidc`, TTL 5 min) posé avant la redirection vers l'IdP, exigé au retour. Redis ne stocke que son empreinte SHA-256, aux côtés du `code_verifier` — d'où le passage de l'entrée d'état d'une chaîne brute à du JSON.
  - Callback → `#code=<opaque>` à usage unique (TTL 60 s) au lieu des jetons, échangé contre la paire via `POST /auth/oidc/exchange`, échange lui-même lié au **même cookie**. Le code seul ne suffirait pas : rien n'empêche l'attaquant de fabriquer un lien portant son propre code frais. C'est le cookie qui ferme la porte, aux deux étapes ; le code enlève simplement toute valeur au fragment.
  - **Effet de bord bénéfique** : les jetons étant émis à l'échange, `store_refresh_session` enregistre l'UA/IP du navigateur qui ouvre réellement la session, et non ceux de la requête de callback.
  - **Point non signalé par l'audit, traité ici** : `SameSite=lax` casse silencieusement les déploiements où le front est sur un hôte distinct de l'API — l'échange y est cross-site, le cookie ne partirait jamais et *toute* connexion SSO échouerait. Bascule automatique en `SameSite=none; Secure` dans ce cas (HTTPS déjà imposé en production). Ce n'est pas SameSite qui protège ici : le nonce est imprévisible et HttpOnly, c'est sa valeur qui est vérifiée.
  - Entrées d'état antérieures à la mise à jour (verifier brut, sans nonce) : refusées plutôt qu'acceptées sans liaison — fenêtre de 5 min, l'utilisateur relance la connexion. Documenté dans `UPGRADING.md`.
  - Tests : `server/tests/test_security_oidc_handoff.py` (11 cas : pose du cookie, déploiement à origines séparées, callback sans/avec mauvais cookie, format d'état hérité, absence de jeton dans l'URL, échange sans cookie qui consomme quand même le code, rejeu, compte désactivé) + `frontend/tests/oidcCallback.test.js` (jetons plantés dans le fragment ignorés, échange credentialed, échec sans stockage). `test_oidc.py` remis à jour sur le nouveau flux.

## Règles de travail

- 1 lot = 1 branche = 1 PR, commits `fix(security):` (→ PATCH).
- Chaque correctif = test de régression dans la foulée (`server/tests/test_security_*.py`, probe, vitest).
- Vérifier les prémisses de chaque finding avant de coder (leçon état des lieux 2026-07-21).
- Mettre à jour ce tableau + `SECURITY.md` à chaque lot mergé.

## Leçons de la vague de merge (2026-07-28)

- **Un test auto-mergé n'est pas un test qui passe.** S1 et S7 modifiaient tous
  deux `test_oidc.py` ; git a fusionné sans conflit, mais les 3 cas F16 de S1
  semaient un état Redis au format pré-S7 et n'envoyaient pas le cookie nonce :
  le callback répondait `invalid_state` avant d'atteindre le contrôle
  `email_verified`, et un cas attendait encore `#access_token=` dans le
  fragment. Les tests passaient donc « pour la mauvaise raison » jusqu'à ce que
  la CI les casse. Sur deux branches qui touchent le même flux, relire les
  fichiers de test fusionnés sans conflit — c'est là que la fusion silencieuse
  fait le plus de dégâts.
- **Trois conflits sur sept rebases, tous des ajouts au même endroit** :
  `SECURITY.md` (checklist), `CLAUDE.md`, `UPGRADING.md`, `schemas/monitor.py`,
  `import_export.py`. Aucun recouvrement sémantique — les deux côtés étaient à
  conserver à chaque fois. Coût réel du découpage en 7 lots : faible.
- **CodeQL classe par le nom de l'identifiant.** Interpoler `PROBE_KEY_FILE`
  (un chemin, construit de littéraux) dans un `print` a déclenché
  `py/clear-text-logging-sensitive-data` en HIGH et bloqué S6. Chemin écrit en
  toutes lettres + commentaire, plutôt qu'une suppression inline.
- **Ordre de merge = ordre des lots**, en rebasant systématiquement sur `main`
  avant chaque merge : c'est ce qui a fait apparaître le trou de `test_oidc.py`
  avant le merge, et non après.
