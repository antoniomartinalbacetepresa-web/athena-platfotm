"""Synthetic ledger coordination regressions; no quotes, brokers or orders."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import multiprocessing
from threading import Barrier
import time

import pytest

from app.services.recommendation_portfolio_event_ledger_service import (
    PortfolioLedgerEventInput, RecommendationPortfolioEventLedgerService,
)

NOW = datetime(2026, 1, 10, tzinfo=timezone.utc)


def event(index: int = 1, *, shared: bool = False) -> PortfolioLedgerEventInput:
    return PortfolioLedgerEventInput(
        portfolio_id="synthetic-concurrency", event_type="external_cash_flow",
        occurred_at=NOW, available_at=NOW, currency="EUR", amount=100.0 if shared else 100.0 + index,
        instrument_id=None, quantity=None, source="synthetic_fixture",
        source_ref="urn:synthetic:shared" if shared else f"urn:synthetic:event:{index}",
    )


class _SlowInitialReadLedger(RecommendationPortfolioEventLedgerService):
    def _load_unlocked(self):
        records = super()._load_unlocked()
        # Expand read->append without a barrier inside the critical section.
        if not records:
            time.sleep(0.08)
        return records


@pytest.mark.parametrize("shared", [False, True])
def test_separate_instances_serialize_append_and_preserve_replay_identity(tmp_path, shared):
    path = tmp_path / "ledger.jsonl"
    start = Barrier(2)

    def append(index):
        service = _SlowInitialReadLedger(path)
        start.wait(timeout=5)
        return service.append(as_of=NOW, item=event(index, shared=shared))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(append, [1, 2]))
    records = RecommendationPortfolioEventLedgerService(path).load()
    assert len(records) == (1 if shared else 2)
    assert [record.sequence for record in records] == list(range(1, len(records) + 1))
    if shared:
        assert first == second
    else:
        assert records[1].previous_hash == records[0].record_hash


def _process_append(path, start, results, index):
    try:
        start.wait(timeout=10)
        record = _SlowInitialReadLedger(path).append(as_of=NOW, item=event(index))
        results.put(("ok", record.sequence))
    except BaseException as exc:
        results.put(("error", str(exc)))


def test_independent_processes_preserve_one_contiguous_chain(tmp_path):
    path = tmp_path / "process-ledger.jsonl"
    context = multiprocessing.get_context("spawn")
    start = context.Barrier(2)
    results = context.Queue()
    workers = [context.Process(target=_process_append, args=(str(path), start, results, index))
               for index in [1, 2]]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=15)
            assert not worker.is_alive(), "Ledger writer failed to finish"
            assert worker.exitcode == 0
        outputs = [results.get(timeout=3) for _ in workers]
        assert sorted(outputs) == [("ok", 1), ("ok", 2)]
        records = RecommendationPortfolioEventLedgerService(path).load()
        assert len(records) == 2
        assert records[1].previous_hash == records[0].record_hash
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        results.close()
        results.join_thread()


def test_busy_writer_times_out_without_mutating_the_ledger_then_recovers(tmp_path):
    path = tmp_path / "busy.jsonl"
    writer = RecommendationPortfolioEventLedgerService(path)
    contender = RecommendationPortfolioEventLedgerService(path, lock_timeout=0.03)
    with writer._exclusive():
        with pytest.raises(TimeoutError, match="busy"):
            contender.append(as_of=NOW, item=event())
        assert not path.exists()
    assert contender.append(as_of=NOW, item=event()).sequence == 1
    assert len(writer.load()) == 1


def test_missing_read_does_not_create_an_owner_directory(tmp_path):
    path = tmp_path / "absent-owner" / "ledger.jsonl"
    assert RecommendationPortfolioEventLedgerService(path).load() == ()
    assert not path.parent.exists()


def test_reader_waits_for_complete_record_instead_of_parsing_partial_write(tmp_path):
    import json
    from threading import Event

    path = tmp_path / "partial.jsonl"
    writer = RecommendationPortfolioEventLedgerService(path)
    normalized = writer.normalize(as_of=NOW, item=event())
    body = json.dumps({"sequence": 1, "previousHash": writer.GENESIS_HASH,
                       "recordHash": writer._record_hash(1, writer.GENESIS_HASH, normalized),
                       "event": normalized.canonical_dict()})
    partial_ready, finish_write, reader_started = Event(), Event(), Event()

    def write_record():
        with writer._exclusive():
            with path.open("w", encoding="utf-8") as handle:
                handle.write(body[:len(body) // 2])
                handle.flush()
                partial_ready.set()
                assert finish_write.wait(timeout=5)
                handle.write(body[len(body) // 2:] + "\n")
                handle.flush()

    def read_record():
        reader_started.set()
        return RecommendationPortfolioEventLedgerService(path).load()

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending_write = executor.submit(write_record)
        try:
            assert partial_ready.wait(timeout=5)
            pending_read = executor.submit(read_record)
            assert reader_started.wait(timeout=5)
            time.sleep(0.03)
            assert not pending_read.done(), "Reader observed an uncommitted partial record"
        finally:
            finish_write.set()
        pending_write.result(timeout=5)
        records = pending_read.result(timeout=5)
    assert len(records) == 1
    assert records[0].event == normalized


def _hold_until_terminated(path, ready):
    with RecommendationPortfolioEventLedgerService(path)._exclusive():
        ready.put("locked")
        time.sleep(10)


def test_process_failure_releases_os_lock_for_safe_restart(tmp_path):
    path = tmp_path / "restart.jsonl"
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    process = context.Process(target=_hold_until_terminated, args=(str(path), ready))
    try:
        process.start()
        assert ready.get(timeout=5) == "locked"
        process.terminate()
        process.join(timeout=5)
        assert not process.is_alive()
        service = RecommendationPortfolioEventLedgerService(path, lock_timeout=0.5)
        record = service.append(as_of=NOW, item=event())
        assert service.load() == (record,)
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        ready.close()
        ready.join_thread()


def test_concurrent_conflicting_provenance_retains_only_first_observation(tmp_path):
    from dataclasses import replace

    path = tmp_path / "conflict.jsonl"
    start = Barrier(2)

    def append(index):
        service = _SlowInitialReadLedger(path)
        start.wait(timeout=5)
        try:
            service.append(as_of=NOW, item=replace(event(shared=True), amount=100.0 + index))
            return "recorded"
        except ValueError as exc:
            assert "conflicting duplicate provenance" in str(exc)
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(append, [1, 2])) == ["recorded", "rejected"]
    records = RecommendationPortfolioEventLedgerService(path).load()
    assert len(records) == 1
    assert records[0].event.amount in {101.0, 102.0}


@pytest.mark.parametrize("timeout", [-1, float("nan"), float("inf"), True, "1", 61])
def test_invalid_wait_policy_is_rejected_before_storage(tmp_path, timeout):
    path = tmp_path / "invalid-policy.jsonl"
    with pytest.raises(ValueError, match="lock_timeout"):
        RecommendationPortfolioEventLedgerService(path, lock_timeout=timeout)
    assert not path.exists()


def test_account_purge_prevents_a_delayed_writer_from_recreating_private_history(tmp_path):
    from app.security.portfolio_owner_storage import owner_scoped_ledger_path, purge_owner_scoped_ledger

    base = tmp_path / "portfolio.jsonl"
    owner_path = owner_scoped_ledger_path(base, owner_user_id=1)
    other_path = owner_scoped_ledger_path(base, owner_user_id=2)
    delayed_writer = RecommendationPortfolioEventLedgerService(owner_path)
    delayed_writer.append(as_of=NOW, item=event())
    other = RecommendationPortfolioEventLedgerService(other_path)
    other_record = other.append(as_of=NOW, item=event(2))
    assert purge_owner_scoped_ledger(base, owner_user_id=1) is True
    with pytest.raises(ValueError, match="closed"):
        delayed_writer.append(as_of=NOW, item=event(3))
    assert not owner_path.exists()
    assert delayed_writer.load() == ()
    assert other.load() == (other_record,)
    assert purge_owner_scoped_ledger(base, owner_user_id=1) is False


def test_account_purge_blocks_delayed_first_append_even_when_no_ledger_existed(tmp_path):
    from app.security.portfolio_owner_storage import owner_scoped_ledger_path, purge_owner_scoped_ledger

    base = tmp_path / "portfolio.jsonl"
    path = owner_scoped_ledger_path(base, owner_user_id=1)
    delayed_writer = RecommendationPortfolioEventLedgerService(path)
    assert purge_owner_scoped_ledger(base, owner_user_id=1) is False
    with pytest.raises(ValueError, match="closed"):
        delayed_writer.append(as_of=NOW, item=event())
    assert not path.exists()


def test_account_purge_waits_for_active_writer_and_keeps_new_instances_closed(tmp_path):
    from threading import Event
    from app.security.portfolio_owner_storage import owner_scoped_ledger_path, purge_owner_scoped_ledger

    base = tmp_path / "portfolio.jsonl"
    path = owner_scoped_ledger_path(base, owner_user_id=1)
    writer = RecommendationPortfolioEventLedgerService(path)
    writer.append(as_of=NOW, item=event())
    purge_started = Event()

    def purge():
        purge_started.set()
        return purge_owner_scoped_ledger(base, owner_user_id=1)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with writer._exclusive():
            result = executor.submit(purge)
            assert purge_started.wait(timeout=2)
            time.sleep(0.03)
            assert not result.done()
            assert path.exists()
        assert result.result(timeout=2) is True
    restarted = RecommendationPortfolioEventLedgerService(path)
    with pytest.raises(ValueError, match="closed"):
        restarted.append(as_of=NOW, item=event(2))
    assert restarted.load() == ()
    assert not path.exists()
