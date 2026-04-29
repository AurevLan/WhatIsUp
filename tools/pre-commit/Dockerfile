# Pre-commit runner — image isolée pour exécuter les hooks sans rien installer sur l'hôte.
# Construite et appelée par tools/pre-commit/run.sh, lui-même invoqué par le hook
# .githooks/pre-commit à chaque git commit.
#
# La config consommée est .pre-commit-config.yaml à la racine du repo.
# Toute modification du Dockerfile ou de la config provoque un rebuild auto
# (le tag d'image inclut un hash des deux fichiers).

FROM python:3.12-slim-trixie

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Outils système nécessaires aux hooks :
#   git              : pre-commit lit l'index git
#   golang           : gitleaks est en Go (pre-commit le compile via language: golang)
#   build-essential  : bandit / ruff peuvent compiler des extensions natives
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        git \
        golang \
        build-essential \
        ca-certificates \
        curl \
 && rm -rf /var/lib/apt/lists/*

RUN pip install "pre-commit==4.0.1"

WORKDIR /repo

# Le cache des hooks (clones de repos, venvs Python, binaires Go compilés) est
# persisté dans /cache via un bind-mount sur .git/precommit-cache du repo hôte.
# Permissions = celles du user hôte ; rien à chown.
ENV PRE_COMMIT_HOME=/cache HOME=/cache

ENTRYPOINT ["pre-commit"]
CMD ["run", "--hook-stage", "commit"]
