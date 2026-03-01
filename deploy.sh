#!/usr/bin/env bash
# WhatIsUp — Assistant de déploiement interactif
# Usage : ./deploy.sh
#
# Modes disponibles :
#   1) Serveur + sonde centrale   (tout en local, clé partagée via volume)
#   2) Serveur seul               (ajoutez des sondes distantes plus tard)
#   3) Sonde distante             (enrôlement automatique via l'API centrale)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Couleurs (désactivées si non-TTY) ────────────────────────────────────────
if [[ -t 1 ]]; then
  R='\033[0;31m' G='\033[0;32m' Y='\033[1;33m'
  B='\033[0;34m' C='\033[0;36m' W='\033[1m' X='\033[0m'
else
  R='' G='' Y='' B='' C='' W='' X=''
fi

# ── Fonctions d'affichage ────────────────────────────────────────────────────
log()     { echo -e "  ${B}→${X} $*"; }
ok()      { echo -e "  ${G}✓${X} $*"; }
warn()    { echo -e "  ${Y}⚠${X}  $*"; }
err()     { echo -e "  ${R}✗${X} $*" >&2; }
die()     { err "$*"; exit 1; }
step()    { echo -e "\n${W}── $* ${X}"; }
blank()   { echo; }

# ── Prérequis ────────────────────────────────────────────────────────────────
detect_compose() {
  if docker compose version &>/dev/null 2>&1; then
    DC=(docker compose)
  elif command -v docker-compose &>/dev/null; then
    DC=(docker-compose)
  else
    die "docker compose introuvable. Installez Docker Desktop ou le plugin Compose v2."
  fi
}

check_deps() {
  local missing=()
  command -v docker  &>/dev/null || missing+=("docker")
  command -v curl    &>/dev/null || missing+=("curl")
  command -v python3 &>/dev/null || missing+=("python3")
  [[ ${#missing[@]} -gt 0 ]] && die "Dépendances manquantes : ${missing[*]}"
  docker info &>/dev/null        || die "Docker daemon non disponible. Lancez Docker d'abord."
  detect_compose
}

# ── Génération de secrets ────────────────────────────────────────────────────
gen_hex()    { python3 -c "import secrets; print(secrets.token_hex($1))"; }
gen_fernet() { python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"; }

# ── Saisies interactives ─────────────────────────────────────────────────────
# prompt <variable> <texte> [défaut]
prompt() {
  local _var="$1" _msg="$2" _def="${3-}"
  local _suffix; [[ -n "$_def" ]] && _suffix=" [${_def}]" || _suffix=""
  read -r -p "  ${C}?${X} ${_msg}${_suffix} : " "${_var}" || true
  # Appliquer le défaut si la réponse est vide
  if [[ -z "${!_var}" && -n "$_def" ]]; then
    printf -v "$_var" '%s' "$_def"
  fi
}

# prompt_secret <variable> <texte>
prompt_secret() {
  local _var="$1" _msg="$2"
  read -rs -p "  ${C}?${X} ${_msg} : " "${_var}" || true
  blank
}

# confirm <message> — renvoie 0 si oui, 1 si non
confirm() {
  local _ans
  read -r -p "  ${Y}?${X} $* [o/N] : " _ans || true
  [[ "${_ans,,}" =~ ^(o|oui|y|yes)$ ]]
}

# check_overwrite <fichier> — renvoie 0 si on peut écrire, 1 si on garde l'existant
check_overwrite() {
  local _f="$1"
  if [[ -f "$_f" ]]; then
    warn "Le fichier ${_f} existe déjà."
    confirm "Écraser ?" && return 0
    log "Conservation de ${_f} existant."
    return 1
  fi
  return 0
}

# ── Génération de certificat auto-signé ──────────────────────────────────────
gen_selfsigned_cert() {
  local domain="${1:-localhost}"
  local ssl_dir="$SCRIPT_DIR/nginx/ssl"
  mkdir -p "$ssl_dir"
  if [[ -f "$ssl_dir/cert.pem" && -f "$ssl_dir/key.pem" ]]; then
    ok "Certificats SSL déjà présents dans nginx/ssl/"
    return
  fi
  log "Génération d'un certificat auto-signé pour ${domain}…"
  openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -keyout "$ssl_dir/key.pem" \
    -out    "$ssl_dir/cert.pem" \
    -subj   "/CN=${domain}/O=WhatIsUp/C=FR" \
    -addext "subjectAltName=DNS:${domain},DNS:localhost,IP:127.0.0.1" \
    2>/dev/null
  chmod 600 "$ssl_dir/key.pem"
  ok "Certificats écrits dans nginx/ssl/cert.pem et nginx/ssl/key.pem"
  warn "Certificat auto-signé — votre navigateur affichera un avertissement."
  warn "Remplacez-le par un certificat Let's Encrypt en production."
}

# ── Écriture des fichiers d'environnement ───────────────────────────────────
write_server_env() {
  local _file="${1:-.env}"
  cat > "$_file" <<EOF
# WhatIsUp — généré par deploy.sh le $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# NE PAS VERSIONNER CE FICHIER

# PostgreSQL
POSTGRES_DB=whatisup
POSTGRES_USER=whatisup
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

# Redis
REDIS_PASSWORD=${REDIS_PASSWORD}

# Sécurité API
SECRET_KEY=${SECRET_KEY}
FERNET_KEY=${FERNET_KEY}

# CORS — origines autorisées (JSON array)
CORS_ALLOWED_ORIGINS=["${DOMAIN_URL}"]

# Email (laisser vide pour désactiver les alertes email)
SMTP_HOST=${SMTP_HOST}
SMTP_PORT=${SMTP_PORT}
SMTP_USER=${SMTP_USER}
SMTP_PASSWORD=${SMTP_PASSWORD}
SMTP_FROM=${SMTP_FROM}
EOF
  chmod 600 "$_file"
}

write_probe_env() {
  local _file="${1:-.env.probe}"
  cat > "$_file" <<EOF
# WhatIsUp probe — généré par deploy.sh le $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# NE PAS VERSIONNER CE FICHIER

CENTRAL_API_URL=${CENTRAL_API_URL}
PROBE_API_KEY=${PROBE_API_KEY}
PROBE_NAME=${PROBE_NAME}
PROBE_LOCATION=${PROBE_LOCATION}
HEARTBEAT_INTERVAL=${HEARTBEAT_INTERVAL}
MAX_CONCURRENT_CHECKS=${MAX_CONCURRENT_CHECKS}
LOG_LEVEL=INFO
EOF
  chmod 600 "$_file"
}

# ── Collecte de la configuration serveur ────────────────────────────────────
collect_server_config() {
  step "Configuration du serveur"

  prompt DOMAIN_URL "URL publique (ex: https://monitoring.example.com)" ""
  [[ -z "$DOMAIN_URL" ]] && die "L'URL est obligatoire."
  DOMAIN_URL="${DOMAIN_URL%/}"   # supprimer le / final

  # Extraire le hostname pour le certificat
  DOMAIN_HOST=$(python3 -c "from urllib.parse import urlparse; print(urlparse('${DOMAIN_URL}').hostname)")

  step "Secrets (générés automatiquement)"
  POSTGRES_PASSWORD=$(gen_hex 16)
  REDIS_PASSWORD=$(gen_hex 16)
  SECRET_KEY=$(gen_hex 32)
  FERNET_KEY=$(gen_fernet)
  ok "Secrets cryptographiques générés"

  step "Email (optionnel — laisser vide pour désactiver)"
  prompt SMTP_HOST "Serveur SMTP" ""
  if [[ -n "$SMTP_HOST" ]]; then
    prompt      SMTP_PORT     "Port SMTP"           "587"
    prompt      SMTP_USER     "Utilisateur SMTP"    ""
    prompt_secret SMTP_PASSWORD "Mot de passe SMTP"
    prompt      SMTP_FROM     "Adresse expéditeur"  "noreply@example.com"
  else
    SMTP_PORT=587; SMTP_USER=""; SMTP_PASSWORD=""; SMTP_FROM="noreply@example.com"
  fi

  step "Certificat SSL"
  if [[ -f "$SCRIPT_DIR/nginx/ssl/cert.pem" ]]; then
    ok "Certificat existant détecté."
  elif command -v openssl &>/dev/null; then
    if confirm "Générer un certificat auto-signé pour ${DOMAIN_HOST} ?"; then
      gen_selfsigned_cert "$DOMAIN_HOST"
    else
      warn "Ajoutez manuellement nginx/ssl/cert.pem et nginx/ssl/key.pem avant de démarrer."
    fi
  else
    warn "openssl introuvable. Ajoutez manuellement nginx/ssl/cert.pem et nginx/ssl/key.pem."
  fi
}

# ── Collecte de la configuration sonde ──────────────────────────────────────
collect_probe_config() {
  step "Identité de la sonde"
  local _default_name
  _default_name="probe-$(hostname -s 2>/dev/null || echo '1')"
  prompt PROBE_NAME             "Nom unique de la sonde"       "$_default_name"
  prompt PROBE_LOCATION         "Localisation (ex: Paris, FR)" "Serveur distant"
  prompt HEARTBEAT_INTERVAL     "Intervalle heartbeat (s)"     "30"
  prompt MAX_CONCURRENT_CHECKS  "Checks simultanés max"        "10"
}

# ── Enrôlement automatique via API ───────────────────────────────────────────
enroll_probe() {
  step "Enrôlement de la sonde via l'API centrale"

  prompt CENTRAL_API_URL "URL du serveur central (ex: https://monitoring.example.com)" ""
  [[ -z "$CENTRAL_API_URL" ]] && die "L'URL du serveur central est obligatoire."
  CENTRAL_API_URL="${CENTRAL_API_URL%/}"

  blank
  prompt      ADMIN_EMAIL    "Email administrateur" "admin@local"
  prompt_secret ADMIN_PASSWORD "Mot de passe administrateur"

  log "Authentification sur ${CENTRAL_API_URL}…"

  # Login — OAuth2PasswordRequestForm (application/x-www-form-urlencoded)
  local _login_resp _http_code
  _login_resp=$(curl -sf \
    --connect-timeout 10 \
    --max-time 20 \
    -w '\n__HTTP_CODE__%{http_code}' \
    -X POST "${CENTRAL_API_URL}/api/v1/auth/login" \
    --data-urlencode "username=${ADMIN_EMAIL}" \
    --data-urlencode "password=${ADMIN_PASSWORD}" \
    2>&1) || die "Impossible de joindre le serveur : ${CENTRAL_API_URL}"

  _http_code=$(grep -o '__HTTP_CODE__[0-9]*' <<< "$_login_resp" | cut -d_ -f5)
  _login_resp=$(sed 's/__HTTP_CODE__[0-9]*//' <<< "$_login_resp")

  [[ "$_http_code" == "200" ]] || die "Authentification échouée (HTTP ${_http_code}). Vérifiez vos credentials."

  local _token
  _token=$(python3 -c "
import sys, json
data = json.loads(sys.stdin.read())
print(data['access_token'])
" <<< "$_login_resp" 2>/dev/null) || die "Impossible d'extraire le token de la réponse."

  ok "Authentification réussie"

  # Vérifier que l'utilisateur est superadmin
  local _me_resp
  _me_resp=$(curl -sf \
    --connect-timeout 10 \
    --max-time 10 \
    -H "Authorization: Bearer ${_token}" \
    "${CENTRAL_API_URL}/api/v1/auth/me" 2>/dev/null) || die "Impossible de vérifier les droits."

  local _is_admin
  _is_admin=$(python3 -c "
import sys, json
print(json.loads(sys.stdin.read()).get('is_superadmin', False))
" <<< "$_me_resp" 2>/dev/null) || true

  [[ "$_is_admin" == "True" ]] || die "Le compte ${ADMIN_EMAIL} n'est pas superadmin."

  log "Enregistrement de la sonde '${PROBE_NAME}'…"

  local _reg_resp _reg_code
  _reg_resp=$(curl -sf \
    --connect-timeout 10 \
    --max-time 20 \
    -w '\n__HTTP_CODE__%{http_code}' \
    -X POST "${CENTRAL_API_URL}/api/v1/probes/register" \
    -H "Authorization: Bearer ${_token}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"${PROBE_NAME}\",\"location_name\":\"${PROBE_LOCATION}\"}" \
    2>&1) || die "Requête d'enregistrement échouée."

  _reg_code=$(grep -o '__HTTP_CODE__[0-9]*' <<< "$_reg_resp" | cut -d_ -f5)
  _reg_resp=$(sed 's/__HTTP_CODE__[0-9]*//' <<< "$_reg_resp")

  if [[ "$_reg_code" == "409" ]]; then
    die "Une sonde nommée '${PROBE_NAME}' existe déjà sur ce serveur. Choisissez un autre nom."
  fi
  [[ "$_reg_code" == "201" ]] || die "Enregistrement échoué (HTTP ${_reg_code})."

  PROBE_API_KEY=$(python3 -c "
import sys, json
print(json.loads(sys.stdin.read())['api_key'])
" <<< "$_reg_resp" 2>/dev/null) || die "Impossible d'extraire la clé API."

  ok "Sonde '${PROBE_NAME}' enregistrée avec succès"
}

# ── Scénarios de déploiement ─────────────────────────────────────────────────

# 1) Serveur + sonde centrale ─────────────────────────────────────────────────
deploy_server_with_probe() {
  blank; echo -e "${W}${C}▶ Mode : Serveur + sonde centrale${X}"; blank

  collect_server_config

  step "Sonde centrale"
  prompt PROBE_LOCATION "Localisation de la sonde centrale" "Central Server"

  COMPOSE_FILES=(-f docker-compose.prod.yml -f docker-compose.central-probe.yml)

  if check_overwrite .env; then
    write_server_env .env
    # Ajouter PROBE_LOCATION pour l'override
    echo "PROBE_LOCATION=${PROBE_LOCATION}" >> .env
    ok ".env écrit"
  fi

  step "Construction des images"
  "${DC[@]}" "${COMPOSE_FILES[@]}" --env-file .env build

  step "Démarrage des services"
  "${DC[@]}" "${COMPOSE_FILES[@]}" --env-file .env up -d

  _post_server_info "${COMPOSE_FILES[@]}"
  blank
  log "Sonde centrale : logs disponibles via :"
  log "  docker compose -f docker-compose.prod.yml -f docker-compose.central-probe.yml logs -f probe-central"
}

# 2) Serveur seul ─────────────────────────────────────────────────────────────
deploy_server_only() {
  blank; echo -e "${W}${C}▶ Mode : Serveur seul${X}"; blank

  collect_server_config

  COMPOSE_FILES=(-f docker-compose.prod.yml)

  if check_overwrite .env; then
    write_server_env .env
    ok ".env écrit"
  fi

  step "Construction des images"
  "${DC[@]}" "${COMPOSE_FILES[@]}" --env-file .env build

  step "Démarrage des services"
  "${DC[@]}" "${COMPOSE_FILES[@]}" --env-file .env up -d

  _post_server_info "${COMPOSE_FILES[@]}"
  blank
  log "Pour ajouter une sonde distante plus tard, utilisez :"
  log "  ./deploy.sh  →  option 3"
}

# 3) Sonde distante ───────────────────────────────────────────────────────────
deploy_probe_only() {
  blank; echo -e "${W}${C}▶ Mode : Sonde distante (enrôlement automatique)${X}"; blank

  collect_probe_config
  enroll_probe

  COMPOSE_FILES=(-f docker-compose.probe.yml)

  if check_overwrite .env.probe; then
    write_probe_env .env.probe
    ok ".env.probe écrit"
  fi

  step "Construction de l'image probe"
  "${DC[@]}" "${COMPOSE_FILES[@]}" --env-file .env.probe build

  step "Démarrage de la sonde"
  "${DC[@]}" "${COMPOSE_FILES[@]}" --env-file .env.probe up -d

  blank
  echo -e "  ${G}${W}✓ Sonde '${PROBE_NAME}' démarrée avec succès !${X}"
  blank
  ok "Serveur central : ${CENTRAL_API_URL}"
  ok "Localisation    : ${PROBE_LOCATION}"
  blank
  log "Logs : ${DC[*]} -f docker-compose.probe.yml --env-file .env.probe logs -f probe"
  warn "Conservez .env.probe en lieu sûr — il contient la clé API de la sonde."
}

# ── Affichage post-déploiement serveur ───────────────────────────────────────
_post_server_info() {
  blank
  echo -e "  ${G}${W}✓ Déploiement serveur terminé !${X}"
  blank
  ok "Frontend : ${DOMAIN_URL}"
  ok "API docs : ${DOMAIN_URL}/api/docs"
  blank
  echo -e "  ${W}Credentials admin (premier démarrage) :${X}"
  log "Consultez : ${DC[*]} $* logs server | grep '\\[WhatIsUp\\]'"
  blank
  warn "Actions post-déploiement :"
  warn "  • Changez le mot de passe admin dès la première connexion"
  warn "  • Vérifiez que nginx/ssl/ contient un certificat valide"
  warn "  • Conservez .env en lieu sûr (contient tous les secrets)"
}

# ── Menu principal ────────────────────────────────────────────────────────────
show_menu() {
  echo
  echo -e "${W}${C}"
  echo   "  ╔══════════════════════════════════════════════╗"
  echo   "  ║   WhatIsUp — Assistant de déploiement       ║"
  echo   "  ╚══════════════════════════════════════════════╝"
  echo -e "${X}"
  echo -e "  ${W}1)${X} Serveur + sonde centrale ${C}(recommandé)${X}"
  echo -e "     Lance toute la plateforme (PostgreSQL, Redis, API, frontend, nginx)"
  echo -e "     et enrôle automatiquement une sonde sur cette même machine."
  blank
  echo -e "  ${W}2)${X} Serveur seul"
  echo -e "     Lance la plateforme sans sonde locale."
  echo -e "     Ajoutez des sondes distantes via l'option 3 depuis d'autres serveurs."
  blank
  echo -e "  ${W}3)${X} Sonde distante (enrôlement automatique)"
  echo -e "     Déploie uniquement l'agent probe sur cette machine."
  echo -e "     Se connecte et s'enrôle automatiquement sur un serveur central existant."
  blank
  echo -e "  ${W}q)${X} Quitter"
  blank
}

main() {
  check_deps

  show_menu
  read -r -p "  Votre choix [1/2/3/q] : " choice || true
  blank

  case "${choice:-}" in
    1) deploy_server_with_probe ;;
    2) deploy_server_only ;;
    3) deploy_probe_only ;;
    q|Q) echo "  Annulé."; exit 0 ;;
    *) die "Choix invalide : '${choice}'" ;;
  esac
}

main "$@"
