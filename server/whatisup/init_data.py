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


async def init() -> None:
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
            shared_dir = "/shared"
            os.makedirs(shared_dir, exist_ok=True)
            pwd_path = os.path.join(shared_dir, "ADMIN_PASSWORD")
            fd = os.open(pwd_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(pwd)

            print("[WhatIsUp] Admin créé — email: admin@local")  # noqa: T201
            print("[WhatIsUp] Mot de passe dans /shared/ADMIN_PASSWORD (à supprimer après lecture).")  # noqa: T201

        # ── Central-Probe (optionnel, activé via AUTO_REGISTER_PROBE=true) ────
        if os.getenv("AUTO_REGISTER_PROBE", "false").lower() == "true":
            existing = (
                await db.execute(select(Probe).where(Probe.name == "Central-Probe"))
            ).scalar_one_or_none()

            if not existing:
                api_key = generate_probe_api_key()
                db.add(
                    Probe(
                        name="Central-Probe",
                        location_name=os.getenv("PROBE_LOCATION", "Central Server"),
                        api_key_hash=hash_api_key(api_key),
                    )
                )
                await db.flush()

                shared_dir = "/shared"
                os.makedirs(shared_dir, exist_ok=True)
                key_path = os.path.join(shared_dir, "PROBE_API_KEY")
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as fh:
                    fh.write(api_key)

                print("[WhatIsUp] Central-Probe enregistrée, clé écrite dans /shared/PROBE_API_KEY")  # noqa: T201

        await db.commit()


if __name__ == "__main__":
    asyncio.run(init())
