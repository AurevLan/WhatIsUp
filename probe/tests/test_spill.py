"""Tests for the disk spill buffer and its reporter integration."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

import whatisup_probe.reporter as reporter_module
import whatisup_probe.spill as spill_module
from whatisup_probe.checkers import CheckResult
from whatisup_probe.reporter import Reporter
from whatisup_probe.spill import DiskSpill

# ── DiskSpill unit tests ──────────────────────────────────────────────────────


def test_spill_append_and_pop_fifo(tmp_path) -> None:
    spill = DiskSpill(path=str(tmp_path / "spill.jsonl"))
    spill.append({"monitor_id": "a"})
    spill.append({"monitor_id": "b"})
    spill.append({"monitor_id": "c"})

    batch = spill.pop_batch(2)
    assert [p["monitor_id"] for p in batch] == ["a", "b"]
    assert spill.pending_count() == 1

    rest = spill.pop_batch(10)
    assert [p["monitor_id"] for p in rest] == ["c"]
    assert spill.pending_count() == 0


def test_spill_pop_empty(tmp_path) -> None:
    spill = DiskSpill(path=str(tmp_path / "missing.jsonl"))
    assert spill.pop_batch(5) == []
    assert spill.pending_count() == 0


def test_spill_skips_corrupted_lines(tmp_path) -> None:
    path = tmp_path / "spill.jsonl"
    path.write_text('{"monitor_id": "ok"}\nnot-json{\n{"monitor_id": "ok2"}\n')
    spill = DiskSpill(path=str(path))

    batch = spill.pop_batch(10)
    assert [p["monitor_id"] for p in batch] == ["ok", "ok2"]


def test_spill_evicts_oldest_when_over_cap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(spill_module, "_COMPACT_THRESHOLD_BYTES", 1)
    spill = DiskSpill(path=str(tmp_path / "spill.jsonl"), max_entries=3)
    for i in range(6):
        spill.append({"monitor_id": f"m{i}"})

    batch = spill.pop_batch(10)
    # Only the 3 newest survive
    assert [p["monitor_id"] for p in batch] == ["m3", "m4", "m5"]


# ── Reporter integration ──────────────────────────────────────────────────────


def _result(mid: str = "mon-1") -> CheckResult:
    return CheckResult(monitor_id=mid, checked_at=datetime.now(UTC), status="up")


@pytest.mark.asyncio
async def test_push_result_spills_when_queue_full(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RESULT_SPILL_PATH", str(tmp_path / "spill.jsonl"))
    monkeypatch.setattr(reporter_module, "_QUEUE_MAX_SIZE", 2)
    reporter = Reporter()
    reporter._queue = asyncio.Queue(maxsize=2)

    await reporter.push_result(_result("a"))
    await reporter.push_result(_result("b"))
    await reporter.push_result(_result("overflow"))

    assert reporter._spill.pending_count() == 1
    spilled = reporter._spill.pop_batch(1)
    assert spilled[0]["monitor_id"] == "overflow"
    await reporter._client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_flush_spills_on_transient_failure(tmp_path, monkeypatch) -> None:
    """Network failure after retries → payload lands in the spill file."""
    monkeypatch.setenv("RESULT_SPILL_PATH", str(tmp_path / "spill.jsonl"))
    respx.post("http://localhost:8000/api/v1/probes/results").mock(
        side_effect=httpx.ConnectError("refused")
    )
    reporter = Reporter()
    # Skip the retry sleeps to keep the test fast
    monkeypatch.setattr(reporter_module.random, "uniform", lambda *_: 0)

    await reporter.push_result(_result("down-net"))
    await reporter._flush_batch()

    assert reporter._spill.pending_count() == 1
    assert reporter._spill.pop_batch(1)[0]["monitor_id"] == "down-net"
    await reporter._client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_flush_drops_on_permanent_rejection(tmp_path, monkeypatch) -> None:
    """A 4xx rejection must NOT be spilled (it would never succeed)."""
    monkeypatch.setenv("RESULT_SPILL_PATH", str(tmp_path / "spill.jsonl"))
    respx.post("http://localhost:8000/api/v1/probes/results").mock(return_value=httpx.Response(403))
    reporter = Reporter()

    await reporter.push_result(_result("rejected"))
    await reporter._flush_batch()

    assert reporter._spill.pending_count() == 0
    await reporter._client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_flush_resends_spilled_results(tmp_path, monkeypatch) -> None:
    """Spilled results are re-sent once the API is reachable again."""
    monkeypatch.setenv("RESULT_SPILL_PATH", str(tmp_path / "spill.jsonl"))
    monkeypatch.setattr(reporter_module, "_SPILL_RETRY_EVERY", 1)
    route = respx.post("http://localhost:8000/api/v1/probes/results").mock(
        return_value=httpx.Response(200)
    )
    reporter = Reporter()
    reporter._spill.append(_result("from-disk").to_dict())

    await reporter._flush_batch()

    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert body["monitor_id"] == "from-disk"
    assert reporter._spill.pending_count() == 0
    await reporter._client.aclose()
