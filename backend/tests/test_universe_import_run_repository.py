from __future__ import annotations

from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.universe_import_run_repository import (
    UniverseImportRunRepository,
)


def _create_repository(
    tmp_path: Path,
) -> tuple[
    AthenaDatabase,
    UniverseImportRunRepository,
]:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    repository = UniverseImportRunRepository(
        database=database
    )

    return database, repository


def test_start_run_creates_running_record(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "NASDAQ_TRADER",
        started_at=(
            "2026-09-01T00:00:00+00:00"
        ),
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None
    assert row["id"] == run_id
    assert row["source_id"] == "nasdaq_trader"
    assert row["status"] == "running"
    assert row["received"] == 0
    assert row["accepted"] == 0
    assert row["rejected"] == 0
    assert row["created_or_updated"] == 0
    assert (
        row["started_at"]
        == "2026-09-01T00:00:00+00:00"
    )
    assert row["completed_at"] is None
    assert row["error_message"] is None


def test_start_run_rejects_empty_source_id(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match="source_id es obligatorio",
    ):
        repository.start_run(
            "   "
        )


def test_mark_succeeded_finalizes_running_record(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader",
        started_at=(
            "2026-09-01T00:00:00+00:00"
        ),
    )

    repository.mark_succeeded(
        run_id,
        received=13141,
        accepted=13141,
        rejected=0,
        created_or_updated=13141,
        completed_at=(
            "2026-09-01T00:01:00+00:00"
        ),
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None
    assert row["status"] == "succeeded"
    assert row["received"] == 13141
    assert row["accepted"] == 13141
    assert row["rejected"] == 0
    assert row["created_or_updated"] == 13141
    assert (
        row["completed_at"]
        == "2026-09-01T00:01:00+00:00"
    )
    assert row["error_message"] is None


def test_mark_failed_finalizes_running_record(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader",
        started_at=(
            "2026-09-01T00:00:00+00:00"
        ),
    )

    repository.mark_failed(
        run_id,
        error_message=(
            "La fuente respondió con HTTP 503."
        ),
        received=100,
        accepted=90,
        rejected=10,
        created_or_updated=0,
        completed_at=(
            "2026-09-01T00:01:00+00:00"
        ),
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None
    assert row["status"] == "failed"
    assert row["received"] == 100
    assert row["accepted"] == 90
    assert row["rejected"] == 10
    assert row["created_or_updated"] == 0
    assert (
        row["completed_at"]
        == "2026-09-01T00:01:00+00:00"
    )
    assert (
        row["error_message"]
        == "La fuente respondió con HTTP 503."
    )


def test_mark_succeeded_cannot_finalize_twice(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    repository.mark_succeeded(
        run_id,
        received=1,
        accepted=1,
        rejected=0,
        created_or_updated=1,
    )

    with pytest.raises(
        ValueError,
        match=(
            "La ejecución no existe "
            "o ya está finalizada"
        ),
    ):
        repository.mark_succeeded(
            run_id,
            received=1,
            accepted=1,
            rejected=0,
            created_or_updated=1,
        )


def test_mark_failed_cannot_finalize_twice(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    repository.mark_failed(
        run_id,
        error_message="Fallo inicial.",
    )

    with pytest.raises(
        ValueError,
        match=(
            "La ejecución no existe "
            "o ya está finalizada"
        ),
    ):
        repository.mark_failed(
            run_id,
            error_message="Segundo fallo.",
        )


def test_mark_succeeded_rejects_negative_received(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    with pytest.raises(
        ValueError,
        match="received no puede ser negativo",
    ):
        repository.mark_succeeded(
            run_id,
            received=-1,
            accepted=0,
            rejected=0,
            created_or_updated=0,
        )


def test_mark_succeeded_rejects_inconsistent_counts(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    with pytest.raises(
        ValueError,
        match=(
            "accepted \\+ rejected "
            "no puede superar received"
        ),
    ):
        repository.mark_succeeded(
            run_id,
            received=10,
            accepted=8,
            rejected=3,
            created_or_updated=8,
        )


def test_mark_succeeded_rejects_created_above_accepted(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    with pytest.raises(
        ValueError,
        match=(
            "created_or_updated "
            "no puede superar accepted"
        ),
    ):
        repository.mark_succeeded(
            run_id,
            received=10,
            accepted=8,
            rejected=2,
            created_or_updated=9,
        )


def test_mark_failed_requires_error_message(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    with pytest.raises(
        ValueError,
        match="error_message es obligatorio",
    ):
        repository.mark_failed(
            run_id,
            error_message="   ",
        )


def test_get_by_id_returns_none_when_missing(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    assert (
        repository.get_by_id(999)
        is None
    )


def test_get_by_id_rejects_non_positive_id(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match=(
            "run_id debe ser mayor que cero"
        ),
    ):
        repository.get_by_id(
            0
        )


def test_latest_for_source_returns_most_recent_run(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    first_id = repository.start_run(
        "nasdaq_trader",
        started_at=(
            "2026-09-01T00:00:00+00:00"
        ),
    )

    repository.mark_succeeded(
        first_id,
        received=10,
        accepted=10,
        rejected=0,
        created_or_updated=10,
        completed_at=(
            "2026-09-01T00:01:00+00:00"
        ),
    )

    second_id = repository.start_run(
        "NASDAQ_TRADER",
        started_at=(
            "2026-09-01T01:00:00+00:00"
        ),
    )

    latest = repository.latest_for_source(
        "Nasdaq_Trader"
    )

    assert latest is not None
    assert latest["id"] == second_id
    assert latest["status"] == "running"


def test_latest_for_source_returns_none_when_missing(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    assert (
        repository.latest_for_source(
            "unknown_source"
        )
        is None
    )


def test_latest_for_source_rejects_empty_source_id(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match="source_id es obligatorio",
    ):
        repository.latest_for_source(
            "   "
        )


def test_mark_failed_can_preserve_partial_progress(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    repository.mark_failed(
        run_id,
        error_message=(
            "Fallo al persistir el último lote."
        ),
        received=100,
        accepted=80,
        rejected=20,
        created_or_updated=50,
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None
    assert row["status"] == "failed"
    assert row["received"] == 100
    assert row["accepted"] == 80
    assert row["rejected"] == 20
    assert row["created_or_updated"] == 50


def test_repository_persists_data_in_database(
    tmp_path: Path,
) -> None:
    database, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                source_id,
                status
            FROM universe_import_runs
            WHERE id = ?
            """,
            (
                run_id,
            ),
        ).fetchone()

    assert row is not None
    assert row["id"] == run_id
    assert row["source_id"] == "nasdaq_trader"
    assert row["status"] == "running"


def test_start_run_initializes_change_statistics_to_zero(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None
    assert row["inserted"] == 0
    assert row["updated"] == 0
    assert row["unchanged"] == 0
    assert row["created_or_updated"] == 0


def test_mark_succeeded_persists_real_change_statistics(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    repository.mark_succeeded(
        run_id,
        received=100,
        accepted=98,
        rejected=2,
        inserted=12,
        updated=3,
        unchanged=83,
        completed_at=(
            "2026-09-01T10:01:00+00:00"
        ),
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None

    assert row["received"] == 100
    assert row["accepted"] == 98
    assert row["rejected"] == 2

    assert row["inserted"] == 12
    assert row["updated"] == 3
    assert row["unchanged"] == 83

    assert row["created_or_updated"] == 15


def test_mark_succeeded_rejects_change_statistics_not_matching_accepted(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    with pytest.raises(
        ValueError,
        match=(
            "inserted \\+ updated \\+ unchanged "
            "debe ser igual a accepted"
        ),
    ):
        repository.mark_succeeded(
            run_id,
            received=100,
            accepted=100,
            rejected=0,
            inserted=10,
            updated=5,
            unchanged=50,
        )


def test_mark_succeeded_rejects_negative_inserted(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    with pytest.raises(
        ValueError,
        match="inserted no puede ser negativo",
    ):
        repository.mark_succeeded(
            run_id,
            received=1,
            accepted=1,
            rejected=0,
            inserted=-1,
            updated=0,
            unchanged=2,
        )


def test_mark_failed_persists_unknown_change_statistics(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    repository.mark_failed(
        run_id,
        error_message="Fallo simulado.",
        received=100,
        accepted=80,
        rejected=20,
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None
    assert row["status"] == "failed"

    assert row["inserted"] is None
    assert row["updated"] is None
    assert row["unchanged"] is None
    assert row["created_or_updated"] == 0


def test_latest_for_source_returns_change_statistics(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    repository.mark_succeeded(
        run_id,
        received=3,
        accepted=3,
        rejected=0,
        inserted=1,
        updated=1,
        unchanged=1,
    )

    latest = repository.latest_for_source(
        "nasdaq_trader"
    )

    assert latest is not None

    assert latest["inserted"] == 1
    assert latest["updated"] == 1
    assert latest["unchanged"] == 1
    assert latest["created_or_updated"] == 2



def test_start_run_initializes_reconciliation_statistics_to_zero(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None
    assert row["deactivated"] == 0
    assert row["reconciliation_applied"] == 0


def test_mark_succeeded_persists_reconciliation_statistics(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    repository.mark_succeeded(
        run_id,
        received=100,
        accepted=100,
        rejected=0,
        inserted=2,
        updated=3,
        unchanged=95,
        deactivated=4,
        reconciliation_applied=True,
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None
    assert row["status"] == "succeeded"
    assert row["deactivated"] == 4
    assert row["reconciliation_applied"] == 1


def test_mark_succeeded_persists_reconciliation_not_applied(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    repository.mark_succeeded(
        run_id,
        received=100,
        accepted=94,
        rejected=6,
        inserted=0,
        updated=0,
        unchanged=94,
        deactivated=0,
        reconciliation_applied=False,
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None
    assert row["deactivated"] == 0
    assert row["reconciliation_applied"] == 0


def test_mark_succeeded_rejects_negative_deactivated(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    with pytest.raises(
        ValueError,
        match="deactivated no puede ser negativo",
    ):
        repository.mark_succeeded(
            run_id,
            received=1,
            accepted=1,
            rejected=0,
            inserted=0,
            updated=0,
            unchanged=1,
            deactivated=-1,
            reconciliation_applied=True,
        )


def test_mark_succeeded_requires_reconciliation_when_deactivated(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    with pytest.raises(
        ValueError,
        match=(
            "deactivated debe ser cero cuando "
            "reconciliation_applied es False"
        ),
    ):
        repository.mark_succeeded(
            run_id,
            received=10,
            accepted=10,
            rejected=0,
            inserted=0,
            updated=0,
            unchanged=10,
            deactivated=1,
            reconciliation_applied=False,
        )


def test_mark_failed_persists_unknown_reconciliation_statistics(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    repository.mark_failed(
        run_id,
        error_message="Fallo simulado.",
        received=100,
        accepted=80,
        rejected=20,
    )

    row = repository.get_by_id(
        run_id
    )

    assert row is not None
    assert row["status"] == "failed"
    assert row["deactivated"] is None
    assert row["reconciliation_applied"] is None


def test_latest_for_source_returns_reconciliation_statistics(
    tmp_path: Path,
) -> None:
    _, repository = _create_repository(
        tmp_path
    )

    run_id = repository.start_run(
        "nasdaq_trader"
    )

    repository.mark_succeeded(
        run_id,
        received=3,
        accepted=3,
        rejected=0,
        inserted=0,
        updated=0,
        unchanged=3,
        deactivated=2,
        reconciliation_applied=True,
    )

    latest = repository.latest_for_source(
        "nasdaq_trader"
    )

    assert latest is not None
    assert latest["deactivated"] == 2
    assert latest["reconciliation_applied"] == 1
