"""Agent staleness classification for probes.

A probe self-reports its agent version at heartbeat (``Probe.version``,
``None`` for any agent older than 1.12 — it simply never sent the field).
This module turns that raw value, plus the server's own release version,
into the three-state verdict served on ``ProbeOut.agent_status``:

- ``unreported``: no version at all. Treated as the *oldest* possible agent,
  not as "unknown" and therefore ignorable — an agent too old to announce
  itself is precisely the one that most needs the warning.
- ``outdated``: reported, but strictly behind the server.
- ``current``: at, or *ahead* of, the server. A probe running a newer agent
  than the server it currently talks to is a normal mid-rollout state, not
  a problem.

Comparison is numeric (dotted components), not a string inequality — a
string compare would flag "1.9.0" as "newer" than "110.0.0", and would flag
a probe merely a build ahead of the server as outdated for no reason.
"""

from __future__ import annotations


def _parse_version(raw: str) -> tuple[int, ...]:
    """Parse a dotted numeric version prefix into a tuple of ints.

    Tolerates pre-release/build suffixes (``-rc1``, ``+build3``) by only
    reading the leading dot-separated numeric run: ``"1.24.0-rc1"`` becomes
    ``(1, 24, 0)``. Any non-digit component stops the parse there, so a
    malformed or empty string yields ``()`` rather than raising.
    """
    core = raw.split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for chunk in core.split("."):
        if not chunk.isdigit():
            break
        parts.append(int(chunk))
    return tuple(parts)


def compare_versions(a: str, b: str) -> int:
    """Return -1, 0 or 1 as ``a`` is <, ==, > ``b`` (numeric components only)."""
    pa, pb = _parse_version(a), _parse_version(b)
    length = max(len(pa), len(pb))
    pa = pa + (0,) * (length - len(pa))
    pb = pb + (0,) * (length - len(pb))
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


AGENT_STATUS_CURRENT = "current"
AGENT_STATUS_OUTDATED = "outdated"
AGENT_STATUS_UNREPORTED = "unreported"


def agent_status_for(probe_version: str | None, server_version: str) -> str:
    """Classify a probe's self-reported agent version against the server's."""
    if not probe_version:
        return AGENT_STATUS_UNREPORTED
    if compare_versions(probe_version, server_version) < 0:
        return AGENT_STATUS_OUTDATED
    return AGENT_STATUS_CURRENT
