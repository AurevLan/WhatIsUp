"""S5 — garde-fous SSRF et DoS côté sonde (audit F9, F20, F8, F19).

La sonde exécute de la configuration écrite par un tenant, depuis l'intérieur
du réseau de supervision. Deux familles de défauts :

- **SSRF** : F9 (les collecteurs de diagnostic n'appliquaient aucun garde-fou)
  et F20 (l'audit TLS et l'extraction SSL rouvraient une connexion avec leur
  propre résolution DNS, après le check épinglé — fenêtre de rebinding).
- **DoS** : F19 (`asyncio.wait_for` n'interrompt pas le thread qui évalue un
  motif) et F8 (`jsonschema.validate` tournait à même la boucle, sans timeout).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from whatisup_probe.checkers._regex_guard import (
    MAX_SCHEMA_BYTES,
    PatternInvalid,
    PatternTimeout,
    safe_search,
    validate_json_schema_sync,
)
from whatisup_probe.checkers._shared import (
    SSRFBlockedError,
    _extract_ssl_info_sync,
    _extract_tls_audit_sync,
)
from whatisup_probe.diagnostics import run_collection

# Alternance dupliquée : chaque caractère peut être consommé par deux branches
# équivalentes, donc le nombre de chemins double à chaque position. `re` y passe
# un temps exponentiel qu'aucun timeout externe ne peut interrompre.
# (`^(a+)+$` — l'exemple canonique — ne sert à rien ici : le moteur `regex`
# l'optimise et répond immédiatement.)
_REDOS_PATTERN = r"^(a|aa)+$"
_REDOS_SUBJECT = "a" * 40 + "!"


# ── F19 — motifs interruptibles ──────────────────────────────────────────────


def test_catastrophic_pattern_is_interrupted_not_merely_abandoned():
    """Le budget doit être tenu *par le moteur*, pas par un timeout qui laisse tourner."""
    started = time.monotonic()
    with pytest.raises(PatternTimeout):
        safe_search(_REDOS_PATTERN, _REDOS_SUBJECT, timeout=0.5)
    elapsed = time.monotonic() - started

    # Marge large : ce qui est vérifié, c'est que l'appel *rend la main* près du
    # budget au lieu de partir en exponentielle.
    assert elapsed < 5.0


def test_valid_pattern_still_matches():
    assert safe_search(r"he(l+)o", "hello world") is not None
    assert safe_search(r"^nope$", "hello world") is None


def test_invalid_pattern_is_reported_as_such():
    with pytest.raises(PatternInvalid):
        safe_search(r"(unclosed", "whatever")


def test_oversized_subject_is_refused():
    with pytest.raises(PatternTimeout):
        safe_search(r"x", "a" * 5_000_001)


# ── F8 — jsonschema borné ────────────────────────────────────────────────────


def test_schema_pattern_redos_is_bounded():
    """Un `pattern` hostile dans le schéma ne doit plus geler l'évaluation."""
    schema = {"type": "object", "properties": {"v": {"type": "string", "pattern": _REDOS_PATTERN}}}
    started = time.monotonic()
    with pytest.raises(PatternTimeout):
        validate_json_schema_sync({"v": _REDOS_SUBJECT}, schema, timeout=0.5)

    assert time.monotonic() - started < 5.0


def test_pattern_properties_redos_is_bounded():
    schema = {"type": "object", "patternProperties": {_REDOS_PATTERN: {"type": "string"}}}
    with pytest.raises(PatternTimeout):
        validate_json_schema_sync({_REDOS_SUBJECT: "x"}, schema, timeout=0.5)


def test_valid_instance_passes_and_invalid_one_raises():
    """Le durcissement ne doit pas changer la sémantique de validation."""
    from jsonschema import ValidationError

    schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "pattern": "^[a-z]+$"}},
        "required": ["name"],
    }
    validate_json_schema_sync({"name": "ok"}, schema)

    with pytest.raises(ValidationError):
        validate_json_schema_sync({"name": "NOPE"}, schema)
    with pytest.raises(ValidationError):
        validate_json_schema_sync({}, schema)


def test_pattern_properties_still_descends_into_matching_keys():
    from jsonschema import ValidationError

    schema = {"type": "object", "patternProperties": {"^s_": {"type": "string"}}}
    validate_json_schema_sync({"s_a": "text", "other": 42}, schema)

    with pytest.raises(ValidationError):
        validate_json_schema_sync({"s_a": 42}, schema)


def test_oversized_schema_is_refused():
    schema = {"type": "object", "description": "x" * (MAX_SCHEMA_BYTES + 1)}
    with pytest.raises(ValueError, match="too large"):
        validate_json_schema_sync({}, schema)


# ── F20 — audit TLS / info SSL épinglés ──────────────────────────────────────


def test_tls_audit_refuses_a_target_that_rebinds_internal():
    """La cible est revalidée : le certificat d'un service interne ne remonte pas."""
    with (
        patch(
            "whatisup_probe.checkers._shared._ssrf_resolve_pinned_sync",
            side_effect=SSRFBlockedError("Host resolves to internal IP: '10.0.0.5'"),
        ),
        patch("whatisup_probe.checkers._shared.socket.create_connection") as sock,
    ):
        assert _extract_tls_audit_sync("https://rebind.example") is None

    sock.assert_not_called()


def test_ssl_info_refuses_a_target_that_rebinds_internal():
    with (
        patch(
            "whatisup_probe.checkers._shared._ssrf_resolve_pinned_sync",
            side_effect=SSRFBlockedError("Host resolves to internal IP: '10.0.0.5'"),
        ),
        patch("whatisup_probe.checkers._shared.socket.create_connection") as sock,
    ):
        assert _extract_ssl_info_sync("https://rebind.example") == (False, None, None, None)

    sock.assert_not_called()


def test_tls_audit_connects_to_the_pinned_ip_but_keeps_sni():
    """L'IP validée sert à la connexion ; le nom reste le SNI et la base du match SAN."""
    with (
        patch(
            "whatisup_probe.checkers._shared._ssrf_resolve_pinned_sync",
            return_value="93.184.216.34",
        ),
        patch("whatisup_probe.checkers._shared.socket.create_connection") as sock,
        patch("whatisup_probe.checkers._shared.ssl.create_default_context") as ctx_factory,
    ):
        ctx = ctx_factory.return_value
        # Handshake factice : on ne teste ici que le routage de la connexion.
        ctx.wrap_socket.return_value.__enter__.return_value.getpeercert.return_value = None
        _extract_tls_audit_sync("https://pinned.example:8443")

    sock.assert_called_once()
    assert sock.call_args.args[0] == ("93.184.216.34", 8443)
    assert ctx.wrap_socket.call_args.kwargs["server_hostname"] == "pinned.example"


# ── F9 — diagnostics sous garde-fou SSRF ─────────────────────────────────────


@pytest.mark.asyncio
async def test_run_collection_refuses_an_internal_target():
    with (
        patch(
            "whatisup_probe.diagnostics._ssrf_resolve_pinned_sync",
            side_effect=SSRFBlockedError("Blocked internal IP: '169.254.169.254'"),
        ),
        patch("whatisup_probe.diagnostics._run") as run,
    ):
        assert await run_collection("http://169.254.169.254/latest/meta-data", "http") == []

    run.assert_not_called()


@pytest.mark.asyncio
async def test_run_collection_refuses_when_resolution_fails():
    """Fail-closed : pas de résolution validée, pas de collecte."""
    with (
        patch(
            "whatisup_probe.diagnostics._ssrf_resolve_pinned_sync",
            side_effect=OSError("boom"),
        ),
        patch("whatisup_probe.diagnostics._run") as run,
    ):
        assert await run_collection("https://unresolvable.example", "http") == []

    run.assert_not_called()


@pytest.mark.asyncio
async def test_collectors_are_pinned_to_the_validated_ip():
    """Chaque collecteur vise l'IP validée — sinon le nom pouvait rebasculer."""
    cmds: list[list[str]] = []

    async def _capture(cmd, stdin=None):
        cmds.append(cmd)
        return 0, "", ""

    with (
        patch(
            "whatisup_probe.diagnostics._ssrf_resolve_pinned_sync",
            return_value="93.184.216.34",
        ),
        patch("whatisup_probe.diagnostics._run", AsyncMock(side_effect=_capture)),
    ):
        await run_collection("https://pinned.example/status", "http")

    by_binary = {cmd[0]: cmd for cmd in cmds}

    assert "93.184.216.34" in by_binary["traceroute"]
    assert "93.184.216.34" in by_binary["ping"]

    openssl = by_binary["openssl"]
    assert "93.184.216.34:443" in openssl
    # SNI préservé : sans lui, l'audit du certificat perdrait son sens.
    assert openssl[openssl.index("-servername") + 1] == "pinned.example"

    curl = by_binary["curl"]
    assert curl[curl.index("--resolve") + 1] == "pinned.example:443:93.184.216.34"
    # L'URL d'origine est conservée : en-tête Host et chemin inchangés.
    assert curl[-1] == "https://pinned.example/status"

    # `dig` interroge des résolveurs, pas la cible : il garde le nom.
    assert "pinned.example" in by_binary["dig"]
