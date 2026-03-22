#!/usr/bin/env bash
# WhatIsUp — Script de recette dockerisé
# Usage: ./recette.sh [--no-cleanup]
#
# Variables optionnelles:
#   RECETTE_EMAIL    (défaut: recette@test.local)
#   RECETTE_PASSWORD (défaut: RecettePass1!)
#
# Pré-requis: docker compose --env-file .env up -d (stack démarrée)

set -euo pipefail

RECETTE_EMAIL="${RECETTE_EMAIL:-recette@test.local}"
RECETTE_PASSWORD="${RECETTE_PASSWORD:-RecettePass1!}"
NO_CLEANUP="${1:-}"

BOLD="\033[1m"
GREEN="\033[92m"
RED="\033[91m"
CYAN="\033[96m"
DIM="\033[2m"
RESET="\033[0m"

echo -e "\n${BOLD}${CYAN}WhatIsUp — Recette${RESET}"
echo -e "${DIM}Email test : ${RECETTE_EMAIL}${RESET}\n"

# ── 1. Vérifier que la stack tourne ──────────────────────────────────────────
if ! docker compose --env-file .env ps server | grep -q "running\|Up"; then
  echo -e "${RED}Erreur : le serveur n'est pas démarré.${RESET}"
  echo -e "${DIM}Lancez d'abord : docker compose --env-file .env up -d${RESET}"
  exit 1
fi

# ── 2. Créer l'utilisateur de test (superadmin) ───────────────────────────────
echo -e "${CYAN}→ Création de l'utilisateur de test...${RESET}"

HASH=$(docker compose --env-file .env run --rm --no-deps \
  -e DATABASE_URL="postgresql+asyncpg://whatisup:$(grep POSTGRES_PASSWORD .env | cut -d= -f2)@postgres:5432/whatisup" \
  server python -c "
from whatisup.core.security import hash_password
print(hash_password('${RECETTE_PASSWORD}'))
" 2>/dev/null | tail -1)

docker compose --env-file .env exec -T postgres psql -U whatisup -d whatisup -q <<SQL
INSERT INTO users (id, email, username, full_name, hashed_password, is_active, is_superadmin, can_create_monitors, created_at, updated_at)
VALUES (
  gen_random_uuid(),
  '${RECETTE_EMAIL}',
  'recette_admin',
  'Recette Admin',
  '${HASH}',
  true, true, true,
  now(), now()
)
ON CONFLICT (email) DO UPDATE
  SET hashed_password = EXCLUDED.hashed_password,
      is_active = true,
      is_superadmin = true;
SQL

echo -e "${GREEN}✓ Utilisateur de test prêt${RESET}"

# ── 3. Build image recette ───────────────────────────────────────────────────
echo -e "\n${CYAN}→ Build de l'image recette...${RESET}"
docker compose --env-file .env --profile recette build recette --quiet

# ── 4. Lancer les tests ──────────────────────────────────────────────────────
echo -e "\n${CYAN}→ Lancement des tests...${RESET}"
set +e
docker compose --env-file .env --profile recette run --rm \
  -e ADMIN_EMAIL="${RECETTE_EMAIL}" \
  -e ADMIN_PASSWORD="${RECETTE_PASSWORD}" \
  recette
EXIT_CODE=$?
set -e

# ── 5. Nettoyage de l'utilisateur de test ────────────────────────────────────
if [[ "${NO_CLEANUP}" != "--no-cleanup" ]]; then
  echo -e "\n${CYAN}→ Suppression de l'utilisateur de test...${RESET}"
  docker compose --env-file .env exec -T postgres psql -U whatisup -d whatisup -q \
    -c "DELETE FROM users WHERE email = '${RECETTE_EMAIL}';"
  echo -e "${GREEN}✓ Nettoyage terminé${RESET}"
fi

# ── 6. Résultat final ─────────────────────────────────────────────────────────
if [[ $EXIT_CODE -eq 0 ]]; then
  echo -e "\n${GREEN}${BOLD}✓ RECETTE RÉUSSIE${RESET}\n"
else
  echo -e "\n${RED}${BOLD}✗ RECETTE ÉCHOUÉE (code $EXIT_CODE)${RESET}\n"
fi

exit $EXIT_CODE
