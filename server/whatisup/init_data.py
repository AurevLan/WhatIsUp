"""First-boot initialisation: admin account + Central-Probe."""

from __future__ import annotations

import asyncio
import os
import secrets
import string

from sqlalchemy import func, select

from whatisup.core.database import get_session_factory
from whatisup.core.security import generate_probe_api_key, hash_api_key, hash_password_async
from whatisup.models.probe import Probe
from whatisup.models.user import User

_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*"

# Deux volumes distincts, pas un seul (audit F15). La sonde est le composant le
# plus exposé — elle exécute des checks sortants contre des cibles hostiles —
# et n'a besoin que de sa clé d'API ; lui monter tout `/shared` lui donnait
# aussi le mot de passe superadmin du premier boot.
SHARED_DIR = "/shared"  # serveur uniquement
PROBE_SECRETS_DIR = "/probe-secrets"  # partagé serveur ↔ sonde locale

ADMIN_PASSWORD_FILE = os.path.join(SHARED_DIR, "ADMIN_PASSWORD")
PROBE_KEY_FILE = os.path.join(PROBE_SECRETS_DIR, "PROBE_API_KEY")
_LEGACY_PROBE_KEY_FILE = os.path.join(SHARED_DIR, "PROBE_API_KEY")


def _write_secret_file(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value)


def migrate_legacy_probe_key() -> None:
    """Déplace une clé de sonde écrite avant la séparation des volumes.

    Sans ça, une installation existante mise à jour verrait la sonde locale
    perdre sa clé : le nouveau volume est vide, et `init()` ne réécrit la clé
    que lors de la *création* de la sonde — elle n'est plus récupérable ensuite
    (seul son hash est en base).
    """
    if os.path.exists(PROBE_KEY_FILE) or not os.path.exists(_LEGACY_PROBE_KEY_FILE):
        return
    try:
        with open(_LEGACY_PROBE_KEY_FILE) as fh:
            _write_secret_file(PROBE_KEY_FILE, fh.read().strip())
        os.unlink(_LEGACY_PROBE_KEY_FILE)
        print("[WhatIsUp] Clé Central-Probe migrée vers /probe-secrets")  # noqa: T201
    except OSError as exc:
        print(f"[WhatIsUp] Migration de la clé sonde impossible : {exc}")  # noqa: T201


def consume_admin_password_file() -> None:
    """Supprime le fichier de mot de passe du premier boot, une fois utilisé.

    L'audit relevait que sa suppression était *conseillée*, jamais appliquée :
    le fichier survivait indéfiniment. Une connexion superadmin réussie prouve
    que l'opérateur l'a lu — c'est le moment de le retirer. Best-effort : un
    échec ne doit pas casser une connexion.
    """
    try:
        os.unlink(ADMIN_PASSWORD_FILE)
    except FileNotFoundError:
        return
    except OSError:
        return


async def init() -> None:
    migrate_legacy_probe_key()

    factory = get_session_factory()
    async with factory() as db:
        # ── Admin account ─────────────────────────────────────────────────────
        count = (await db.execute(select(func.count()).select_from(User))).scalar()
        if count == 0:
            pwd = "".join(secrets.choice(_ALPHABET) for _ in range(20))
            db.add(
                User(
                    email="admin@local",
                    username="admin",
                    hashed_password=await hash_password_async(pwd),
                    is_superadmin=True,
                    is_active=True,
                )
            )
            await db.flush()

            # Write password to a temp file instead of logging it in clear text
            _write_secret_file(ADMIN_PASSWORD_FILE, pwd)

            print("[WhatIsUp] Admin créé — email: admin@local")  # noqa: T201
            print(  # noqa: T201
                f"[WhatIsUp] Mot de passe : {ADMIN_PASSWORD_FILE}"
                " (supprimé automatiquement à la première connexion)"
            )

        # ── Central-Probe (optionnel, activé via AUTO_REGISTER_PROBE=true) ────
        if os.getenv("AUTO_REGISTER_PROBE", "false").lower() == "true":
            existing = (
                await db.execute(select(Probe).where(Probe.name == "Central-Probe"))
            ).scalar_one_or_none()

            if not existing:
                api_key, api_key_prefix = generate_probe_api_key()
                db.add(
                    Probe(
                        name="Central-Probe",
                        location_name=os.getenv("PROBE_LOCATION", "Central Server"),
                        api_key_hash=hash_api_key(api_key),
                        api_key_prefix=api_key_prefix,
                    )
                )
                await db.flush()

                _write_secret_file(PROBE_KEY_FILE, api_key)

                # Chemin écrit en toutes lettres, pas interpolé : CodeQL classe
                # tout identifiant contenant « KEY » comme donnée sensible et
                # signale un log en clair, alors qu'on n'affiche qu'un chemin.
                print(  # noqa: T201
                    "[WhatIsUp] Central-Probe enregistrée, clé écrite dans"
                    " /probe-secrets/PROBE_API_KEY"
                )

        await db.commit()


if __name__ == "__main__":
    asyncio.run(init())
