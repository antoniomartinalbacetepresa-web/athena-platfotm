from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.fx_rate_repository import FxRateRepository


def _repository(tmp_path) -> FxRateRepository:
    return FxRateRepository(AthenaDatabase(tmp_path / "athena-test.db"))


def _save(repository: FxRateRepository):
    return repository.save(
        observed_on=date(2026, 8, 3),
        base_currency="USD",
        quote_currency="EUR",
        rate=0.865,
        source_provider="yahoo",
        source_symbol="USDEUR=X",
        observed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
    )


def test_fx_rate_repository_replays_only_after_original_retrieval(tmp_path) -> None:
    repository = _repository(tmp_path)
    stored = _save(repository)

    before_retrieval = repository.get_pit(
        observed_on=date(2026, 8, 3),
        base_currency="USD",
        quote_currency="EUR",
        source_symbol="USDEUR=X",
        knowledge_cutoff=datetime(2026, 8, 4, 11, 59, 59, tzinfo=timezone.utc),
    )
    replayed = repository.get_pit(
        observed_on=date(2026, 8, 3),
        base_currency="USD",
        quote_currency="EUR",
        source_symbol="USDEUR=X",
        knowledge_cutoff=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
    )

    assert before_retrieval is None
    assert replayed == stored
    assert replayed.rate == pytest.approx(0.865)
    assert replayed.observed_at == datetime(2026, 8, 3, tzinfo=timezone.utc)
    assert replayed.retrieved_at == datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
    assert replayed.source_provider == "yahoo"
    assert replayed.source_symbol == "USDEUR=X"


def test_fx_rate_repository_is_idempotent_for_identical_observation(tmp_path) -> None:
    repository = _repository(tmp_path)

    first = _save(repository)
    second = _save(repository)

    assert second == first


def test_fx_rate_repository_rejects_mutation_of_persisted_observation(tmp_path) -> None:
    repository = _repository(tmp_path)
    _save(repository)

    with pytest.raises(RuntimeError, match="no puede sobrescribirse"):
        repository.save(
            observed_on=date(2026, 8, 3),
            base_currency="USD",
            quote_currency="EUR",
            rate=0.9,
            source_provider="yahoo",
            source_symbol="USDEUR=X",
            observed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            retrieved_at=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
        )


def test_fx_rate_repository_rejects_boolean_and_non_finite_rates(tmp_path) -> None:
    repository = _repository(tmp_path)

    for invalid in (True, float("nan"), float("inf"), 0.0, -1.0):
        with pytest.raises(ValueError, match="positivo y finito"):
            repository.save(
                observed_on=date(2026, 8, 3),
                base_currency="USD",
                quote_currency="EUR",
                rate=invalid,
                source_provider="yahoo",
                source_symbol="USDEUR=X",
                observed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
                retrieved_at=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
            )


def test_fx_rate_repository_rejects_retrieval_before_observation(tmp_path) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(ValueError, match="preceder"):
        repository.save(
            observed_on=date(2026, 8, 3),
            base_currency="USD",
            quote_currency="EUR",
            rate=0.865,
            source_provider="yahoo",
            source_symbol="USDEUR=X",
            observed_at=datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
            retrieved_at=datetime(2026, 8, 3, 11, tzinfo=timezone.utc),
        )


def test_fx_rate_repository_requires_timezone_aware_cutoff(tmp_path) -> None:
    repository = _repository(tmp_path)
    _save(repository)

    with pytest.raises(ValueError, match="zona horaria"):
        repository.get_pit(
            observed_on=date(2026, 8, 3),
            base_currency="USD",
            quote_currency="EUR",
            source_symbol="USDEUR=X",
            knowledge_cutoff=datetime(2026, 8, 4, 12),
        )
