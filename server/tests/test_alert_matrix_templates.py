"""Coverage for the alert-matrix template catalog."""

from __future__ import annotations

import pytest

from whatisup.services.alert_matrix_templates import TEMPLATES, get_templates


def test_every_check_type_has_three_named_templates() -> None:
    """Each supported check_type ships standard / strict / silent presets."""
    for check_type in TEMPLATES:
        ids = {tpl["id"] for tpl in TEMPLATES[check_type]}
        assert ids == {"standard", "strict", "silent"}, check_type


def test_template_rows_carry_a_condition() -> None:
    for check_type, tpls in TEMPLATES.items():
        for tpl in tpls:
            assert tpl["rows"], f"{check_type}/{tpl['id']} has no rows"
            for row in tpl["rows"]:
                assert row.get("condition"), tpl["id"]


@pytest.mark.parametrize("check_type", ["http", "tcp", "dns", "heartbeat"])
def test_get_templates_returns_known_set(check_type: str) -> None:
    out = get_templates(check_type)
    assert out is TEMPLATES[check_type]


def test_get_templates_falls_back_to_http_for_unknown() -> None:
    out = get_templates("does-not-exist")
    assert out is TEMPLATES["http"]


def test_http_strict_has_more_rows_than_silent() -> None:
    """Sanity: aggressive preset can't be lighter than the silent one."""
    strict = get_templates("http")[1]
    silent = get_templates("http")[2]
    assert len(strict["rows"]) > len(silent["rows"])
