"""Exécution bornée des motifs et schémas fournis par le propriétaire d'un monitor.

Deux mécanismes, pour deux moitiés du même problème (audit F19, F8) :

1. **Un moteur interruptible.** `re` ne peut pas être arrêté : `asyncio.wait_for`
   autour d'un `run_in_executor` annule la coroutine qui attend, pas le thread
   qui calcule. Un motif à backtracking catastrophique continuait donc à brûler
   un thread longtemps après que le check ait renvoyé « down ». Le module
   `regex` accepte un `timeout=` que le moteur vérifie *pendant* le parcours :
   le thread est réellement rendu. `regex` est un sur-ensemble de `re` en mode
   V0 (le défaut), donc les motifs existants continuent de fonctionner.

2. **Un pool isolé.** Tout ce travail CPU non fiable tourne dans son propre
   `ThreadPoolExecutor`, jamais dans l'executor par défaut — celui-ci sert à la
   résolution DNS, à l'épinglage SSRF et à l'extraction TLS. Même si un thread
   de ce pool devait rester bloqué, il ne pourrait pas geler les checks des
   autres tenants : c'est précisément l'impact décrit par l'audit.

`jsonschema` valide `pattern` / `patternProperties` avec `re` en interne, hors
de tout timeout. On étend donc la classe de validateur correspondant au schéma
pour router ces deux mots-clés vers le moteur interruptible, avec une échéance
partagée par toute la validation (sinon N motifs × T secondes se cumulent).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import regex

# Assez de parallélisme pour ne pas sérialiser les checks d'un même cycle,
# assez petit pour que ce travail ne puisse jamais monopoliser la machine.
_MAX_WORKERS = 4

# Budget CPU par vérification. Le check HTTP lui-même a un timeout bien plus
# large ; ce budget-ci ne borne que l'évaluation du motif.
DEFAULT_TIMEOUT = 5.0

# Au-delà, on refuse d'évaluer plutôt que de tenter : un corps de cette taille
# n'est pas un cas d'usage de motif, c'est un vecteur.
MAX_REGEX_SUBJECT_BYTES = 5_000_000
MAX_SCHEMA_INSTANCE_BYTES = 5_000_000
MAX_SCHEMA_BYTES = 64_000

_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="userpattern")

# Échéance courante du thread : `jsonschema` appelle nos validateurs depuis
# l'intérieur de sa propre récursion, sans qu'on puisse lui passer d'argument.
_local = threading.local()


class PatternTimeout(Exception):
    """Le motif n'a pas terminé dans le budget imparti."""


class PatternInvalid(Exception):
    """Le motif ne compile pas."""


def pattern_executor() -> ThreadPoolExecutor:
    """Pool dédié au travail CPU issu de la configuration utilisateur."""
    return _executor


def _remaining() -> float:
    """Budget restant pour l'échéance du thread courant, sinon le défaut."""
    deadline = getattr(_local, "deadline", None)
    if deadline is None:
        return DEFAULT_TIMEOUT
    return max(0.001, deadline - time.monotonic())


def safe_search(pattern: str, subject: str, *, flags: int = 0, timeout: float | None = None):
    """`regex.search` borné dans le temps — bloquant, à lancer via :func:`pattern_executor`.

    Lève :class:`PatternTimeout` si le budget est épuisé, :class:`PatternInvalid`
    si le motif ne compile pas.
    """
    if len(subject) > MAX_REGEX_SUBJECT_BYTES:
        raise PatternTimeout("subject too large for pattern evaluation")
    budget = _remaining() if timeout is None else timeout
    try:
        return regex.search(pattern, subject, flags=flags, timeout=budget)
    except TimeoutError as exc:  # levé par le moteur regex
        raise PatternTimeout(str(exc)) from None
    except regex.error as exc:
        raise PatternInvalid(str(exc)) from None


# ── jsonschema : router `pattern` / `patternProperties` vers le moteur borné ──


def _pattern(validator, patrn, instance, schema):
    from jsonschema.exceptions import ValidationError

    if not validator.is_type(instance, "string"):
        return
    if safe_search(patrn, instance) is None:
        yield ValidationError(f"{instance!r} does not match {patrn!r}")


def _pattern_properties(validator, patternProperties, instance, schema):
    if not validator.is_type(instance, "object"):
        return
    for patrn, subschema in patternProperties.items():
        for key, value in instance.items():
            if safe_search(patrn, key) is not None:
                yield from validator.descend(value, subschema, path=key, schema_path=patrn)


_extended: dict[Any, Any] = {}


def _safe_validator_for(schema: dict):
    """Classe de validateur du schéma, motifs routés vers le moteur borné.

    On étend la classe que `jsonschema` aurait choisie (via `$schema`) plutôt
    que d'en imposer une : le draft déclaré par l'utilisateur reste respecté.
    """
    from jsonschema.validators import extend, validator_for

    base = validator_for(schema)
    cached = _extended.get(base)
    if cached is None:
        cached = extend(base, {"pattern": _pattern, "patternProperties": _pattern_properties})
        _extended[base] = cached
    return cached


def validate_json_schema_sync(instance: Any, schema: dict, *, timeout: float = DEFAULT_TIMEOUT):
    """Valide `instance` contre `schema`, tout motif borné — bloquant.

    À lancer via :func:`pattern_executor`. Lève l'erreur de validation de `jsonschema`
    (comportement de `jsonschema.validate`), :class:`PatternTimeout` si le budget
    est épuisé, ou `ValueError` si le schéma dépasse la taille admise.
    """
    import json

    from jsonschema.exceptions import best_match

    if len(json.dumps(schema)) > MAX_SCHEMA_BYTES:
        raise ValueError("json_schema too large")

    _local.deadline = time.monotonic() + timeout
    try:
        cls = _safe_validator_for(schema)
        cls.check_schema(schema)
        error = best_match(cls(schema).iter_errors(instance))
        if error is not None:
            raise error
    finally:
        _local.deadline = None
