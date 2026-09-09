from datetime import datetime, timezone

import pytest

from app.services.recommendation_book_to_market_evidence_service import (
    RecommendationBookToMarketEvidenceService,
)


UTC = timezone.utc
AS_OF = datetime(2026, 3, 1, 12, tzinfo=UTC)


class Identity:
    cik = "0000123456"

    def to_api_dict(self):
        return {
            "module": "sec_instrument_cik_resolution",
            "instrumentId": 42,
            "issuerId": 7,
            "cik": self.cik,
            "issuerName": "Example Corp",
            "linkConfidence": 0.98,
            "externalIdConfidence": 0.99,
            "evidenceSource": "sec_ticker_mapping",
            "resolutionMethod": "canonical_security_master",
            "identityKey": "a" * 64,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        }


class FakeCikResolver:
    def resolve(self, *, instrument_id):
        assert instrument_id == 42
        return Identity()


class FakeFundamentalResolver:
    def __init__(self, *, value=500.0, status="resolved", evidence_key="b" * 64):
        self.value = value
        self.status = status
        self.evidence_key = evidence_key

    def resolve(self, *, cik, canonical_concept, as_of):
        assert cik == "0000123456"
        assert canonical_concept == "stockholders_equity"
        assert as_of == AS_OF
        if self.status != "resolved":
            return {
                "module": "sec_fundamental_evidence_resolver",
                "status": "missing",
                "evidenceKey": None,
                "selectedFact": None,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "isWeightingReady": False,
            }
        return {
            "module": "sec_fundamental_evidence_resolver",
            "status": "resolved",
            "evidenceKey": self.evidence_key,
            "selectedFact": {
                "factKey": "c" * 64,
                "value": self.value,
                "concept": "StockholdersEquity",
                "unit": "USD",
                "periodEnd": "2025-12-31",
                "availableAt": "2026-02-15T12:00:00+00:00",
                "provenance": {"source": "sec_edgar", "sourceRef": "sec:fact"},
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        }


class FakeMarketRepository:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def list_for_instrument(self, instrument_id, *, knowledge_cutoff=None, **kwargs):
        self.calls.append((instrument_id, knowledge_cutoff))
        return list(self.rows)


def market_row(
    *,
    cap=1000.0,
    observed="2026-02-28T12:00:00+00:00",
    retrieved="2026-02-28T13:00:00+00:00",
    provider="market-source-a",
    source_timestamp="2026-02-28T12:05:00+00:00",
):
    return {
        "market_cap_usd": cap,
        "observed_at": observed,
        "retrieved_at": retrieved,
        "source_provider": provider,
        "source_timestamp": source_timestamp,
    }


def service(*, rows=None, equity=500.0, status="resolved"):
    return RecommendationBookToMarketEvidenceService(
        cik_resolver=FakeCikResolver(),
        fundamental_resolver=FakeFundamentalResolver(value=equity, status=status),
        market_repository=FakeMarketRepository(rows if rows is not None else [market_row()]),
    )


def test_book_to_market_binds_canonical_sec_equity_to_latest_pit_market_cap() -> None:
    item = service(rows=[
        market_row(cap=800.0, observed="2026-02-20T12:00:00+00:00", retrieved="2026-02-20T13:00:00+00:00"),
        market_row(cap=1000.0),
    ]).evaluate(instrument_id=42, as_of=AS_OF)

    assert item["status"] == "resolved"
    assert item["bookEquityUsd"] == 500.0
    assert item["marketCapUsd"] == 1000.0
    assert item["bookToMarket"] == 0.5
    assert len(item["evidenceKey"]) == 64
    assert item["identityEvidence"]["cik"] == "0000123456"
    assert item["factorReady"] is False
    assert item["factorExposure"] is None
    assert item["policy"]["normalization"] == "not_yet_cross_sectionally_ranked"
    assert item["advisoryStatus"] == "no_advice"
    assert item["productionEligible"] is False
    assert item["isWeightingReady"] is False

    validated = service().validate_artifact(item)
    assert validated["evidenceKey"] == item["evidenceKey"]


def test_book_to_market_uses_latest_retrieved_vintage_for_same_observation() -> None:
    result = service(rows=[
        market_row(cap=900.0, retrieved="2026-02-28T12:30:00+00:00", provider="old-vintage"),
        market_row(cap=1000.0, retrieved="2026-02-28T13:00:00+00:00", provider="new-vintage"),
    ]).evaluate(instrument_id=42, as_of=AS_OF)

    assert result["marketCapUsd"] == 1000.0
    assert result["marketCapEvidence"]["sources"][0]["provider"] == "new-vintage"


def test_book_to_market_fails_closed_on_conflicting_sources_same_pit_point() -> None:
    rows = [
        market_row(cap=1000.0, provider="a"),
        market_row(cap=1100.0, provider="b"),
    ]
    with pytest.raises(ValueError, match="ambiguo"):
        service(rows=rows).evaluate(instrument_id=42, as_of=AS_OF)


def test_book_to_market_accepts_same_value_from_multiple_sources_and_binds_all_provenance() -> None:
    result = service(rows=[market_row(cap=1000.0, provider="b"), market_row(cap=1000.0, provider="a")]).evaluate(
        instrument_id=42,
        as_of=AS_OF,
    )
    assert [item["provider"] for item in result["marketCapEvidence"]["sources"]] == ["a", "b"]


def test_book_to_market_reports_missing_for_missing_or_non_positive_equity_and_market_cap() -> None:
    missing_equity = service(status="missing").evaluate(instrument_id=42, as_of=AS_OF)
    assert missing_equity["status"] == "missing"
    assert missing_equity["missingReason"] == "stockholders_equity_missing"
    assert missing_equity["bookToMarket"] is None

    negative = service(equity=-1.0).evaluate(instrument_id=42, as_of=AS_OF)
    assert negative["status"] == "missing"
    assert negative["missingReason"] == "stockholders_equity_non_positive"

    no_market = service(rows=[]).evaluate(instrument_id=42, as_of=AS_OF)
    assert no_market["status"] == "missing"
    assert no_market["missingReason"] == "market_cap_usd_missing"


def test_book_to_market_rejects_future_leak_nonfinite_and_naive_as_of() -> None:
    with pytest.raises(ValueError, match="PIT"):
        service(rows=[market_row(retrieved="2026-03-02T13:00:00+00:00")]).evaluate(
            instrument_id=42,
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="finito"):
        service(rows=[market_row(cap=float("nan"))]).evaluate(instrument_id=42, as_of=AS_OF)
    with pytest.raises(ValueError, match="zona horaria"):
        service().evaluate(instrument_id=42, as_of=datetime(2026, 3, 1, 12))


def test_book_to_market_validation_detects_ratio_or_provenance_tampering() -> None:
    validator = service()
    result = validator.evaluate(instrument_id=42, as_of=AS_OF)

    tampered = dict(result)
    tampered["bookToMarket"] = 0.6
    with pytest.raises(ValueError, match="reconcilia"):
        validator.validate_artifact(tampered)

    tampered = dict(result)
    market = dict(result["marketCapEvidence"])
    market["sources"] = [{"provider": "other", "sourceTimestamp": None}]
    tampered["marketCapEvidence"] = market
    with pytest.raises(ValueError, match="manipulado"):
        validator.validate_artifact(tampered)
