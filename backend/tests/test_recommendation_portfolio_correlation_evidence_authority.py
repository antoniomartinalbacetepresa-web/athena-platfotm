from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_portfolio_correlation_evidence_repository import (
    RecommendationPortfolioCorrelationEvidenceRepository,
)
from app.services.recommendation_portfolio_correlation_evidence_store_service import (
    RecommendationPortfolioCorrelationEvidenceStoreService,
)


CUTOFF = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Result:
    def to_api_dict(self):
        return {
            "leftInstrumentId": 10,
            "rightInstrumentId": 20,
            "sourceProvider": "YAHOO_CHART",
            "knowledgeCutoff": CUTOFF.isoformat(),
            "sampleCount": 60,
            "correlation": 0.25,
            "firstReturnDate": "2026-06-01",
            "lastReturnDate": "2026-08-31",
            "latestRetrievedAt": "2026-09-01T11:00:00+00:00",
            "priceField": "adjusted_close",
            "alignmentPolicy": "utc_calendar_date_intersection",
            "returnPolicy": "simple_return_consecutive_observations_per_instrument",
            "recommendationPolicy": "no_advice",
            "productionEligible": False,
            "allocationInfluence": False,
            "automaticTrading": False,
        }


class _CorrelationService:
    def calculate_pair(self, **kwargs):
        assert kwargs["knowledge_cutoff"] == CUTOFF
        return _Result()


def _fingerprint(core):
    return hashlib.sha256(
        json.dumps(
            core,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def test_store_seals_exact_backend_derived_correlation(tmp_path):
    repository = RecommendationPortfolioCorrelationEvidenceRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    service = RecommendationPortfolioCorrelationEvidenceStoreService(
        correlation_service=_CorrelationService(),
        repository=repository,
    )

    result = service.calculate_and_seal(
        left_instrument_id=10,
        right_instrument_id=20,
        source_provider="YAHOO_CHART",
        knowledge_cutoff=CUTOFF,
    )

    evidence = result["evidence"]
    assert evidence["knowledgeCutoff"] == CUTOFF.isoformat()
    assert evidence["latestRetrievedAt"] < evidence["knowledgeCutoff"]
    assert evidence["advisoryStatus"] == "no_advice"
    assert evidence["productionEligible"] is False
    assert evidence["allocationEligible"] is False
    assert evidence["automaticTrading"] is False
    persisted = repository.get(evidence_fingerprint=result["evidenceFingerprint"])
    assert persisted is not None
    assert persisted["record_fingerprint"] == result["recordFingerprint"]
    assert persisted["artifact"] == evidence


def test_repository_rejects_nonfinite_or_post_cutoff_correlation(tmp_path):
    repository = RecommendationPortfolioCorrelationEvidenceRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    core = {
        "artifactVersion": repository.ARTIFACT_VERSION,
        "leftInstrumentId": 10,
        "rightInstrumentId": 20,
        "sourceProvider": "YAHOO_CHART",
        "knowledgeCutoff": CUTOFF.isoformat(),
        "sampleCount": 60,
        "correlation": 0.25,
        "firstReturnDate": "2026-06-01",
        "lastReturnDate": "2026-08-31",
        "latestRetrievedAt": "2026-09-01T13:00:00+00:00",
        "priceField": "adjusted_close",
        "alignmentPolicy": "utc_calendar_date_intersection",
        "returnPolicy": "simple_return_consecutive_observations_per_instrument",
    }
    artifact = {
        "status": "portfolio_correlation_evidence_verified_non_advisory",
        **core,
        "portfolioCorrelationEvidenceFingerprint": _fingerprint(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }
    with pytest.raises(ValueError, match="después del cutoff"):
        repository.seal(artifact=artifact)

    core["latestRetrievedAt"] = "2026-09-01T11:00:00+00:00"
    core["correlation"] = float("nan")
    artifact["correlation"] = float("nan")
    artifact["latestRetrievedAt"] = core["latestRetrievedAt"]
    artifact["portfolioCorrelationEvidenceFingerprint"] = "0" * 64
    with pytest.raises(ValueError):
        repository.seal(artifact=artifact)


def test_direct_database_tampering_is_detected(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = RecommendationPortfolioCorrelationEvidenceRepository(database)
    service = RecommendationPortfolioCorrelationEvidenceStoreService(
        correlation_service=_CorrelationService(),
        repository=repository,
    )
    result = service.calculate_and_seal(
        left_instrument_id=10,
        right_instrument_id=20,
        source_provider="YAHOO_CHART",
        knowledge_cutoff=CUTOFF,
    )

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_portfolio_correlation_evidence
            SET source_provider = 'TAMPERED'
            WHERE evidence_fingerprint = ?
            """,
            (result["evidenceFingerprint"],),
        )

    with pytest.raises(ValueError, match="sourceProvider"):
        repository.get(evidence_fingerprint=result["evidenceFingerprint"])
