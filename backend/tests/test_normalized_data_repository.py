from app.database.athena_database import AthenaDatabase
from app.models.normalized_data import DataProvenance, NormalizedDatum
from app.repositories.normalized_data_repository import NormalizedDataRepository


def _datum(
    *,
    value: int,
    effective_at: str,
    published_at: str,
    available_at: str,
) -> NormalizedDatum:
    return NormalizedDatum(
        metric="fundamental.us-gaap.netincomeloss",
        value=value,
        data_kind="fact",
        provenance=DataProvenance(
            source_id="sec_edgar_xbrl",
            retrieved_at=f"{published_at}T12:00:00+00:00",
            effective_at=effective_at,
            published_at=published_at,
            source_timestamp=published_at,
            available_at=available_at,
            version=f"10-K|{published_at}",
            raw_identifier="us-gaap:NetIncomeLoss:USD",
            normalized_identifier="fundamental.us-gaap.netincomeloss",
        ),
        unit="USD",
        entity_id="sec-cik:0000320193",
        quality_score=100.0,
    )


def test_repository_preserves_history_and_supports_as_of_queries(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = NormalizedDataRepository(database)

    first_id = repository.save(
        _datum(
            value=10,
            effective_at="2024-09-28",
            published_at="2024-11-01",
            available_at="2024-11-02T00:00:00+00:00",
        )
    )
    second_id = repository.save(
        _datum(
            value=12,
            effective_at="2025-09-27",
            published_at="2025-10-31",
            available_at="2025-11-01T00:00:00+00:00",
        )
    )

    assert first_id != second_id

    history = repository.get_latest(
        metric="fundamental.us-gaap.netincomeloss",
        entity_id="sec-cik:0000320193",
    )
    assert [row["value_json"] for row in history] == ["12", "10"]
    assert history[0]["available_at"] == "2025-11-01T00:00:00+00:00"

    point_in_time = repository.get_latest(
        metric="fundamental.us-gaap.netincomeloss",
        entity_id="sec-cik:0000320193",
        as_of="2025-01-01T00:00:00+00:00",
    )
    assert [row["value_json"] for row in point_in_time] == ["10"]


def test_repository_as_of_requires_explicit_availability(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = NormalizedDataRepository(database)

    datum = NormalizedDatum(
        metric="fundamental.us-gaap.assets",
        value=100,
        data_kind="fact",
        provenance=DataProvenance(
            source_id="sec_edgar_xbrl",
            retrieved_at="2025-11-02T12:00:00+00:00",
            effective_at="2025-09-27",
            published_at="2025-10-31",
        ),
        unit="USD",
        entity_id="sec-cik:0000320193",
    )
    repository.save(datum)

    history = repository.get_latest(
        metric="fundamental.us-gaap.assets",
        entity_id="sec-cik:0000320193",
    )
    point_in_time = repository.get_latest(
        metric="fundamental.us-gaap.assets",
        entity_id="sec-cik:0000320193",
        as_of="2026-01-01T00:00:00+00:00",
    )

    assert len(history) == 1
    assert history[0]["available_at"] is None
    assert point_in_time == []


def test_repository_as_of_rejects_observation_retrieved_after_cutoff(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = NormalizedDataRepository(database)

    repository.save(
        NormalizedDatum(
            metric="macro.test.series",
            value=4.25,
            data_kind="fact",
            provenance=DataProvenance(
                source_id="macro_source",
                retrieved_at="2026-09-02T08:00:00+00:00",
                effective_at="2026-08-01",
                published_at="2026-08-15",
                available_at="2026-08-15T00:00:00+00:00",
                version="vintage-2026-08-15",
            ),
        )
    )

    before_retrieval = repository.get_latest(
        metric="macro.test.series",
        as_of="2026-09-01T20:30:00+00:00",
    )
    after_retrieval = repository.get_latest(
        metric="macro.test.series",
        as_of="2026-09-02T09:00:00+00:00",
    )

    assert before_retrieval == []
    assert [row["value_json"] for row in after_retrieval] == ["4.25"]


def test_repository_deduplicates_same_observation(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = NormalizedDataRepository(database)
    datum = _datum(
        value=10,
        effective_at="2024-09-28",
        published_at="2024-11-01",
        available_at="2024-11-02T00:00:00+00:00",
    )

    first_id = repository.save(datum)
    second_id = repository.save(datum)

    assert first_id == second_id


def test_repository_deduplicates_observation_with_nullable_identity(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = NormalizedDataRepository(database)
    datum = NormalizedDatum(
        metric="market.sentiment.sample",
        value=0.25,
        data_kind="calculation",
        provenance=DataProvenance(
            source_id="athena",
            retrieved_at="2026-09-01T08:00:00+00:00",
        ),
    )

    first_id = repository.save(datum)
    second_id = repository.save(datum)

    assert first_id == second_id

    history = repository.get_latest(
        metric="market.sentiment.sample",
    )
    assert len(history) == 1
    assert history[0]["id"] == first_id


def test_initialize_migrates_legacy_table_without_available_at(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE normalized_data_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric TEXT NOT NULL,
                entity_id TEXT,
                value_json TEXT NOT NULL,
                data_kind TEXT NOT NULL,
                unit TEXT,
                currency TEXT,
                quality_score REAL,
                confidence_score REAL,
                source_id TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                effective_at TEXT,
                published_at TEXT,
                source_timestamp TEXT,
                source_version TEXT,
                raw_identifier TEXT,
                normalized_identifier TEXT,
                source_url TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    repository = NormalizedDataRepository(database)
    repository.initialize()

    with database.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(normalized_data_observations)"
            ).fetchall()
        }

    assert "available_at" in columns


def test_initialize_collapses_legacy_null_duplicates(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = NormalizedDataRepository(database)
    repository.initialize()

    with database.connect() as connection:
        connection.execute(
            "DROP INDEX uq_normalized_data_observation_identity"
        )
        values = (
            "market.sentiment.legacy",
            None,
            "0.5",
            "calculation",
            "athena",
            "2026-09-01T08:00:00+00:00",
        )
        connection.execute(
            """
            INSERT INTO normalized_data_observations (
                metric,
                entity_id,
                value_json,
                data_kind,
                source_id,
                retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        connection.execute(
            """
            INSERT INTO normalized_data_observations (
                metric,
                entity_id,
                value_json,
                data_kind,
                source_id,
                retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    repository.initialize()

    history = repository.get_latest(
        metric="market.sentiment.legacy",
    )
    assert len(history) == 1
