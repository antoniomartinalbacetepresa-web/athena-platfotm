"""Regression tests for one-generation, atomic paired operational diagnostics."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from scripts import export_operational_history_bundle as bundle

CUTOFF = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def _seed(tmp_path):
    source = tmp_path / "fixture.db"
    database = AthenaDatabase(source)
    database.initialize()
    with database.connect() as connection:
        instrument_id = connection.execute(
            "INSERT INTO instruments (symbol, company_name, exchange_short_name, instrument_type) "
            "VALUES ('ONLY', 'Only', 'NASDAQ', 'common_stock')"
        ).lastrowid
    CorporateActionRepository(database).save_many(
        instrument_id=instrument_id, source_provider="yahoo",
        retrieved_at=CUTOFF - timedelta(days=1),
        actions=[{
            "type": "dividend",
            "effectiveAt": (CUTOFF - timedelta(days=30)).isoformat(),
            "cashAmount": 0.25, "currency": "USD",
        }],
    )
    return source


def test_paired_bundle_has_both_complete_reports_and_hashes(tmp_path):
    source = _seed(tmp_path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "evidence.zip"
    result = bundle.export_operational_history_bundle(
        database_path=source, output_path=output, as_of=CUTOFF, history_page_size=1,
    )
    assert result["eligibleInstrumentCount"] == 1
    assert result["historyBlockingCount"] == 1
    assert result["corporateActionUnresolvedCount"] == 1
    assert result["operationalOriginVerified"] is False
    assert result["bundleSha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert before == hashlib.sha256(source.read_bytes()).hexdigest()
    assert output.stat().st_mode & 0o077 == 0
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read(bundle.MANIFEST_MEMBER))
        history = [json.loads(row) for row in archive.read(bundle.HISTORY_MEMBER).splitlines()]
        actions = [json.loads(row) for row in archive.read(bundle.ACTIONS_MEMBER).splitlines()]
        assert manifest["sameSourceGeneration"] is True
        assert manifest["sourceGenerationSha256"] == result["sourceGenerationSha256"]
        assert manifest["productionCoverageClaimed"] is False
        assert manifest["independentProviderAgreementVerified"] is False
        assert len(history) == 2 and history[1]["symbol"] == "ONLY"
        assert len(actions) == 2 and actions[1]["symbol"] == "ONLY"
        for name, digest in manifest["members"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest


def test_second_export_failure_does_not_publish_half_bundle(tmp_path, monkeypatch):
    source = _seed(tmp_path)
    output = tmp_path / "absent.zip"

    def unavailable(**kwargs):
        raise RuntimeError("reconciliation unavailable")

    monkeypatch.setattr(bundle, "export_worklist", unavailable)
    with pytest.raises(RuntimeError, match="unavailable"):
        bundle.export_operational_history_bundle(
            database_path=source, output_path=output, as_of=CUTOFF,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".athena-paired-*"))


def test_refuses_overwrite_and_future_cutoff(tmp_path):
    source = _seed(tmp_path)
    output = tmp_path / "existing.zip"
    output.write_text("previous evidence")
    with pytest.raises(FileExistsError):
        bundle.export_operational_history_bundle(
            database_path=source, output_path=output, as_of=CUTOFF,
        )
    assert output.read_text() == "previous evidence"
    with pytest.raises(ValueError, match="future"):
        bundle.export_operational_history_bundle(
            database_path=source, output_path=tmp_path / "future.zip",
            as_of=datetime.now(timezone.utc) + timedelta(days=1),
        )


def test_live_database_write_after_freeze_cannot_mix_generations(tmp_path, monkeypatch):
    source = _seed(tmp_path)
    original = bundle.export_worklist

    def update_live_source(**kwargs):
        with sqlite3.connect(source) as connection:
            connection.execute(
                "INSERT INTO instruments (symbol, company_name, exchange_short_name, instrument_type) "
                "VALUES ('LATE', 'Late', 'NASDAQ', 'common_stock')"
            )
        return original(**kwargs)

    monkeypatch.setattr(bundle, "export_worklist", update_live_source)
    output = tmp_path / "frozen.zip"
    result = bundle.export_operational_history_bundle(
        database_path=source, output_path=output, as_of=CUTOFF,
    )
    assert result["eligibleInstrumentCount"] == 1
    with zipfile.ZipFile(output) as archive:
        assert b"LATE" not in archive.read(bundle.HISTORY_MEMBER)
        assert b"LATE" not in archive.read(bundle.ACTIONS_MEMBER)


@pytest.mark.parametrize("corrupt_child", ["history", "actions"])
def test_paired_bundle_rejects_rehashed_incomplete_child_reports(
    tmp_path, monkeypatch, corrupt_child,
):
    """A child summary and its SHA can agree while JSONL rows are missing."""
    source = _seed(tmp_path)
    output = tmp_path / "should-not-publish.zip"
    name = "export_history_gaps" if corrupt_child == "history" else "export_worklist"
    original = getattr(bundle, name)

    def truncate_rows(**kwargs):
        summary = original(**kwargs)
        path = kwargs["output_path"]
        metadata_line = path.read_text(encoding="utf-8").splitlines(keepends=True)[0]
        path.write_text(metadata_line, encoding="utf-8")
        summary["exportSha256"] = bundle._sha256_file(path)
        return summary

    monkeypatch.setattr(bundle, name, truncate_rows)
    with pytest.raises(RuntimeError, match="rows do not match claimed totals"):
        bundle.export_operational_history_bundle(
            database_path=source, output_path=output, as_of=CUTOFF,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".athena-paired-*"))


def test_paired_bundle_rejects_rehashed_misclassified_action(tmp_path, monkeypatch):
    source = _seed(tmp_path)
    output = tmp_path / "should-not-publish.zip"
    original = bundle.export_worklist

    def relabel_action(**kwargs):
        summary = original(**kwargs)
        path = kwargs["output_path"]
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[1]["reconciliationStatus"] = "conflict"
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        summary["exportSha256"] = bundle._sha256_file(path)
        return summary

    monkeypatch.setattr(bundle, "export_worklist", relabel_action)
    with pytest.raises(RuntimeError, match="rows do not match claimed totals"):
        bundle.export_operational_history_bundle(
            database_path=source, output_path=output, as_of=CUTOFF,
        )
    assert not output.exists()


