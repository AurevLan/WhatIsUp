"""V2-02-04 — DNS authoritative consistency collection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from whatisup_probe.checkers.dns import _collect_dns_consistency


def _make_rrset(values: list[str], ttl: int = 300):
    rrset = MagicMock()
    rrset.ttl = ttl
    return rrset


def _make_answer(values: list[str], ttl: int = 300):
    """Build a mock dns.resolver.Answer iterable."""
    ans = MagicMock()
    ans.rrset = _make_rrset(values, ttl)
    ans.__iter__ = lambda self: iter([MagicMock(__str__=lambda self, v=v: v) for v in values])
    ans.__getitem__ = lambda self, i: MagicMock(__str__=lambda self, v=values[i]: v)
    return ans


@pytest.mark.asyncio
async def test_consistency_all_ns_agree() -> None:
    ns_target = MagicMock()
    ns_target.target = MagicMock(__str__=lambda self: "ns1.example.com.")
    ns_target2 = MagicMock()
    ns_target2.target = MagicMock(__str__=lambda self: "ns2.example.com.")
    ns_answer = MagicMock()
    ns_answer.__iter__ = lambda self: iter([ns_target, ns_target2])

    a_rec = _make_answer(["1.2.3.4"], ttl=300)
    ns_ip = _make_answer(["192.0.2.1"])

    call_count = {"n": 0}

    def fake_resolve(host, rtype):  # noqa: ARG001
        call_count["n"] += 1
        if rtype == "NS":
            return ns_answer
        if rtype == "A" and host.startswith("ns"):
            return ns_ip
        return a_rec

    with patch("dns.resolver.Resolver") as MockRes:
        instance = MockRes.return_value
        instance.resolve = fake_resolve
        instance.cache = None
        instance.lifetime = 5
        instance.nameservers = []
        result = await _collect_dns_consistency("api.example.com", "A", 5)

    assert result is not None
    assert result["consistent"] is True
    assert result["drift"] == []
    assert result["queried"] == 2


@pytest.mark.asyncio
async def test_consistency_value_mismatch_flags_drift() -> None:
    ns_target = MagicMock()
    ns_target.target = MagicMock(__str__=lambda self: "ns1.example.com.")
    ns_target2 = MagicMock()
    ns_target2.target = MagicMock(__str__=lambda self: "ns2.example.com.")
    ns_answer = MagicMock()
    ns_answer.__iter__ = lambda self: iter([ns_target, ns_target2])

    ns_ip = _make_answer(["192.0.2.1"])
    answers_seq = iter([_make_answer(["1.2.3.4"]), _make_answer(["9.9.9.9"])])

    def fake_resolve(host, rtype):  # noqa: ARG001
        if rtype == "NS":
            return ns_answer
        if rtype == "A" and host.startswith("ns"):
            return ns_ip
        return next(answers_seq)

    with patch("dns.resolver.Resolver") as MockRes:
        instance = MockRes.return_value
        instance.resolve = fake_resolve
        instance.cache = None
        instance.lifetime = 5
        instance.nameservers = []
        result = await _collect_dns_consistency("api.example.com", "A", 5)

    assert result is not None
    assert result["consistent"] is False
    assert "value_mismatch" in result["drift"]


@pytest.mark.asyncio
async def test_consistency_returns_none_when_ns_unresolvable() -> None:
    def fake_resolve(host, rtype):  # noqa: ARG001
        raise Exception("nope")

    with patch("dns.resolver.Resolver") as MockRes:
        instance = MockRes.return_value
        instance.resolve = fake_resolve
        instance.cache = None
        instance.lifetime = 5
        instance.nameservers = []
        result = await _collect_dns_consistency("api.example.com", "A", 5)

    assert result is None


@pytest.mark.asyncio
async def test_consistency_marks_per_ns_error_when_query_fails() -> None:
    ns_target = MagicMock()
    ns_target.target = MagicMock(__str__=lambda self: "ns1.example.com.")
    ns_target2 = MagicMock()
    ns_target2.target = MagicMock(__str__=lambda self: "ns2.example.com.")
    ns_answer = MagicMock()
    ns_answer.__iter__ = lambda self: iter([ns_target, ns_target2])

    ns_ip = _make_answer(["192.0.2.1"])
    a_rec = _make_answer(["1.2.3.4"])
    side_effects = iter([a_rec, Exception("ServFail")])

    def fake_resolve(host, rtype):  # noqa: ARG001
        if rtype == "NS":
            return ns_answer
        if rtype == "A" and host.startswith("ns"):
            return ns_ip
        try:
            v = next(side_effects)
        except StopIteration:
            return a_rec
        if isinstance(v, Exception):
            raise v
        return v

    with patch("dns.resolver.Resolver") as MockRes:
        instance = MockRes.return_value
        instance.resolve = fake_resolve
        instance.cache = None
        instance.lifetime = 5
        instance.nameservers = []
        result = await _collect_dns_consistency("api.example.com", "A", 5)

    assert result is not None
    assert "ns_errors" in result["drift"]
    assert result["consistent"] is False
