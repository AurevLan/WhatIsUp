#!/usr/bin/env bash
# Wrapper Docker pour pre-commit.
# Appelé par .githooks/pre-commit (à chaque git commit) et utilisable à la main :
#   tools/pre-commit/run.sh                         # hooks sur les fichiers stagés
#   tools/pre-commit/run.sh run --all-files         # hooks sur tout le repo
#   tools/pre-commit/run.sh autoupdate              # MAJ des révisions de hooks
#   tools/pre-commit/run.sh run --files SECURITY.md # hooks sur un fichier précis
#
# Reconstruit l'image automatiquement si Dockerfile ou .pre-commit-config.yaml ont bougé.
# Le cache des hooks (clones, venvs, binaires) est persisté dans .git/precommit-cache.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE_TAG="whatisup-precommit"
CONFIG_FILE="$REPO_ROOT/.pre-commit-config.yaml"
DOCKERFILE="$REPO_ROOT/tools/pre-commit/Dockerfile"
# In a git worktree .git is a file, not a directory.
# Use the common git dir so the precommit-cache lands in the main .git/.
# We also need to bind-mount the common git dir into Docker so that git inside
# the container can resolve the worktree's gitdir pointer (absolute host path).
GIT_COMMON_DIR="$(git -C "$REPO_ROOT" rev-parse --git-common-dir)"
CACHE_DIR="$GIT_COMMON_DIR/precommit-cache"

# Tag = hash de la config + Dockerfile → rebuild auto à chaque évolution.
CONFIG_HASH=$(sha256sum "$CONFIG_FILE" "$DOCKERFILE" | sha256sum | cut -c1-12)
IMAGE_REF="${IMAGE_TAG}:${CONFIG_HASH}"

if ! docker image inspect "$IMAGE_REF" >/dev/null 2>&1; then
    echo "[pre-commit] Building image $IMAGE_REF (config or Dockerfile changed)…" >&2
    docker build \
        --quiet \
        --tag "$IMAGE_REF" \
        --tag "${IMAGE_TAG}:latest" \
        --file "$DOCKERFILE" \
        "$REPO_ROOT" >&2
fi

# Cache hors volume Docker : bind-mount d'un dossier dans .git/ → permissions hôte natives.
mkdir -p "$CACHE_DIR/ruff" "$CACHE_DIR/tmp"

# Mode hook git par défaut (lance sur les fichiers stagés).
if [[ $# -eq 0 ]]; then
    set -- run --hook-stage commit
fi

USER_ID=$(id -u)
GROUP_ID=$(id -g)

# Extra mounts needed when running from a git worktree: the .git file inside
# the worktree points to an absolute host path (the common git dir). That path
# must be accessible at the same location inside the Docker container so that
# git and pre-commit can resolve the repository.
EXTRA_MOUNTS=()
if [ -f "$REPO_ROOT/.git" ]; then
    EXTRA_MOUNTS+=(--volume "$GIT_COMMON_DIR:$GIT_COMMON_DIR")
fi

# RUFF_CACHE_DIR + TMPDIR redirigés vers le cache → évite que ruff/bandit/etc. créent
# des dossiers root-owned dans l'arbo du repo (ex: probe/.ruff_cache).
exec docker run --rm \
    --user "${USER_ID}:${GROUP_ID}" \
    --volume "$REPO_ROOT:/repo" \
    --volume "$CACHE_DIR:/cache" \
    "${EXTRA_MOUNTS[@]+"${EXTRA_MOUNTS[@]}"}" \
    --workdir /repo \
    --env HOME=/cache \
    --env PRE_COMMIT_HOME=/cache \
    --env RUFF_CACHE_DIR=/cache/ruff \
    --env TMPDIR=/cache/tmp \
    "$IMAGE_REF" \
    "$@"
