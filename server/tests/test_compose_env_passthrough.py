"""`docker-compose.yml` doit transmettre au serveur tout réglage documenté.

Le piège vécu (v1.28.0) : `PUBLIC_BASE_URL` était documenté dans
`.env.example`, lu par `Settings`, consommé par le flux Atom et les e-mails
d'abonnement… et **absent du bloc `environment:` du service `server`**. Un
exploitant pouvait le renseigner dans son `.env` sans effet : le conteneur ne
le recevait jamais, le serveur retombait sur `http://localhost:5173`, et la
page de statut publiait des liens pointant vers la machine du visiteur.

Rien n'échouait. C'est exactement la forme de panne que ce test attrape : le
réglage existe des deux côtés, seul le fil entre les deux manque.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO_ROOT / "docker-compose.yml"
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"
_CONFIG = _REPO_ROOT / "server" / "whatisup" / "core" / "config.py"

# Réglages volontairement non transmis au service `server`, avec la raison.
# Toute entrée ici est une dérogation assumée, pas un oubli toléré.
_NOT_FOR_SERVER: dict[str, str] = {}


def _documented_env_keys() -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", _ENV_EXAMPLE.read_text(), re.M))


def _settings_field_names() -> set[str]:
    """Champs déclarés sur `Settings`, en NOM_D_ENV (pydantic-settings mappe
    `public_base_url` sur `PUBLIC_BASE_URL`)."""
    body = _CONFIG.read_text()
    return {f.upper() for f in re.findall(r"^\s{4}([a-z][a-z0-9_]*)\s*:", body, re.M)}


def _server_service_env() -> set[str]:
    """Variables que le service `server` reçoit — clés du bloc `environment:`
    et variables `${...}` interpolées dedans (une clé peut être renommée en
    chemin, ex. `DATABASE_URL` composée depuis `POSTGRES_PASSWORD`)."""
    compose = _COMPOSE.read_text()
    block = re.search(r"\n  server:\n(.*?)\n  [a-z]", compose, re.S)
    assert block is not None, "service `server` introuvable dans docker-compose.yml"
    body = block.group(1)
    declared = set(re.findall(r"^\s{6}([A-Z][A-Z0-9_]*):", body, re.M))
    interpolated = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", body))
    return declared | interpolated


def test_documented_server_settings_reach_the_container() -> None:
    candidates = _documented_env_keys() & _settings_field_names()
    assert candidates, "aucun réglage croisé — les regex ont cessé de mordre"

    missing = sorted(candidates - _server_service_env() - set(_NOT_FOR_SERVER))
    assert not missing, (
        "réglages documentés dans .env.example et lus par Settings, mais jamais "
        f"transmis au service `server` de docker-compose.yml : {missing}. "
        "Les renseigner dans un .env n'aurait aucun effet. Ajouter la ligne "
        "`NOM: ${NOM:-...}` au bloc `environment:`, ou déclarer la dérogation "
        "dans _NOT_FOR_SERVER avec sa raison."
    )


def test_public_base_url_is_wired() -> None:
    """Le cas qui a motivé le test, épinglé nommément : une refonte des regex
    ci-dessus ne doit pas pouvoir le laisser repasser en silence."""
    assert "PUBLIC_BASE_URL" in _server_service_env()


def test_blank_public_base_url_falls_back_to_the_default(monkeypatch) -> None:
    """`${PUBLIC_BASE_URL:-}` transmet une chaîne **vide** quand l'exploitant
    n'a rien réglé. Sans garde-fou elle écraserait le défaut, et le serveur
    fabriquerait des liens relatifs : un `link rel="self"` valant
    `/api/v1/...` rend le flux Atom invalide, et une URL de désinscription
    sans hôte n'est pas cliquable dans un e-mail."""
    from whatisup.core.config import _DEFAULT_PUBLIC_BASE_URL, Settings

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-32-chars-minimum-xx")
    for blank in ("", "   "):
        monkeypatch.setenv("PUBLIC_BASE_URL", blank)
        assert Settings().public_base_url == _DEFAULT_PUBLIC_BASE_URL

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://status.example.com")
    assert Settings().public_base_url == "https://status.example.com"
