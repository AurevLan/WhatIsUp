#!/usr/bin/env bash
# Setup unique : configure git pour utiliser .githooks/ et build l'image pre-commit.
# Idempotent — peut être relancé sans danger.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if ! command -v docker >/dev/null 2>&1; then
    echo "✗ Docker n'est pas installé ou pas dans le PATH." >&2
    exit 1
fi

# 1. Pointer git sur les hooks versionnés.
git config core.hooksPath .githooks
echo "✓ git config core.hooksPath = .githooks"

# 2. S'assurer que le hook est exécutable (au cas où le clone l'a aplati).
chmod +x .githooks/pre-commit tools/pre-commit/run.sh tools/pre-commit/install.sh
echo "✓ hooks marqués exécutables"

# 3. Build / pull initial de l'image (sera rapide aux runs suivants).
echo "↻ Build initial de l'image pre-commit (peut prendre 1–2 min la première fois)…"
tools/pre-commit/run.sh --version
echo "✓ image pre-commit prête"

echo ""
echo "Tout est prêt. À partir de maintenant, chaque 'git commit' déclenche"
echo "automatiquement les hooks (gitleaks, ruff, bandit, etc.)."
echo ""
echo "Run manuel :"
echo "  tools/pre-commit/run.sh                  # fichiers stagés"
echo "  tools/pre-commit/run.sh run --all-files  # tout le repo"
echo "  tools/pre-commit/run.sh autoupdate       # MAJ des révisions de hooks"
