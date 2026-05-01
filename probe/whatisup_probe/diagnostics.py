"""Diagnostic collectors fired on incident open (V2-01-01).

Each collector wraps a system binary (``traceroute``, ``dig``, ``openssl``,
``ping``, ``curl``) under an ``asyncio.create_subprocess_exec`` with a hard
timeout. The output is parsed into a structured payload and posted back to the
central API. Failures are captured (``error`` field) rather than swallowed —
the diagnostic trail is still useful even when one collector misfires.

Design notes:
- ``mtr`` was considered but ``mtr-tiny`` (the Debian package) lacks
  ``--json``; sticking with ``traceroute -n`` keeps parsing predictable.
- Raw output is truncated to ``_MAX_RAW_BYTES`` so a chatty ``dig +trace``
  cannot blow up the JSONB payload.
- Collectors run in parallel via ``asyncio.gather`` to keep wall time tight.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)

_PER_KIND_TIMEOUT = 10.0  # seconds — hard cap per collector
_MAX_RAW_BYTES = 8 * 1024  # truncate raw command output

ALL_KINDS = (
    "traceroute",
    "dig_trace",
    "openssl_handshake",
    "icmp_ping",
    "http_verbose",
)


def _truncate(s: str) -> str:
    if len(s) <= _MAX_RAW_BYTES:
        return s
    return s[:_MAX_RAW_BYTES] + "\n…(truncated)"


def _extract_host(target: str) -> str:
    """Pull a hostname out of either a URL or a bare host[:port] string."""
    if "://" in target:
        return urlparse(target).hostname or target
    return target.split(":", 1)[0]


def _extract_port(target: str, default: int = 443) -> int:
    if "://" in target:
        parsed = urlparse(target)
        if parsed.port:
            return parsed.port
        return 443 if parsed.scheme == "https" else 80
    if ":" in target:
        try:
            return int(target.rsplit(":", 1)[1])
        except ValueError:
            return default
    return default


async def _run(cmd: list[str], stdin: bytes | None = None) -> tuple[int, str, str]:
    """Run a subprocess with a timeout; return (rc, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin), timeout=_PER_KIND_TIMEOUT
        )
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def collect_traceroute(host: str) -> dict[str, Any]:
    rc, out, err = await _run(["traceroute", "-n", "-w", "2", "-q", "1", host])
    hops: list[dict[str, Any]] = []
    target_ip: str | None = None
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(\S+)\s+ms", line)
        if not m:
            continue
        n = int(m.group(1))
        ip = m.group(2)
        try:
            rtt = float(m.group(3))
        except ValueError:
            rtt = None
        hops.append({"n": n, "ip": ip, "rtt_ms": rtt})
        if ip != "*" and target_ip is None and n > 0:
            target_ip = ip
    return {
        "hops": hops,
        "total_hops": len(hops),
        "target_ip": target_ip,
        "exit_code": rc,
        "raw": _truncate(out + (err or "")),
    }


async def collect_dig_trace(host: str) -> dict[str, Any]:
    rc, out, err = await _run(["dig", "+trace", "+time=3", "+tries=1", host])
    records: list[str] = []
    for line in out.splitlines():
        if not line or line.startswith(";"):
            continue
        records.append(line.strip())
    return {
        "records": records[:100],
        "queried_at": datetime.now(UTC).isoformat(),
        "exit_code": rc,
        "raw": _truncate(out + (err or "")),
    }


async def collect_openssl_handshake(host: str, port: int) -> dict[str, Any]:
    cmd = [
        "openssl", "s_client",
        "-connect", f"{host}:{port}",
        "-servername", host,
        "-showcerts",
        "-verify_return_error",
    ]
    rc, out, err = await _run(cmd, stdin=b"\n")  # close stdin politely
    combined = out + err
    cn = None
    if m := re.search(r"subject=.*?CN\s*=\s*([^\n,/]+)", combined):
        cn = m.group(1).strip()
    issuer = None
    if m := re.search(r"issuer=.*?CN\s*=\s*([^\n,/]+)", combined):
        issuer = m.group(1).strip()
    protocol = None
    if m := re.search(r"Protocol\s*:\s*(\S+)", combined):
        protocol = m.group(1).strip()
    cipher = None
    if m := re.search(r"Cipher\s*:\s*(\S+)", combined):
        cipher = m.group(1).strip()
    chain_depth = len(re.findall(r"-----BEGIN CERTIFICATE-----", combined))
    return {
        "cn": cn,
        "issuer": issuer,
        "protocol": protocol,
        "cipher": cipher,
        "chain_depth": chain_depth,
        "exit_code": rc,
        "raw": _truncate(combined),
    }


async def collect_icmp_ping(host: str) -> dict[str, Any]:
    rc, out, err = await _run(["ping", "-c", "5", "-W", "2", host])
    sent = received = 0
    loss = 100.0
    rtt_min = rtt_avg = rtt_max = None
    if m := re.search(r"(\d+)\s+packets transmitted,\s+(\d+)\s+received", out):
        sent = int(m.group(1))
        received = int(m.group(2))
        loss = round(((sent - received) / sent) * 100, 1) if sent else 100.0
    if m := re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)", out):
        rtt_min = float(m.group(1))
        rtt_avg = float(m.group(2))
        rtt_max = float(m.group(3))
    return {
        "packets_sent": sent,
        "packets_received": received,
        "loss_pct": loss,
        "rtt_min_ms": rtt_min,
        "rtt_avg_ms": rtt_avg,
        "rtt_max_ms": rtt_max,
        "exit_code": rc,
        "raw": _truncate(out + (err or "")),
    }


async def collect_http_verbose(target: str) -> dict[str, Any]:
    cmd = [
        "curl", "-sS", "-v", "-o", "/dev/null",
        "--max-time", "8",
        "-A", "WhatIsUp-Probe-Diagnostic/1.0",
        target,
    ]
    rc, _out, err = await _run(cmd)
    request_headers = [ln[2:] for ln in err.splitlines() if ln.startswith("> ")]
    response_headers = [ln[2:] for ln in err.splitlines() if ln.startswith("< ")]
    status_code = None
    if response_headers:
        if m := re.match(r"HTTP/[\d.]+\s+(\d+)", response_headers[0]):
            status_code = int(m.group(1))
    ssl_protocol = None
    if m := re.search(r"SSL connection using (\S+)", err):
        ssl_protocol = m.group(1)
    return {
        "request_headers": request_headers[:40],
        "response_headers": response_headers[:40],
        "status_code": status_code,
        "ssl_protocol": ssl_protocol,
        "exit_code": rc,
        "raw": _truncate(err),
    }


async def _safe_run(kind: str, coro) -> dict[str, Any]:
    """Run a collector and return a normalized {kind, payload, error, collected_at} dict."""
    started = datetime.now(UTC)
    try:
        payload = await coro
        return {
            "kind": kind,
            "payload": payload,
            "error": None,
            "collected_at": started.isoformat(),
        }
    except FileNotFoundError as exc:
        # Binary missing in the image — explicit signal so ops can fix the build.
        return {
            "kind": kind,
            "payload": {},
            "error": f"binary_missing: {exc.filename}",
            "collected_at": started.isoformat(),
        }
    except TimeoutError:
        return {
            "kind": kind,
            "payload": {},
            "error": "timeout",
            "collected_at": started.isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("diagnostic_collect_failed", kind=kind, error=str(exc))
        return {
            "kind": kind,
            "payload": {},
            "error": f"{type(exc).__name__}: {exc}",
            "collected_at": started.isoformat(),
        }


async def run_collection(
    target: str,
    check_type: str,
    kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run all requested collectors in parallel against ``target``.

    ``check_type`` (http / tcp / dns) is used to skip kinds that don't apply
    (e.g. openssl/curl for a TCP-only monitor)."""
    host = _extract_host(target)
    port = _extract_port(target)
    enabled = set(kinds or ALL_KINDS)

    is_http = check_type == "http" or target.startswith(("http://", "https://"))
    tasks: dict[str, Any] = {}

    if "traceroute" in enabled:
        tasks["traceroute"] = collect_traceroute(host)
    if "dig_trace" in enabled:
        tasks["dig_trace"] = collect_dig_trace(host)
    if "icmp_ping" in enabled:
        tasks["icmp_ping"] = collect_icmp_ping(host)
    if "openssl_handshake" in enabled and is_http:
        tasks["openssl_handshake"] = collect_openssl_handshake(host, port)
    if "http_verbose" in enabled and is_http:
        tasks["http_verbose"] = collect_http_verbose(target)

    results = await asyncio.gather(
        *(_safe_run(k, c) for k, c in tasks.items()),
        return_exceptions=False,
    )
    return list(results)
