"""SA3 — FERNET_KEY rotation: MultiFernet decryption + rotate_fernet tool.

Never asserts on (nor prints) real secrets in reports — but test plaintexts
here are dummy values, safe to compare in assertions.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.core.security import (
    decrypt_channel_config,
    decrypt_scenario_variables,
    decrypt_secret_str,
    encrypt_channel_config,
    encrypt_scenario_variables,
    encrypt_secret_str,
)
from whatisup.models.alert import AlertChannel, AlertChannelType
from whatisup.models.monitor import Monitor
from whatisup.models.system_settings import SystemSettings
from whatisup.models.user import User
from whatisup.tools.rotate_fernet import rotate

KEY_A = Fernet.generate_key().decode()  # old key
KEY_B = Fernet.generate_key().decode()  # new primary key
KEY_C = Fernet.generate_key().decode()  # a second old key


def _use_keys(monkeypatch, primary: str, previous: str = "") -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "fernet_key", primary)
    monkeypatch.setattr(settings, "fernet_key_previous", previous)


# ── MultiFernet decryption (no DB) ────────────────────────────────────────────


def test_decrypt_with_previous_key_after_switch(monkeypatch):
    _use_keys(monkeypatch, KEY_A)
    enc = encrypt_channel_config({"bot_token": "dummy-token", "chat_id": "42"})
    assert enc["bot_token"] != "dummy-token"

    # Switch: B becomes primary, A kept as previous key
    _use_keys(monkeypatch, KEY_B, previous=KEY_A)
    dec = decrypt_channel_config(enc)
    assert dec["bot_token"] == "dummy-token"
    assert dec["chat_id"] == "42"


def test_encrypt_always_uses_primary_key(monkeypatch):
    _use_keys(monkeypatch, KEY_B, previous=KEY_A)
    enc = encrypt_channel_config({"bot_token": "dummy-token"})
    # Decryptable by the new primary key alone...
    assert Fernet(KEY_B.encode()).decrypt(enc["bot_token"].encode()) == b"dummy-token"
    # ...and NOT by the previous key.
    with pytest.raises(InvalidToken):
        Fernet(KEY_A.encode()).decrypt(enc["bot_token"].encode())


def test_decrypt_with_multiple_previous_keys(monkeypatch):
    _use_keys(monkeypatch, KEY_A)
    secret_a = encrypt_secret_str("totp-under-a")
    _use_keys(monkeypatch, KEY_C)
    secret_c = encrypt_secret_str("totp-under-c")

    _use_keys(monkeypatch, KEY_B, previous=f"{KEY_A},{KEY_C}")
    assert decrypt_secret_str(secret_a) == "totp-under-a"
    assert decrypt_secret_str(secret_c) == "totp-under-c"


def test_fernet_previous_keys_parsing(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "fernet_key_previous", f" {KEY_A} , ,{KEY_C},")
    assert settings.fernet_previous_keys == [KEY_A, KEY_C]
    monkeypatch.setattr(settings, "fernet_key_previous", "")
    assert settings.fernet_previous_keys == []


# ── rotate_fernet tool (DB) ───────────────────────────────────────────────────


@pytest.fixture
async def seeded(db_session: AsyncSession, test_user: User, monkeypatch):
    """Rows encrypted under KEY_A, then settings switched to KEY_B (+A previous)."""
    _use_keys(monkeypatch, KEY_A)
    channel = AlertChannel(
        owner_id=test_user.id,
        name="tg",
        type=AlertChannelType.telegram,
        config=encrypt_channel_config({"bot_token": "dummy-token", "chat_id": "42"}),
    )
    plain_channel = AlertChannel(
        owner_id=test_user.id,
        name="legacy",
        type=AlertChannelType.telegram,
        # Legacy plaintext value — no configured key decrypts it.
        config={"bot_token": "legacy-plaintext", "chat_id": "1"},
    )
    monitor = Monitor(
        name="scn",
        url="http://example.com",
        owner_id=test_user.id,
        scenario_variables=encrypt_scenario_variables(
            [
                {"name": "PASS", "value": "dummy-pass", "secret": True},
                {"name": "BASE", "value": "http://example.com", "secret": False},
            ]
        ),
    )
    test_user.totp_secret = encrypt_secret_str("dummy-totp")
    sysrow = SystemSettings(
        id=1,
        oidc_client_secret=Fernet(KEY_A.encode()).encrypt(b"dummy-oidc").decode(),
    )
    db_session.add_all([channel, plain_channel, monitor, sysrow])
    await db_session.flush()

    _use_keys(monkeypatch, KEY_B, previous=KEY_A)
    return channel, plain_channel, monitor, sysrow


async def test_rotate_reencrypts_all_stores(db_session, test_user, seeded):
    channel, plain_channel, monitor, sysrow = seeded
    old_token_ct = channel.config["bot_token"]
    old_var_ct = monitor.scenario_variables[0]["value"]
    fernet_a = Fernet(KEY_A.encode())
    fernet_b = Fernet(KEY_B.encode())

    report = await rotate(db_session, dry_run=False)

    # 4 values rotated: bot_token + scenario PASS + totp_secret + oidc secret
    assert report.total_rotated == 4
    assert report.stores["alert_channels.config"].rotated == 1
    assert report.stores["alert_channels.config"].unreadable == 1  # legacy plaintext
    assert report.stores["monitors.scenario_variables"].rotated == 1
    assert report.stores["users.totp_secret"].rotated == 1
    assert report.stores["system_settings.oidc_client_secret"].rotated == 1

    # Ciphertext changed, now decryptable by the new primary key ONLY,
    # and the decrypted plaintext is identical.
    assert channel.config["bot_token"] != old_token_ct
    assert fernet_b.decrypt(channel.config["bot_token"].encode()) == b"dummy-token"
    with pytest.raises(InvalidToken):
        fernet_a.decrypt(channel.config["bot_token"].encode())
    assert channel.config["chat_id"] == "42"  # non-secret field untouched

    assert monitor.scenario_variables[0]["value"] != old_var_ct
    assert decrypt_scenario_variables(monitor.scenario_variables)[0]["value"] == "dummy-pass"
    assert monitor.scenario_variables[1]["value"] == "http://example.com"  # non-secret

    assert fernet_b.decrypt(test_user.totp_secret.encode()) == b"dummy-totp"
    assert fernet_b.decrypt(sysrow.oidc_client_secret.encode()) == b"dummy-oidc"

    # Legacy plaintext left strictly untouched
    assert plain_channel.config["bot_token"] == "legacy-plaintext"


async def test_rotate_is_idempotent(db_session, seeded):
    channel, _plain, monitor, sysrow = seeded
    first = await rotate(db_session, dry_run=False)
    assert first.total_rotated == 4
    token_ct = channel.config["bot_token"]
    var_ct = monitor.scenario_variables[0]["value"]
    oidc_ct = sysrow.oidc_client_secret

    second = await rotate(db_session, dry_run=False)

    assert second.total_rotated == 0
    assert second.stores["alert_channels.config"].current == 1
    assert channel.config["bot_token"] == token_ct
    assert monitor.scenario_variables[0]["value"] == var_ct
    assert sysrow.oidc_client_secret == oidc_ct


async def test_rotate_dry_run_writes_nothing(db_session, seeded):
    channel, _plain, monitor, sysrow = seeded
    old_token_ct = channel.config["bot_token"]
    old_var_ct = monitor.scenario_variables[0]["value"]
    old_oidc_ct = sysrow.oidc_client_secret

    report = await rotate(db_session, dry_run=True)

    # Reports what WOULD be rotated...
    assert report.dry_run is True
    assert report.total_rotated == 4
    assert "DRY RUN" in report.summary()
    # ...but nothing changed, in the ORM objects nor in the DB.
    assert channel.config["bot_token"] == old_token_ct
    assert monitor.scenario_variables[0]["value"] == old_var_ct
    assert sysrow.oidc_client_secret == old_oidc_ct
    db_row = (
        await db_session.execute(select(AlertChannel.config).where(AlertChannel.id == channel.id))
    ).scalar_one()
    assert db_row["bot_token"] == old_token_ct


async def test_rotate_requires_fernet_key(db_session, monkeypatch):
    _use_keys(monkeypatch, "")
    with pytest.raises(RuntimeError, match="FERNET_KEY"):
        await rotate(db_session)


def test_report_summary_never_contains_secrets(monkeypatch):
    # The summary is pure counters — belt and braces.
    from whatisup.tools.rotate_fernet import RotationReport, StoreReport

    report = RotationReport(dry_run=False, stores={"x": StoreReport(scanned=2, rotated=1)})
    assert "dummy" not in report.summary()
    assert "1 rotated" in report.summary()


def test_main_exit_code(monkeypatch):
    """main() must exit non-zero when any value stays unreadable, 0 otherwise."""
    import whatisup.tools.rotate_fernet as rf

    _use_keys(monkeypatch, KEY_B)  # fernet_key set → main() proceeds

    state = {"unreadable": 0}

    def _fake_asyncio_run(_coro):
        return rf.RotationReport(
            dry_run=False,
            stores={"x": rf.StoreReport(scanned=2, rotated=1, unreadable=state["unreadable"])},
        )

    monkeypatch.setattr(rf, "_run", lambda dry_run: None)
    monkeypatch.setattr(rf.asyncio, "run", _fake_asyncio_run)

    state["unreadable"] = 0
    assert rf.main([]) == 0

    state["unreadable"] = 1
    assert rf.main([]) == 1
