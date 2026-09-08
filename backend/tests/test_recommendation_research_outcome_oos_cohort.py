from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_research_outcome_oos_cohort as cohort_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_research_outcome_oos_cohort_repository import (
    RecommendationResearchOutcomeOosCohortRepository,
)
from app.services.recommendation_research_outcome_oos_cohort_service import (
    OutcomeIssuerIdentityEvidence,
    RecommendationResearchOutcomeOosCohortService,
)


CYCLE_AS_OF = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
COHORT_AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _hash(payload: object) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _record(
    *,
    outcome_id: str,
    instrument_id: str,
    symbol: str,
    cycle_seed: str,
    days: int = 30,
    total_return: float = 0.10,
    market: float = 0.04,
    fx: float = 0.01,
    factor: float = 0.02,
) -> dict[str, object]:
    cycle_hash = hashlib.sha256(cycle_seed.encode("utf-8")).hexdigest()
    period_start = CYCLE_AS_OF
    period_end = period_start + timedelta(days=days)
    residual = total_return - market - fx - factor
    attribution = {
        "module": "performance_attribution",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "instrumentId": instrument_id,
        "symbol": symbol,
        "asOf": period_end.isoformat(),
        "periodStart": period_start.isoformat(),
        "periodEnd": period_end.isoformat(),
        "totalReturn": total_return,
        "marketContribution": market,
        "fxContribution": fx,
        "factorContributions": {"quality": factor},
        "explainedReturn": market + fx + factor,
        "residualReturn": residual,
        "evidence": {},
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "causalClaim": "forbidden_arithmetic_attribution_only",
            "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
            "fx": "explicit_not_silently_neutralized",
        },
    }
    canonical = {
        "outcomeId": outcome_id,
        "cycleHash": cycle_hash,
        "instrumentId": instrument_id,
        "symbol": symbol,
        "cycleAsOf": CYCLE_AS_OF.isoformat(),
        "attribution": attribution,
    }
    outcome_hash = _hash(canonical)
    payload = {
        "module": "research_outcome_attribution",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "outcomeId": outcome_id,
        "outcomeHash": outcome_hash,
        "cycleHash": cycle_hash,
        "instrumentId": instrument_id,
        "symbol": symbol,
        "cycleAsOf": CYCLE_AS_OF.isoformat(),
        "asOf": period_end.isoformat(),
        "periodStart": period_start.isoformat(),
        "periodEnd": period_end.isoformat(),
        "attribution": attribution,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "posteriorObservation": "period_starts_at_or_after_frozen_cycle_and_evidence_available_after_period_end",
            "causalClaim": "forbidden_arithmetic_attribution_only",
            "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
            "learning": "research_only_not_automatic_model_update",
            "fx": "explicit_not_silently_neutralized",
            "integrity": "outcome_hash_binds_cycle_hash_and_exact_attribution_payload",
        },
    }
    return {
        "cycle_hash": cycle_hash,
        "outcome_hash": outcome_hash,
        "payload": payload,
    }


def _identity(
    instrument_id: str,
    issuer_id: str | None,
    *,
    source: str = "athena-identity",
    source_ref: str | None = None,
) -> OutcomeIssuerIdentityEvidence:
    return OutcomeIssuerIdentityEvidence(
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        available_at=COHORT_AS_OF - timedelta(days=1),
        source=source,
        source_ref=source_ref or f"urn:issuer:{instrument_id}",
        resolution_method="canonical_security_master",
    )


def test_cohort_counts_repeated_issuer_as_one_distinct_issuer() -> None:
    service = RecommendationResearchOutcomeOosCohortService()
    first = _record(
        outcome_id="outcome-a",
        instrument_id="instrument-a",
        symbol="AAA",
        cycle_seed="cycle-a",
    )
    second = _record(
        outcome_id="outcome-b",
        instrument_id="instrument-b",
        symbol="AAB",
        cycle_seed="cycle-b",
        total_return=0.06,
    )

    result = service.build(
        cohort_id="cohort-1",
        as_of=COHORT_AS_OF,
        outcome_records=[first, second],
        issuer_evidence=[
            _identity("instrument-a", "issuer-shared"),
            _identity("instrument-b", "issuer-shared"),
        ],
    )

    assert result["observationCount"] == 2
    assert result["distinctOutcomeCount"] == 2
    assert result["resolvedIssuerObservationCount"] == 2
    assert result["distinctResolvedIssuerCount"] == 1
    assert result["maximumObservationsPerResolvedIssuer"] == 2
    horizon = result["horizons"][str(30 * 86400)]
    assert horizon["observationCount"] == 2
    assert horizon["distinctResolvedIssuerCount"] == 1
    assert horizon["issuerObservationCounts"] == {"issuer-shared": 2}
    assert result["policy"]["statisticalIndependence"] == "not_claimed"
    assert result["productionEligible"] is False
    assert result["isWeightingReady"] is False
    assert result["productionLearningEligible"] is False


def test_cohort_partitions_exact_horizons_without_pooling() -> None:
    service = RecommendationResearchOutcomeOosCohortService()
    result = service.build(
        cohort_id="cohort-horizons",
        as_of=COHORT_AS_OF,
        outcome_records=[
            _record(
                outcome_id="outcome-30",
                instrument_id="instrument-a",
                symbol="AAA",
                cycle_seed="cycle-30",
                days=30,
            ),
            _record(
                outcome_id="outcome-90",
                instrument_id="instrument-b",
                symbol="BBB",
                cycle_seed="cycle-90",
                days=90,
            ),
        ],
        issuer_evidence=[
            _identity("instrument-a", "issuer-a"),
            _identity("instrument-b", "issuer-b"),
        ],
    )

    assert result["horizonCount"] == 2
    assert result["horizons"][str(30 * 86400)]["horizonDays"] == 30
    assert result["horizons"][str(90 * 86400)]["horizonDays"] == 90
    assert result["policy"]["horizonPooling"] == "forbidden_exact_elapsed_horizons_partitioned"


def test_unresolved_issuer_is_explicit_and_not_counted_as_distinct() -> None:
    service = RecommendationResearchOutcomeOosCohortService()
    result = service.build(
        cohort_id="cohort-unresolved",
        as_of=COHORT_AS_OF,
        outcome_records=[
            _record(
                outcome_id="outcome-u",
                instrument_id="instrument-u",
                symbol="UUU",
                cycle_seed="cycle-u",
            )
        ],
        issuer_evidence=[_identity("instrument-u", None)],
    )

    assert result["unresolvedIssuerObservationCount"] == 1
    assert result["distinctResolvedIssuerCount"] == 0
    assert result["rows"][0]["issuerIdentity"]["status"] == "unresolved"


def test_cohort_rejects_duplicate_outcome_and_future_outcome() -> None:
    service = RecommendationResearchOutcomeOosCohortService()
    record = _record(
        outcome_id="outcome-dup",
        instrument_id="instrument-a",
        symbol="AAA",
        cycle_seed="cycle-dup",
    )
    with pytest.raises(ValueError, match="outcomeHash duplicado"):
        service.build(
            cohort_id="cohort-dup",
            as_of=COHORT_AS_OF,
            outcome_records=[record, record],
            issuer_evidence=[_identity("instrument-a", "issuer-a")],
        )

    with pytest.raises(ValueError, match="posterior a cohort asOf"):
        service.build(
            cohort_id="cohort-future",
            as_of=CYCLE_AS_OF + timedelta(days=10),
            outcome_records=[record],
            issuer_evidence=[
                OutcomeIssuerIdentityEvidence(
                    instrument_id="instrument-a",
                    issuer_id="issuer-a",
                    available_at=CYCLE_AS_OF + timedelta(days=1),
                    source="athena-identity",
                    source_ref="urn:issuer:a",
                    resolution_method="canonical_security_master",
                )
            ],
        )


def test_cohort_rejects_future_or_fmp_identity_evidence() -> None:
    service = RecommendationResearchOutcomeOosCohortService()
    record = _record(
        outcome_id="outcome-id",
        instrument_id="instrument-a",
        symbol="AAA",
        cycle_seed="cycle-id",
    )
    future_identity = OutcomeIssuerIdentityEvidence(
        instrument_id="instrument-a",
        issuer_id="issuer-a",
        available_at=COHORT_AS_OF + timedelta(seconds=1),
        source="athena-identity",
        source_ref="urn:issuer:a",
        resolution_method="canonical_security_master",
    )
    with pytest.raises(ValueError, match="look-ahead"):
        service.build(
            cohort_id="cohort-future-identity",
            as_of=COHORT_AS_OF,
            outcome_records=[record],
            issuer_evidence=[future_identity],
        )

    with pytest.raises(ValueError, match="FMP/Financial Modeling Prep"):
        service.build(
            cohort_id="cohort-fmp",
            as_of=COHORT_AS_OF,
            outcome_records=[record],
            issuer_evidence=[_identity("instrument-a", "issuer-a", source="FMP")],
        )


def test_cohort_repository_is_idempotent_and_detects_tampering(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "oos-cohort.db")
    service = RecommendationResearchOutcomeOosCohortService()
    repository = RecommendationResearchOutcomeOosCohortRepository(database, service)
    artifact = service.build(
        cohort_id="cohort-persisted",
        as_of=COHORT_AS_OF,
        outcome_records=[
            _record(
                outcome_id="outcome-p",
                instrument_id="instrument-p",
                symbol="PPP",
                cycle_seed="cycle-p",
            )
        ],
        issuer_evidence=[_identity("instrument-p", "issuer-p")],
    )

    first = repository.append(artifact=artifact)
    second = repository.append(artifact=artifact)
    assert second["cohort_hash"] == first["cohort_hash"]

    with database.connect() as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_research_outcome_oos_cohorts WHERE cohort_hash = ?",
            (first["cohort_hash"],),
        ).fetchone()
        mutated = json.loads(str(row["artifact_json"]))
        mutated["rows"][0]["totalReturn"] = 999.0
        connection.execute(
            "UPDATE athena_research_outcome_oos_cohorts SET artifact_json = ? WHERE cohort_hash = ?",
            (
                json.dumps(mutated, sort_keys=True, separators=(",", ":"), allow_nan=False),
                first["cohort_hash"],
            ),
        )

    with pytest.raises(ValueError, match="modificado"):
        repository.get_by_hash(cohort_hash=first["cohort_hash"])


class _OutcomeRepositoryStub:
    def __init__(self, records: dict[str, dict[str, object]]) -> None:
        self.records = records

    def get_by_hash(self, *, outcome_hash: str) -> dict[str, object]:
        try:
            return self.records[outcome_hash]
        except KeyError as exc:
            raise ValueError("Outcome no encontrado") from exc


def test_cohort_api_builds_persists_and_reverifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(
        outcome_id="outcome-api",
        instrument_id="instrument-api",
        symbol="API",
        cycle_seed="cycle-api",
    )
    outcome_hash = str(record["outcome_hash"])
    database = AthenaDatabase(tmp_path / "oos-cohort-api.db")
    service = RecommendationResearchOutcomeOosCohortService()
    repository = RecommendationResearchOutcomeOosCohortRepository(database, service)
    monkeypatch.setattr(cohort_api, "outcome_repository", _OutcomeRepositoryStub({outcome_hash: record}))
    monkeypatch.setattr(cohort_api, "cohort_service", service)
    monkeypatch.setattr(cohort_api, "cohort_repository", repository)
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/professional-research/outcome-oos-cohort",
        json={
            "cohortId": "cohort-api",
            "asOf": COHORT_AS_OF.isoformat(),
            "outcomeHashes": [outcome_hash],
            "issuerEvidence": [
                {
                    "instrumentId": "instrument-api",
                    "issuerId": "issuer-api",
                    "availableAt": (COHORT_AS_OF - timedelta(days=1)).isoformat(),
                    "source": "athena-identity",
                    "sourceRef": "urn:issuer:api",
                    "resolutionMethod": "canonical_security_master",
                }
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["productionLearningEligible"] is False
    assert data["persistence"]["appendOnly"] is True
    assert data["persistence"]["tamperEvident"] is True

    fetched = client.get(
        f"/api/v1/recommendations/professional-research/outcome-oos-cohort/{data['cohortHash']}"
    )
    assert fetched.status_code == 200
    fetched_data = fetched.json()["data"]
    assert fetched_data["cohortHash"] == data["cohortHash"]
    assert fetched_data["persistence"]["tamperEvident"] is True


def test_cohort_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/recommendations/professional-research/outcome-oos-cohort" in paths
    assert "/api/v1/recommendations/professional-research/outcome-oos-cohort/{cohort_hash}" in paths
