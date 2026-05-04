"""V2-02-05 — BGP looking-glass parser + cache + verdict gate (unit-level)."""

from __future__ import annotations

from whatisup.api.v1.bgp import _parse_ripestat


def test_parse_ripestat_flattens_rrcs() -> None:
    payload = {
        "data": {
            "rrcs": [
                {
                    "rrc": "RRC00",
                    "location": "Amsterdam",
                    "peers": [
                        {
                            "asn_origin": "13335",
                            "as_path": "3333 3320 13335",
                            "prefix": "1.1.1.0/24",
                        },
                        {
                            "asn_origin": "13335",
                            "as_path": "1299 13335",
                            "prefix": "1.1.1.0/24",
                        },
                    ],
                },
                {
                    "rrc": "RRC03",
                    "location": "Frankfurt",
                    "peers": [
                        {
                            "asn_origin": "13335",
                            "as_path": "6939 13335",
                            "prefix": "1.1.1.0/24",
                        },
                    ],
                },
            ]
        }
    }
    out = _parse_ripestat(payload)
    assert len(out) == 3
    assert {p["rrc"] for p in out} == {"RRC00", "RRC03"}
    assert all(p["peer_asn"] == "13335" for p in out)
    assert out[0]["location"] == "Amsterdam"


def test_parse_ripestat_handles_empty_rrcs() -> None:
    assert _parse_ripestat({"data": {"rrcs": []}}) == []


def test_parse_ripestat_handles_missing_data() -> None:
    assert _parse_ripestat({}) == []


def test_parse_ripestat_handles_missing_peers() -> None:
    payload = {"data": {"rrcs": [{"rrc": "RRC01", "location": "London"}]}}
    assert _parse_ripestat(payload) == []
