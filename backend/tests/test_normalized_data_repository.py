from app.database.athena_database import AthenaDatabase
from app.models.normalized_data import DataProvenance, NormalizedDatum
from app.repositories.normalized_data_repository import NormalizedDataRepository


def _datum(*, value: int, effective_at: str, published_at: str) -> NormalizedDatum:
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
        _datum(value=10, effective_at="2024-09-28", published_at="2024-11-01")
    )
    second_id = repository.save(
        _datum(value=12, effective_at="2025-09-27", published_at="2025-10-31")
    )

    assert first_id != second_id

    history = repository.get_latest(
        metric="fundamental.us-gaap.netincomeloss",
        entity_id="sec-cik:0000320193",
    )
    assert [row["value_json"] for row in history] == ["12", "10"]

    point_in_time = repository.get_latest(
        metric="fundamental.us-gaap.netincomeloss",
        entity_id="sec-cik:0000320193",
        as_of="2025-01-01",
    )
    assert [row["value_json"] for row in point_in_time] == ["10"]


def test_repository_deduplicates_same_observation(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = NormalizedDataRepository(database)
    datum = _datum(value=10, effective_at="2024-09-28", published_at="2024-11-01")

    first_id = repository.save(datum)
    second_id = repository.save(datum)

    assert first_id == second_id
