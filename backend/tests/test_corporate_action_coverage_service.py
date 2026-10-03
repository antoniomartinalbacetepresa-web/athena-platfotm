from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.corporate_action_coverage_service import CorporateActionCoverageService


AS_OF = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
RETRIEVED_AT = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


def _database(tmp_path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name,
                instrument_type
            ) VALUES ('AAPL', 'Apple Inc.', 'NASDAQ', 'equity')
            """
        )
    return database


def _save_dividend(database, *, provider: str, amount: float, currency: str | None = "USD") -> None:
    CorporateActionRepository(database).save_many(
        instrument_id=1,
        source_provider=provider,
        retrieved_at=RETRIEVED_AT,
        actions=[
            {
                "type": "dividend",
                "effectiveAt": "2026-08-15T00:00:00+00:00",
                "cashAmount": amount,
                "currency": currency,
            }
        ],
    )


def test_empty_event_set_cannot_satisfy_cross_provider_reconciliation(tmp_path) -> None:
    database = _database(tmp_path)
    report = CorporateActionCoverageService(database=database).get_report(as_of=AS_OF)
    assert report.eligible_instrument_count == 1
    assert report.action_bearing_instrument_count == 0
    assert report.event_count == 0
    assert report.agreed_event_count == 0
    assert report.conflict_event_count == 0
    assert report.incomplete_event_count == 0
    assert report.agreement_coverage == 0.0
    assert report.cross_provider_reconciliation_ready is False
    payload = report.to_api_dict()
    assert payload["crossProviderReconciliationReady"] is False
    assert payload["productionIndependenceClaimed"] is False


def test_production_mapping_does_not_trust_arbitrary_secondary_label(tmp_path) -> None:
    database = _database(tmp_path)
    _save_dividend(database, provider="yahoo", amount=0.25)
    _save_dividend(database, provider="secondary", amount=0.25)
    report = CorporateActionCoverageService(database=database).get_report(as_of=AS_OF)
    assert report.event_count == 1
    assert report.agreed_event_count == 0
    assert report.incomplete_event_count == 1
    assert report.independent_provider_families == ("yahoo",)
    assert report.unclassified_source_providers == ("secondary",)
    assert report.cross_provider_reconciliation_ready is False


def test_two_configured_independent_families_with_full_agreement_are_ready(tmp_path) -> None:
    database = _database(tmp_path)
    _save_dividend(database, provider="yahoo", amount=0.25)
    _save_dividend(database, provider="exchange_notice", amount=0.25)
    report = CorporateActionCoverageService(database=database, provider_families={"yahoo": "yahoo", "exchange_notice": "exchange"}).get_report(as_of=AS_OF)
    assert report.event_count == 1
    assert report.agreed_event_count == 1
    assert report.conflict_event_count == 0
    assert report.incomplete_event_count == 0
    assert report.agreement_coverage == 1.0
    assert report.independent_provider_families == ("exchange", "yahoo")
    assert report.cross_provider_reconciliation_ready is True
    payload = report.to_api_dict()
    assert payload["automaticCanonicalization"] is False
    assert payload["productionIndependenceClaimed"] is False


def test_equal_dividend_amounts_without_currency_are_incomplete_not_agreed(tmp_path) -> None:
    database = _database(tmp_path)
    _save_dividend(database, provider="yahoo", amount=0.25, currency=None)
    _save_dividend(database, provider="exchange_notice", amount=0.25, currency=None)
    report = CorporateActionCoverageService(database=database, provider_families={"yahoo": "yahoo", "exchange_notice": "exchange"}).get_report(as_of=AS_OF)
    assert report.event_count == 1
    assert report.agreed_event_count == 0
    assert report.conflict_event_count == 0
    assert report.incomplete_event_count == 1
    assert report.cross_provider_reconciliation_ready is False


def test_non_ascii_currency_code_is_rejected_before_it_can_become_reconciliation_evidence(tmp_path) -> None:
    database = _database(tmp_path)
    with pytest.raises(ValueError, match="ISO de tres letras ASCII"):
        _save_dividend(database, provider="yahoo", amount=0.25, currency="ÉUR")
    report = CorporateActionCoverageService(
        database=database,
        provider_families={"yahoo": "yahoo", "exchange_notice": "exchange"},
    ).get_report(as_of=AS_OF)
    assert report.event_count == 0
    assert report.agreed_event_count == 0
    assert report.cross_provider_reconciliation_ready is False


def test_equal_amounts_in_different_currencies_conflict(tmp_path) -> None:
    database = _database(tmp_path)
    _save_dividend(database, provider="yahoo", amount=0.25, currency="USD")
    _save_dividend(database, provider="exchange_notice", amount=0.25, currency="EUR")
    report = CorporateActionCoverageService(database=database, provider_families={"yahoo": "yahoo", "exchange_notice": "exchange"}).get_report(as_of=AS_OF)
    assert report.event_count == 1
    assert report.agreed_event_count == 0
    assert report.conflict_event_count == 1
    assert report.incomplete_event_count == 0
    assert report.cross_provider_reconciliation_ready is False


def test_unclassified_provenance_blocks_readiness_even_when_classified_families_agree(tmp_path) -> None:
    database = _database(tmp_path)
    _save_dividend(database, provider="yahoo", amount=0.25)
    _save_dividend(database, provider="exchange_notice", amount=0.25)
    _save_dividend(database, provider="mystery_feed", amount=0.30)
    report = CorporateActionCoverageService(database=database, provider_families={"yahoo": "yahoo", "exchange_notice": "exchange"}).get_report(as_of=AS_OF)
    assert report.event_count == 1
    assert report.agreed_event_count == 1
    assert report.unclassified_source_providers == ("mystery_feed",)
    assert report.cross_provider_reconciliation_ready is False
    assert report.to_api_dict()["crossProviderReconciliationReady"] is False


def test_disagreement_between_independent_families_fails_closed(tmp_path) -> None:
    database = _database(tmp_path)
    _save_dividend(database, provider="yahoo", amount=0.25)
    _save_dividend(database, provider="exchange_notice", amount=0.30)
    report = CorporateActionCoverageService(database=database, provider_families={"yahoo": "yahoo", "exchange_notice": "exchange"}).get_report(as_of=AS_OF)
    assert report.event_count == 1
    assert report.agreed_event_count == 0
    assert report.conflict_event_count == 1
    assert report.agreement_coverage == 0.0
    assert report.cross_provider_reconciliation_ready is False


def test_coverage_requires_timezone_aware_cutoff_and_valid_tolerance(tmp_path) -> None:
    database = _database(tmp_path)
    service = CorporateActionCoverageService(database=database)
    with pytest.raises(ValueError, match="zona horaria"):
        service.get_report(as_of=datetime(2026, 9, 12, 10, 0))
    with pytest.raises(ValueError):
        CorporateActionCoverageService(database=database, numeric_tolerance=float("nan"))


def test_multiple_aliases_in_one_family_do_not_outvote_independent_family(tmp_path) -> None:
    database = _database(tmp_path)
    _save_dividend(database, provider="primary_a", amount=0.25)
    _save_dividend(database, provider="primary_b", amount=0.25)
    _save_dividend(database, provider="independent", amount=0.30)
    report = CorporateActionCoverageService(database=database, provider_families={"primary_a": "primary", "primary_b": "primary", "independent": "secondary"}).get_report(as_of=AS_OF)
    assert report.event_count == 1
    assert report.agreed_event_count == 0
    assert report.conflict_event_count == 1
    assert report.incomplete_event_count == 0
    assert report.cross_provider_reconciliation_ready is False


def test_aliases_within_one_family_cannot_create_false_cross_provider_conflict(tmp_path) -> None:
    database = _database(tmp_path)
    _save_dividend(database, provider="primary_a", amount=0.25)
    _save_dividend(database, provider="primary_b", amount=0.25)
    _save_dividend(database, provider="independent", amount=0.25)
    report = CorporateActionCoverageService(database=database, provider_families={"primary_a": "primary", "primary_b": "primary", "independent": "secondary"}).get_report(as_of=AS_OF)
    assert report.event_count == 1
    assert report.agreed_event_count == 1
    assert report.conflict_event_count == 0
    assert report.incomplete_event_count == 0
    assert report.cross_provider_reconciliation_ready is True


def test_disagreement_inside_one_provider_family_fails_closed(tmp_path) -> None:
    database = _database(tmp_path)
    _save_dividend(database, provider="primary_a", amount=0.25)
    _save_dividend(database, provider="primary_b", amount=0.30)
    _save_dividend(database, provider="independent", amount=0.25)
    report = CorporateActionCoverageService(database=database, provider_families={"primary_a": "primary", "primary_b": "primary", "independent": "secondary"}).get_report(as_of=AS_OF)
    assert report.event_count == 1
    assert report.agreed_event_count == 0
    assert report.conflict_event_count == 1
    assert report.cross_provider_reconciliation_ready is False
