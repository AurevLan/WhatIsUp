"""DNS resolution checker."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from ._shared import validate_host_ssrf
from .base import BaseChecker, CheckResult


class DNSChecker(BaseChecker):
    name = "dns"

    async def check(self, monitor_id: str, config: dict[str, Any], **kwargs: Any) -> CheckResult:
        import dns.resolver  # type: ignore[import]

        parsed = urlparse(config.get("url", ""))
        host = parsed.hostname or config.get("url", "")
        record_type = config.get("dns_record_type") or "A"
        expected_value = config.get("dns_expected_value")
        timeout_seconds = config["timeout_seconds"]

        checked_at = datetime.now(UTC)

        # Block DNS lookups targeting internal hostnames (SSRF prevention)
        ssrf_err = validate_host_ssrf(host)
        if ssrf_err:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message=f"SSRF blocked: {ssrf_err}",
            )

        t0 = time.perf_counter()

        try:
            resolver = dns.resolver.Resolver()
            resolver.lifetime = timeout_seconds
            # Disable dnspython internal cache to always get fresh results
            resolver.cache = dns.resolver.LRUCache(0)
            # Use custom nameservers if configured, bypassing system cache
            nameservers = config.get("dns_nameservers")
            if nameservers:
                import ipaddress as _ipa

                ns_list = nameservers if isinstance(nameservers, list) else [nameservers]
                validated = []
                for ns in ns_list:
                    try:
                        ip = _ipa.ip_address(ns)
                        if ip.is_private or ip.is_loopback or ip.is_link_local:
                            return CheckResult(
                                monitor_id=monitor_id,
                                checked_at=checked_at,
                                status="error",
                                error_message=f"Blocked private/internal nameserver: {ns}",
                            )
                        validated.append(ns)
                    except ValueError:
                        return CheckResult(
                            monitor_id=monitor_id,
                            checked_at=checked_at,
                            status="error",
                            error_message=f"Invalid nameserver IP: {ns}",
                        )
                resolver.nameservers = validated

            loop = asyncio.get_running_loop()
            answers = await asyncio.wait_for(
                loop.run_in_executor(None, resolver.resolve, host, record_type),
                timeout=timeout_seconds + 2,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000

            resolved_values = [str(r) for r in answers]

            if expected_value and not any(expected_value in v for v in resolved_values):
                return CheckResult(
                    monitor_id=monitor_id,
                    checked_at=checked_at,
                    status="down",
                    response_time_ms=round(elapsed_ms, 2),
                    error_message=(
                        f"DNS {record_type} for {host}: expected {expected_value!r}, "
                        f"got {resolved_values}"
                    ),
                )

            # V2-02-04 — DNS authoritative consistency.
            # Best-effort: query each authoritative NS for the same record and
            # compare. Failure is non-fatal — main check stays "up".
            consistency = await _collect_dns_consistency(host, record_type, timeout_seconds)

            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="up",
                response_time_ms=round(elapsed_ms, 2),
                dns_resolved_values=resolved_values,
                dns_consistency=consistency,
            )

        except dns.resolver.NXDOMAIN:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="down",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                error_message=f"DNS NXDOMAIN: {host} does not exist",
            )
        except dns.resolver.Timeout:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="timeout",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                error_message=f"DNS timeout after {timeout_seconds}s",
            )
        except Exception as exc:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message=f"DNS error: {type(exc).__name__}: {str(exc)[:200]}",
            )


async def _collect_dns_consistency(
    host: str, record_type: str, timeout_seconds: int
) -> dict | None:
    """V2-02-04 — Query each authoritative NS for the same record and compare.

    Returns a dict with keys ``ns_count``, ``consistent``, ``drift``, and
    ``ns_responses`` (per-NS ``{ns, ip?, values?, ttl?, error?}``), or
    ``None`` if no authoritative NS could be resolved (best-effort).
    """
    import dns.exception  # type: ignore[import]
    import dns.resolver  # type: ignore[import]

    try:
        # Resolve apex domain (drop subdomain) to find authoritative NS.
        # For a host like "api.example.com", we query NS for "example.com".
        labels = host.split(".")
        apex = ".".join(labels[-2:]) if len(labels) >= 2 else host

        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout_seconds
        resolver.cache = dns.resolver.LRUCache(0)

        loop = asyncio.get_running_loop()

        try:
            ns_answer = await asyncio.wait_for(
                loop.run_in_executor(None, resolver.resolve, apex, "NS"),
                timeout=timeout_seconds + 1,
            )
        except Exception:
            return None

        ns_hostnames = [str(r.target).rstrip(".") for r in ns_answer]
        if not ns_hostnames:
            return None

        # Resolve each NS hostname to an IP, then query the record directly against it.
        ns_responses: list[dict] = []
        for ns_host in ns_hostnames[:8]:  # cap to avoid latency on huge NS sets
            try:
                ns_ip_ans = await asyncio.wait_for(
                    loop.run_in_executor(None, resolver.resolve, ns_host, "A"),
                    timeout=timeout_seconds,
                )
                ns_ip = str(ns_ip_ans[0])
            except Exception:
                ns_responses.append({"ns": ns_host, "error": "ns_unresolvable"})
                continue

            per_resolver = dns.resolver.Resolver(configure=False)
            per_resolver.nameservers = [ns_ip]
            per_resolver.lifetime = timeout_seconds
            per_resolver.cache = dns.resolver.LRUCache(0)
            try:
                ans = await asyncio.wait_for(
                    loop.run_in_executor(None, per_resolver.resolve, host, record_type),
                    timeout=timeout_seconds,
                )
                ttl = getattr(ans.rrset, "ttl", None) if ans.rrset else None
                values = sorted(str(r) for r in ans)
                ns_responses.append(
                    {"ns": ns_host, "ip": ns_ip, "values": values, "ttl": ttl}
                )
            except dns.resolver.NXDOMAIN:
                ns_responses.append({"ns": ns_host, "ip": ns_ip, "error": "NXDOMAIN"})
            except Exception as exc:
                ns_responses.append(
                    {"ns": ns_host, "ip": ns_ip, "error": type(exc).__name__}
                )

        # Compute drift: any divergent value sets across the responding NSes.
        value_sets = {tuple(r["values"]) for r in ns_responses if "values" in r}
        ttls = {r["ttl"] for r in ns_responses if r.get("ttl") is not None}
        consistent = len(value_sets) <= 1
        drift_reasons: list[str] = []
        if len(value_sets) > 1:
            drift_reasons.append("value_mismatch")
        if len(ttls) > 1:
            drift_reasons.append("ttl_mismatch")
        unresolved = [r["ns"] for r in ns_responses if "error" in r]
        if unresolved:
            drift_reasons.append("ns_errors")

        return {
            "ns_count": len(ns_hostnames),
            "queried": len(ns_responses),
            "consistent": consistent and not unresolved,
            "drift": drift_reasons,
            "ns_responses": ns_responses,
        }
    except Exception:
        return None


def setup(register):
    register(DNSChecker())
