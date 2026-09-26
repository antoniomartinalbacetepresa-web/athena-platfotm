from datetime import datetime, timezone
import json
import sqlite3

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_book_to_market_evidence_repository import (
    RecommendationBookToMarketEvidenceRepository,
)
from app.services.recommendation_book_to_market_evidence_service import (
    RecommendationBookToMarketEvidenceService,
)


UTC = timezone.utc
AS_OF = datetime(2026, 3, 1, 12, tzinfo=UTC)


class Identity:
    cik = "0000123456"

    def to_api_dict(self):
        return {
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


class CikResolver:
    def resolve(self, *, instrument_id):
        return Identity()


class FundamentalResolver:
    def resolve(self, *, cik, canonical_concept, as_of):
        return {
            "status": "resolved",
            "evidenceKey": "b" * 64,
            "selectedFact": {
                "factKey": "c" * 64,
                "value": 500.0,
                "concept": "StockholdersEquity",
                "unit": "USD",
                "periodEnd": "2025-12-31",
                "availableAt": "2026-02-15T12:00:00+00:00",
                "provenance": {"source": "sec_edgar", "sourceRef": "sec:fact"},
            },
        }


class MarketRepository:
    def list_for_instrument(self, instrument_id, *, knowledge_cutoff=None, **kwargs):
        return [
            {
                "market_cap_usd": 1000.0,
                "observed_at": "2026-02-28T12:00:00+00:00",
                "retrieved_at": "2026-02-28T13:00:00+00:00",
                "source_provider": "market-source",
                "source_timestamp": "2026-02-28T12:05:00+00:00",
            }
        ]


def service():
    return RecommendationBookToMarketEvidenceService(
        cik_resolver=CikResolver(),
        fundamental_resolver=FundamentalResolver(),
        market_repository=MarketRepository(),
    )


def artifact():
    return service().evaluate(instrument_id=42, as_of=AS_OF)


def test_repository_is_idempotent_and_revalidates_canonical_artifact(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repo = RecommendationBookToMarketEvidenceRepository(database=database, service=service())
    item = artifact()

    first = repo.append(artifact=item)
    second = repo.append(artifact=item)
    loaded = repo.get_by_key(evidence_key=item["evidenceKey"])

    assert first["id"] == second["id"] == loaded["id"]
    assert loaded["artifact"]["bookToMarket"] == 0.5
    assert loaded["artifact"]["factorReady"] is False
    assert loaded["artifact"]["productionEligible"] is False


def test_repository_detects_direct_sqlite_artifact_tampering(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repo = RecommendationBookToMarketEvidenceRepository(database=database, service=service())
    item = artifact()
    repo.append(artifact=item)

    with sqlite3.connect(database.database_path) as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_book_to_market_evidence WHERE evidence_key = ?",
            (item["evidenceKey"],),
        ).fetchone()
        payload = json.loads(row[0])
        payload["bookToMarket"] = 0.6
        connection.execute(
            "UPDATE athena_book_to_market_evidence SET artifact_json = ? WHERE evidence_key = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), item["evidenceKey"]),
        )

    with pytest.raises(ValueError, match="reconcilia|manipulado"):
        repo.get_by_key(evidence_key=item["evidenceKey"])


def test_repository_rejects_missing_or_factor_ready_artifacts(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repo = RecommendationBookToMarketEvidenceRepository(database=database, service=service())

    missing = {
        "module": "book_to_market_pit_evidence",
        "status": "missing",
        "evidenceKey": None,
    }
    with pytest.raises(ValueError, match="resuelto"):
        repo.append(artifact=missing)

    unsafe = artifact()
    unsafe["factorReady"] = True
    with pytest.raises(ValueError, match="exposición factorial"):
        repo.append(artifact=unsafe)
