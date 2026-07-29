"""Validateurs partagés entre les schémas Pydantic et les services.

Vit dans `core/` plutôt que dans `schemas/` parce que les deux couches en ont
besoin : la validation au bord (422 sur une entrée d'API) ne couvre pas les
chemins qui écrivent en base sans schéma — l'import IaC `PUT /config/` prend un
`dict[str, Any]` brut — ni les lignes déjà présentes en base.
"""

from __future__ import annotations

import re

# Volontairement plus strict que la RFC : ce qui compte ici est qu'aucun
# caractère d'espacement ne passe. Une adresse destinataire finit dans un
# en-tête SMTP ; un CR/LF au milieu transforme le champ en injection d'en-tête
# arbitraire (audit F7). `\s` couvre \r et \n.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# RFC 5321 §4.5.3.1.3 : 320 caractères pour un chemin inverse complet.
_MAX_EMAIL_LEN = 320


def is_valid_email(addr: object) -> bool:
    """Vrai si `addr` peut être posé sans danger dans un en-tête destinataire."""
    return (
        isinstance(addr, str) and len(addr) <= _MAX_EMAIL_LEN and _EMAIL_RE.match(addr) is not None
    )


def validate_email_list(values: list[str]) -> list[str]:
    """Retourne la liste inchangée, ou lève `ValueError` sur la première invalide."""
    for addr in values:
        if not is_valid_email(addr):
            raise ValueError(f"Invalid email address: {addr!r}")
    return values
