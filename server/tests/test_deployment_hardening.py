"""S6 — durcissement du déploiement par défaut (audit F5, F15).

Les deux findings portaient sur ce que l'installation livrée fait *sans* que
l'opérateur configure quoi que ce soit :

- F5 : `/api/metrics` était ouvert tant que `METRICS_AUTH_TOKEN` restait vide,
  en supposant un filtrage par le reverse proxy — que le `nginx.conf` livré ne
  faisait pas.
- F15 : le mot de passe superadmin du premier boot survivait indéfiniment dans
  un volume monté en lecture dans la sonde, le composant le plus exposé.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from tests.conftest import TEST_PASSWORD
from whatisup import init_data

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Ces deux fichiers vivent hors du paquet serveur : ils sont présents en CI
# (dépôt complet) mais pas quand la suite tourne dans un conteneur où seul
# `server/` est monté. On saute plutôt que de faire échouer à tort.
_repo_files = pytest.mark.skipif(
    not (_REPO_ROOT / "docker-compose.yml").exists(),
    reason="dépôt complet absent (suite lancée sur server/ seul)",
)


# ── F5 — /api/metrics ────────────────────────────────────────────────────────


@pytest.fixture
def metrics_settings(monkeypatch):
    """Substitue les settings vus par la garde `/api/metrics`.

    On ne bascule pas `ENVIRONMENT=production` par l'environnement : `Settings`
    applique alors `validate_production_settings` (CORS, SECRET_KEY…), ce qui
    ferait échouer la construction pour des raisons sans rapport avec le test.
    """

    def _apply(*, is_production: bool, token: str = ""):
        fake = SimpleNamespace(metrics_auth_token=token, is_production=is_production)
        monkeypatch.setattr("whatisup.main.get_settings", lambda: fake)

    return _apply


@pytest.mark.asyncio
async def test_metrics_refused_in_production_without_token(
    client: AsyncClient, metrics_settings
) -> None:
    """Fail-closed : pas de jeton en production = pas de métriques."""
    metrics_settings(is_production=True)

    resp = await client.get("/api/metrics")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_metrics_open_outside_production(client: AsyncClient, metrics_settings) -> None:
    """En dev, l'endpoint reste un outil de mise au point."""
    metrics_settings(is_production=False)

    resp = await client.get("/api/metrics")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_metrics_requires_the_configured_bearer(
    client: AsyncClient, metrics_settings
) -> None:
    metrics_settings(is_production=True, token="s3cret-token")

    assert (await client.get("/api/metrics")).status_code == 401
    assert (
        await client.get("/api/metrics", headers={"Authorization": "Bearer wrong"})
    ).status_code == 401
    ok = await client.get("/api/metrics", headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200


@_repo_files
def test_shipped_nginx_denies_metrics() -> None:
    """Le proxy livré doit refuser l'endpoint, indépendamment du serveur.

    Bloc `= /api/metrics` : nginx fait gagner un match exact sur le préfixe
    `/api/`, donc l'ordre dans le fichier n'a pas d'importance.
    """
    conf = (_REPO_ROOT / "nginx" / "whatisup.conf").read_text()

    assert "location = /api/metrics" in conf
    block = conf.split("location = /api/metrics", 1)[1].split("}", 1)[0]
    assert "deny all;" in block


# ── F15 — secrets de premier boot ────────────────────────────────────────────


@_repo_files
def test_probe_only_mounts_its_own_secret_volume() -> None:
    """La sonde ne doit plus monter `/shared` : il porte le mot de passe admin."""
    compose = (_REPO_ROOT / "docker-compose.yml").read_text()

    probe_local = compose.split("  probe-local:", 1)[1].split("\n  probe:", 1)[0]
    assert "probe_secrets:/probe-secrets:ro" in probe_local
    assert "shared:/shared" not in probe_local


def test_admin_password_file_is_consumed_on_use(tmp_path, monkeypatch) -> None:
    """Suppression appliquée, pas conseillée : le fichier disparaît après usage."""
    pwd_file = tmp_path / "ADMIN_PASSWORD"
    pwd_file.write_text("hunter2")
    monkeypatch.setattr(init_data, "ADMIN_PASSWORD_FILE", str(pwd_file))

    init_data.consume_admin_password_file()

    assert not pwd_file.exists()
    # Idempotent : une seconde connexion ne doit pas lever.
    init_data.consume_admin_password_file()


@pytest.mark.asyncio
async def test_superadmin_login_removes_the_password_file(
    client: AsyncClient, admin_user, tmp_path, monkeypatch
) -> None:
    pwd_file = tmp_path / "ADMIN_PASSWORD"
    pwd_file.write_text("hunter2")
    monkeypatch.setattr(init_data, "ADMIN_PASSWORD_FILE", str(pwd_file))

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": TEST_PASSWORD},
    )

    assert resp.status_code == 200
    assert not pwd_file.exists()


def test_legacy_probe_key_is_migrated_to_the_split_volume(tmp_path, monkeypatch) -> None:
    """Sans cette migration, une mise à jour couperait la sonde locale.

    La clé n'est écrite qu'à la *création* de la sonde et n'est plus
    récupérable ensuite : seul son hash est en base.
    """
    legacy = tmp_path / "shared" / "PROBE_API_KEY"
    legacy.parent.mkdir()
    legacy.write_text("wiu_legacy_key\n")
    new = tmp_path / "probe-secrets" / "PROBE_API_KEY"
    monkeypatch.setattr(init_data, "_LEGACY_PROBE_KEY_FILE", str(legacy))
    monkeypatch.setattr(init_data, "PROBE_KEY_FILE", str(new))

    init_data.migrate_legacy_probe_key()

    assert new.read_text() == "wiu_legacy_key"
    assert not legacy.exists()
    assert oct(os.stat(new).st_mode & 0o777) == "0o600"


def test_migration_leaves_an_already_split_key_alone(tmp_path, monkeypatch) -> None:
    legacy = tmp_path / "shared" / "PROBE_API_KEY"
    legacy.parent.mkdir()
    legacy.write_text("wiu_stale")
    new = tmp_path / "probe-secrets" / "PROBE_API_KEY"
    new.parent.mkdir()
    new.write_text("wiu_current")
    monkeypatch.setattr(init_data, "_LEGACY_PROBE_KEY_FILE", str(legacy))
    monkeypatch.setattr(init_data, "PROBE_KEY_FILE", str(new))

    init_data.migrate_legacy_probe_key()

    assert new.read_text() == "wiu_current"
