"""Snapshot tests for the probe diagnostic collectors.
#3 / Top 5 quality push (reliquat).

Each collector parses raw output of a system binary into a structured JSON
payload. The contract between probe and server is the *shape and field names*
of that payload — if we accidentally rename `total_hops` to `hop_count` the
server's ingest endpoint silently drops the field. These tests pin the exact
payload structure produced for known-good raw inputs.

Strategy:
- Mock ``whatisup_probe.diagnostics._run`` (the single subprocess wrapper) so
  no real ``traceroute`` / ``dig`` / ``openssl`` / ``ping`` / ``curl`` binary
  is invoked.
- Feed each collector a realistic raw output captured from a healthy run.
- Assert on the parsed payload exactly — every field, every type.
- ``raw`` is asserted via prefix/length rather than equality since
  ``_truncate`` may stamp a "(truncated)" sentinel on long outputs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from whatisup_probe.diagnostics import (
    _extract_host,
    _extract_port,
    _safe_run,
    collect_dig_trace,
    collect_http_verbose,
    collect_icmp_ping,
    collect_openssl_handshake,
    collect_traceroute,
    run_collection,
)


def _mock_run(stdout: str = "", stderr: str = "", rc: int = 0):
    """Return an AsyncMock for diagnostics._run with the given subprocess output."""
    return AsyncMock(return_value=(rc, stdout, stderr))


# ── _extract_host / _extract_port (pure helpers) ─────────────────────────────


def test_extract_host_from_url():
    assert _extract_host("https://example.com/path?q=1") == "example.com"


def test_extract_host_from_host_only():
    assert _extract_host("example.com") == "example.com"


def test_extract_host_strips_port():
    assert _extract_host("example.com:8080") == "example.com"


def test_extract_port_from_https_url():
    assert _extract_port("https://example.com/x") == 443


def test_extract_port_from_http_url():
    assert _extract_port("http://example.com/x") == 80


def test_extract_port_explicit_url():
    assert _extract_port("https://example.com:8443/x") == 8443


def test_extract_port_host_with_port():
    assert _extract_port("example.com:9090") == 9090


def test_extract_port_falls_back_to_default():
    assert _extract_port("example.com", default=1234) == 1234


# ── collect_traceroute ───────────────────────────────────────────────────────

TRACEROUTE_OUT = """traceroute to google.com (142.250.179.110), 30 hops max
 1  192.168.1.1  1.234 ms
 2  10.0.0.1  3.456 ms
 3  *  *
 4  142.250.179.110  12.345 ms
"""


@pytest.mark.asyncio
async def test_collect_traceroute_parses_hops_and_target():
    with patch("whatisup_probe.diagnostics._run", _mock_run(stdout=TRACEROUTE_OUT)):
        payload = await collect_traceroute("google.com")

    assert payload["exit_code"] == 0
    assert payload["total_hops"] == 3  # lines matching the regex (the "* *" hop is skipped)
    assert payload["target_ip"] == "192.168.1.1"  # first non-wildcard hop with n>0
    assert payload["hops"] == [
        {"n": 1, "ip": "192.168.1.1", "rtt_ms": 1.234},
        {"n": 2, "ip": "10.0.0.1", "rtt_ms": 3.456},
        {"n": 4, "ip": "142.250.179.110", "rtt_ms": 12.345},
    ]
    assert payload["raw"].startswith("traceroute to google.com")


@pytest.mark.asyncio
async def test_collect_traceroute_empty_output():
    with patch("whatisup_probe.diagnostics._run", _mock_run()):
        payload = await collect_traceroute("invalid.example")
    assert payload["hops"] == []
    assert payload["total_hops"] == 0
    assert payload["target_ip"] is None


# ── collect_dig_trace ────────────────────────────────────────────────────────

DIG_OUT = """
; <<>> DiG 9.18.30 <<>> +trace example.com
;; global options: +cmd
.		61432	IN	NS	a.root-servers.net.
.		61432	IN	NS	b.root-servers.net.
example.com.	300	IN	A	93.184.215.14
;; Received 56 bytes from 192.0.2.1#53(a.root-servers.net) in 12 ms
"""


@pytest.mark.asyncio
async def test_collect_dig_trace_filters_comment_lines():
    with patch("whatisup_probe.diagnostics._run", _mock_run(stdout=DIG_OUT)):
        payload = await collect_dig_trace("example.com")

    assert payload["exit_code"] == 0
    # `;`-prefixed lines and blank lines are stripped; the three record lines
    # plus the closing ";; Received…" stay (the ";;" line is filtered because
    # it begins with `;`).
    assert payload["records"] == [
        ".\t\t61432\tIN\tNS\ta.root-servers.net.",
        ".\t\t61432\tIN\tNS\tb.root-servers.net.",
        "example.com.\t300\tIN\tA\t93.184.215.14",
    ]
    assert "queried_at" in payload  # ISO timestamp


# ── collect_openssl_handshake ────────────────────────────────────────────────

OPENSSL_OUT = """CONNECTED(00000003)
depth=2 C = US, O = DigiCert Inc, CN = DigiCert Global Root CA
verify return:1
---
Certificate chain
 0 s:CN = example.com
   i:C = US, O = DigiCert Inc, CN = R3
-----BEGIN CERTIFICATE-----
MIIDxTCCAq2gAwIBAgI...
-----END CERTIFICATE-----
 1 s:CN = R3
   i:C = US, O = DigiCert Inc, CN = DigiCert Global Root CA
-----BEGIN CERTIFICATE-----
MIIDxTCCAq2gAwIBAgI...
-----END CERTIFICATE-----
---
SSL handshake has read 5000 bytes and written 300 bytes
subject=CN = example.com
issuer=CN = R3
---
New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
Server public key is 2048 bit
SSL-Session:
    Protocol  : TLSv1.3
    Cipher    : TLS_AES_256_GCM_SHA384
"""


@pytest.mark.asyncio
async def test_collect_openssl_extracts_cert_and_protocol():
    with patch("whatisup_probe.diagnostics._run", _mock_run(stdout=OPENSSL_OUT)):
        payload = await collect_openssl_handshake("example.com", 443)

    assert payload["exit_code"] == 0
    assert payload["cn"] == "example.com"
    assert payload["issuer"] == "R3"
    assert payload["protocol"] == "TLSv1.3"
    assert payload["cipher"] == "TLS_AES_256_GCM_SHA384"
    assert payload["chain_depth"] == 2


@pytest.mark.asyncio
async def test_collect_openssl_missing_fields_remain_none():
    with patch("whatisup_probe.diagnostics._run", _mock_run(stdout="connect:errno=111")):
        payload = await collect_openssl_handshake("unreachable.example", 443)
    assert payload["cn"] is None
    assert payload["issuer"] is None
    assert payload["protocol"] is None
    assert payload["cipher"] is None
    assert payload["chain_depth"] == 0


# ── collect_icmp_ping ────────────────────────────────────────────────────────

PING_OUT = """PING example.com (93.184.216.34): 56 data bytes
64 bytes from 93.184.216.34: icmp_seq=0 ttl=56 time=10.123 ms
64 bytes from 93.184.216.34: icmp_seq=1 ttl=56 time=11.456 ms
64 bytes from 93.184.216.34: icmp_seq=2 ttl=56 time=12.789 ms
64 bytes from 93.184.216.34: icmp_seq=3 ttl=56 time=13.012 ms
64 bytes from 93.184.216.34: icmp_seq=4 ttl=56 time=14.345 ms
--- example.com ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4006ms
rtt min/avg/max/mdev = 10.123/12.345/14.345/1.500 ms
"""


@pytest.mark.asyncio
async def test_collect_icmp_ping_parses_stats():
    with patch("whatisup_probe.diagnostics._run", _mock_run(stdout=PING_OUT)):
        payload = await collect_icmp_ping("example.com")

    assert payload["exit_code"] == 0
    assert payload["packets_sent"] == 5
    assert payload["packets_received"] == 5
    assert payload["loss_pct"] == 0.0
    assert payload["rtt_min_ms"] == 10.123
    assert payload["rtt_avg_ms"] == 12.345
    assert payload["rtt_max_ms"] == 14.345


@pytest.mark.asyncio
async def test_collect_icmp_ping_handles_full_loss():
    out = "5 packets transmitted, 0 received, 100% packet loss, time 4005ms\n"
    with patch("whatisup_probe.diagnostics._run", _mock_run(stdout=out)):
        payload = await collect_icmp_ping("unreachable.example")
    assert payload["packets_sent"] == 5
    assert payload["packets_received"] == 0
    assert payload["loss_pct"] == 100.0
    assert payload["rtt_min_ms"] is None
    assert payload["rtt_avg_ms"] is None


# ── collect_http_verbose ─────────────────────────────────────────────────────

CURL_STDERR = """*   Trying 93.184.216.34:443...
* Connected to example.com (93.184.216.34) port 443
* ALPN: offers h2,http/1.1
* SSL connection using TLSv1.3 / TLS_AES_256_GCM_SHA384
* Server certificate:
*  subject: CN=example.com
> GET / HTTP/2
> Host: example.com
> User-Agent: WhatIsUp-Probe-Diagnostic/1.0
> Accept: */*
>
< HTTP/2 200
< accept-ranges: bytes
< age: 12345
< cache-control: max-age=604800
< content-type: text/html; charset=UTF-8
<
* Connection #0 to host example.com left intact
"""


@pytest.mark.asyncio
async def test_collect_http_verbose_extracts_headers_and_status():
    with patch("whatisup_probe.diagnostics._run", _mock_run(stderr=CURL_STDERR)):
        payload = await collect_http_verbose("https://example.com")

    assert payload["exit_code"] == 0
    assert payload["status_code"] == 200
    assert payload["ssl_protocol"] == "TLSv1.3"
    # Note: blank-line markers (`>\n` / `<\n`) are dropped by the
    # `startswith("> ")` filter — only the prefixed-and-spaced lines are kept.
    assert payload["request_headers"] == [
        "GET / HTTP/2",
        "Host: example.com",
        "User-Agent: WhatIsUp-Probe-Diagnostic/1.0",
        "Accept: */*",
    ]
    assert payload["response_headers"] == [
        "HTTP/2 200",
        "accept-ranges: bytes",
        "age: 12345",
        "cache-control: max-age=604800",
        "content-type: text/html; charset=UTF-8",
    ]


@pytest.mark.asyncio
async def test_collect_http_verbose_truncates_headers_at_40():
    # 50 fake "> " lines should be capped at 40 in the payload.
    big = "\n".join(f"> X-Test-{i}: v{i}" for i in range(50))
    with patch("whatisup_probe.diagnostics._run", _mock_run(stderr=big)):
        payload = await collect_http_verbose("https://example.com")
    assert len(payload["request_headers"]) == 40


# ── _safe_run wrapper ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_safe_run_passes_payload_through():
    async def fake():
        return {"hello": "world"}

    out = await _safe_run("kind_x", fake())
    assert out["kind"] == "kind_x"
    assert out["payload"] == {"hello": "world"}
    assert out["error"] is None
    assert "collected_at" in out


@pytest.mark.asyncio
async def test_safe_run_captures_filenotfound_as_binary_missing():
    async def fake():
        raise FileNotFoundError(2, "No such file or directory", "traceroute")

    out = await _safe_run("traceroute", fake())
    assert out["payload"] == {}
    assert out["error"] == "binary_missing: traceroute"


@pytest.mark.asyncio
async def test_safe_run_captures_timeout():
    async def fake():
        raise TimeoutError()

    out = await _safe_run("dig_trace", fake())
    assert out["payload"] == {}
    assert out["error"] == "timeout"


@pytest.mark.asyncio
async def test_safe_run_captures_generic_exception_with_typename():
    async def fake():
        raise ValueError("bad value")

    out = await _safe_run("icmp_ping", fake())
    assert out["error"] == "ValueError: bad value"


# ── run_collection (orchestrator) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_collection_skips_http_only_kinds_for_tcp():
    """openssl + curl are HTTP-specific; a TCP monitor should not invoke them."""
    with patch("whatisup_probe.diagnostics._run", _mock_run()):
        results = await run_collection("example.com:22", check_type="tcp")
    kinds = {r["kind"] for r in results}
    assert "openssl_handshake" not in kinds
    assert "http_verbose" not in kinds
    # traceroute / dig / ping still run.
    assert "traceroute" in kinds
    assert "dig_trace" in kinds
    assert "icmp_ping" in kinds


@pytest.mark.asyncio
async def test_run_collection_filters_by_requested_kinds():
    with patch("whatisup_probe.diagnostics._run", _mock_run()):
        results = await run_collection(
            "https://example.com", check_type="http", kinds=["traceroute"]
        )
    assert [r["kind"] for r in results] == ["traceroute"]


@pytest.mark.asyncio
async def test_run_collection_runs_http_specific_for_http_target():
    with patch("whatisup_probe.diagnostics._run", _mock_run()):
        results = await run_collection("https://example.com", check_type="http")
    kinds = {r["kind"] for r in results}
    assert kinds == {"traceroute", "dig_trace", "openssl_handshake", "icmp_ping", "http_verbose"}
