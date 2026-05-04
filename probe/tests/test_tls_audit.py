"""V2-02-03 — TLS audit grade matrix + SAN matching."""

from __future__ import annotations

from whatisup_probe.checkers._shared import _grade_tls, _hostname_matches_san

# ── Grade matrix ──────────────────────────────────────────────────────────────


def _base_audit(**overrides) -> dict:
    base = {
        "tls_version": "TLSv1.3",
        "cipher_aead": True,
        "san_match": True,
        "sct_present": True,
        "key_type": "rsa",
        "key_size_bits": 2048,
        "is_self_signed": False,
        "days_remaining": 60,
    }
    base.update(overrides)
    return base


def test_grade_a_for_tls13_aead_san_sct() -> None:
    assert _grade_tls(_base_audit()) == "A"


def test_grade_a_plus_for_long_lived_strong_key() -> None:
    audit = _base_audit(key_size_bits=4096, days_remaining=120)
    assert _grade_tls(audit) == "A+"


def test_grade_a_plus_for_ec_384() -> None:
    audit = _base_audit(key_type="ec", key_size_bits=384, days_remaining=120)
    assert _grade_tls(audit) == "A+"


def test_grade_b_for_tls12_aead() -> None:
    audit = _base_audit(tls_version="TLSv1.2")
    assert _grade_tls(audit) == "B"


def test_grade_c_for_missing_sct() -> None:
    audit = _base_audit(sct_present=False)
    assert _grade_tls(audit) == "C"


def test_grade_c_for_short_expiry() -> None:
    audit = _base_audit(days_remaining=10)
    assert _grade_tls(audit) == "C"


def test_grade_d_for_tls12_non_aead() -> None:
    audit = _base_audit(tls_version="TLSv1.2", cipher_aead=False)
    assert _grade_tls(audit) == "D"


def test_grade_e_for_tls11() -> None:
    audit = _base_audit(tls_version="TLSv1.1")
    assert _grade_tls(audit) == "E"


def test_grade_f_for_self_signed() -> None:
    audit = _base_audit(is_self_signed=True)
    assert _grade_tls(audit) == "F"


def test_grade_f_for_san_mismatch() -> None:
    audit = _base_audit(san_match=False)
    assert _grade_tls(audit) == "F"


# ── SAN wildcard matching (RFC 6125) ──────────────────────────────────────────


def test_san_exact_match() -> None:
    assert _hostname_matches_san("api.example.com", ["api.example.com"]) is True


def test_san_case_insensitive() -> None:
    assert _hostname_matches_san("API.example.com", ["api.example.com"]) is True


def test_san_wildcard_matches_one_label() -> None:
    assert _hostname_matches_san("api.example.com", ["*.example.com"]) is True


def test_san_wildcard_does_not_match_apex() -> None:
    assert _hostname_matches_san("example.com", ["*.example.com"]) is False


def test_san_wildcard_does_not_match_two_labels() -> None:
    assert _hostname_matches_san("a.b.example.com", ["*.example.com"]) is False


def test_san_no_match_returns_false() -> None:
    assert _hostname_matches_san("evil.com", ["example.com", "*.example.com"]) is False
