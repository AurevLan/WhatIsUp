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
# In a git worktree, .git is a file (not a directory) pointing to the real git
# store. Resolve the common git directory so the cache always lands in the main
# .git/ regardless of whether we are in a worktree or the main working tree.
GIT_COMMON="$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null || echo "$REPO_ROOT/.git")"
CACHE_DIR="$GIT_COMMON/precommit-cache"

# When run from a worktree, .git is a pointer file whose target path is an
# absolute host path. Docker can't follow that reference unless the path exists
# inside the container. If we are in a worktree, also mount the common git dir
# at its exact host path so git can resolve the full gitdir chain.
#
# We also mount the worktree at its real absolute path (instead of /repo) so
# that git's internal paths all resolve consistently inside the container.
EXTRA_DOCKER_OPTS=()
REPO_MOUNT_TARGET="/repo"
if [ -f "$REPO_ROOT/.git" ]; then
    REPO_MOUNT_TARGET="$REPO_ROOT"
    if [ -d "$GIT_COMMON" ]; then
        EXTRA_DOCKER_OPTS+=(--volume "${GIT_COMMON}:${GIT_COMMON}")
    fi
fi

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

# RUFF_CACHE_DIR + TMPDIR redirigés vers le cache → évite que ruff/bandit/etc. créent
# des dossiers root-owned dans l'arbo du repo (ex: probe/.ruff_cache).
exec docker run --rm \
    --user "${USER_ID}:${GROUP_ID}" \
    --volume "$REPO_ROOT:$REPO_MOUNT_TARGET" \
    "${EXTRA_DOCKER_OPTS[@]}" \
    --volume "$CACHE_DIR:/cache" \
    --workdir "$REPO_MOUNT_TARGET" \
    --env HOME=/cache \
    --env PRE_COMMIT_HOME=/cache \
    --env RUFF_CACHE_DIR=/cache/ruff \
    --env TMPDIR=/cache/tmp \
    "$IMAGE_REF" \
    "$@"
