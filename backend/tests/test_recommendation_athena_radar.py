from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarEvidenceInput,
    RecommendationAthenaRadarService,
)


AS_OF = datetime(2026, 9, 8, 2, 30, tzinfo=timezone.utc)


def evidence(
    evidence_id: str,
    *,
    category: str = "news",
    urgency: str = "material",
    minutes_before: int = 5,
    source: str = "Reuters",
    source_ref: str | None = None,
) -> AthenaRadarEvidenceInput:
    return AthenaRadarEvidenceInput(
        evidence_id=evidence_id,
        category=category,
        urgency=urgency,
        summary=f"Evidence {evidence_id}",
        available_at=AS_OF - timedelta(minutes=minutes_before),
        source=source,
        source_ref=source_ref or f"reuters:{evidence_id}",
    )


def candidate(
    instrument_id: str,
    symbol: str,
    *items: AthenaRadarEvidenceInput,
) -> AthenaRadarCandidateInput:
    return AthenaRadarCandidateInput(
        instrument_id=instrument_id,
        symbol=symbol,
        evidence=tuple(items),
    )


def request_payload() -> dict[str, object]:
    return {
        "asOf": AS_OF.isoformat(),
        "candidates": [
            {
                "instrumentId": "issuer:apple",
                "symbol": "aapl",
                "evidence": [
                    {
                        "evidenceId": "ev-1",
                        "category": "expectations_gap",
                        "urgency": "critical",
                        "summary": "Consensus assumptions moved materially.",
                        "availableAt": (AS_OF - timedelta(minutes=5)).isoformat(),
                        "source": "SEC",
                        "sourceRef": "sec:aapl:10q:2026q3",
                    }
                ],
            }
        ],
    }


def test_radar_orders_research_urgency_without_investment_scoring() -> None:
    service = RecommendationAthenaRadarService()
    result = service.build(
        as_of=AS_OF,
        candidates=(
            candidate("issuer:z", "ZZZ", evidence("routine", urgency="routine")),
            candidate(
                "issuer:a",
                "AAA",
                evidence(
                    "critical",
                    category="thesis_invalidation",
                    urgency="critical",
                    source="SEC",
                    source_ref="sec:aaa:8k",
                ),
            ),
            candidate(
                "issuer:m",
                "MMM",
                evidence(
                    "material",
                    category="factor_risk",
                    urgency="material",
                    source="internal_factor_model",
                    source_ref="factor:mmm:20260908",
                ),
            ),
        ),
    )

    payload = result.to_api_dict()
    assert [item["researchUrgency"] for item in payload["candidates"]] == [
        "critical",
        "material",
        "routine",
    ]
    assert payload["mode"] == "research_attention_only"
    assert payload["rankingInterpretation"] == "research_urgency_not_investment_preference"
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["probability"] == "not_estimated"
    assert payload["policy"]["expectedReturn"] == "not_estimated"
    assert payload["policy"]["automaticTrading"] is False
    assert "score" not in payload
    assert "expectedReturn" not in payload
    assert "probability" not in payload


def test_radar_tie_break_is_deterministic() -> None:
    service = RecommendationAthenaRadarService()
    result = service.build(
        as_of=AS_OF,
        candidates=(
            candidate("issuer:b", "BBB", evidence("b", source_ref="ref:b")),
            candidate("issuer:a", "AAA", evidence("a", source_ref="ref:a")),
        ),
    )
    assert [item.instrument_id for item in result.candidates] == ["issuer:a", "issuer:b"]


@pytest.mark.parametrize(
    "bad_as_of",
    [datetime(2026, 9, 8, 2, 30)],
)
def test_radar_rejects_timezone_naive_as_of(bad_as_of: datetime) -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        RecommendationAthenaRadarService().build(
            as_of=bad_as_of,
            candidates=(candidate("issuer:a", "AAA", evidence("a")),),
        )


def test_radar_rejects_lookahead_evidence() -> None:
    future = AthenaRadarEvidenceInput(
        evidence_id="future",
        category="news",
        urgency="critical",
        summary="Future evidence",
        available_at=AS_OF + timedelta(seconds=1),
        source="Reuters",
        source_ref="reuters:future",
    )
    with pytest.raises(ValueError, match="look-ahead"):
        RecommendationAthenaRadarService().build(
            as_of=AS_OF,
            candidates=(candidate("issuer:a", "AAA", future),),
        )


def test_radar_rejects_naive_evidence_time() -> None:
    naive = AthenaRadarEvidenceInput(
        evidence_id="naive",
        category="news",
        urgency="material",
        summary="Naive evidence",
        available_at=datetime(2026, 9, 8, 2, 0),
        source="Reuters",
        source_ref="reuters:naive",
    )
    with pytest.raises(ValueError, match="zona horaria"):
        RecommendationAthenaRadarService().build(
            as_of=AS_OF,
            candidates=(candidate("issuer:a", "AAA", naive),),
        )


def test_radar_rejects_duplicate_candidate_identity() -> None:
    with pytest.raises(ValueError, match="identidad canónica"):
        RecommendationAthenaRadarService().build(
            as_of=AS_OF,
            candidates=(
                candidate("Issuer:A", "aaa", evidence("one", source_ref="ref:one")),
                candidate("issuer:a", "AAA", evidence("two", source_ref="ref:two")),
            ),
        )


def test_radar_rejects_duplicate_evidence_id() -> None:
    with pytest.raises(ValueError, match="evidence_id"):
        RecommendationAthenaRadarService().build(
            as_of=AS_OF,
            candidates=(
                candidate("issuer:a", "AAA", evidence("same", source_ref="ref:one")),
                candidate("issuer:b", "BBB", evidence("same", source_ref="ref:two")),
            ),
        )


def test_radar_rejects_duplicate_provenance() -> None:
    with pytest.raises(ValueError, match="provenance"):
        RecommendationAthenaRadarService().build(
            as_of=AS_OF,
            candidates=(
                candidate("issuer:a", "AAA", evidence("one", source_ref="same:ref")),
                candidate("issuer:b", "BBB", evidence("two", source_ref="same:ref")),
            ),
        )


def test_radar_rejects_missing_evidence_instead_of_imputing_benign_state() -> None:
    with pytest.raises(ValueError, match="ausencia de evidencia"):
        RecommendationAthenaRadarService().build(
            as_of=AS_OF,
            candidates=(AthenaRadarCandidateInput("issuer:a", "AAA", ()),),
        )


@pytest.mark.parametrize("category", ["buy_signal", "target_price", "unknown"])
def test_radar_rejects_unsupported_categories(category: str) -> None:
    with pytest.raises(ValueError, match="category"):
        RecommendationAthenaRadarService().build(
            as_of=AS_OF,
            candidates=(candidate("issuer:a", "AAA", evidence("bad", category=category)),),
        )


@pytest.mark.parametrize("urgency", ["buy", "sell", "0.92"])
def test_radar_rejects_non_research_urgency(urgency: str) -> None:
    with pytest.raises(ValueError, match="urgency"):
        RecommendationAthenaRadarService().build(
            as_of=AS_OF,
            candidates=(candidate("issuer:a", "AAA", evidence("bad", urgency=urgency)),),
        )


@pytest.mark.parametrize(
    ("source", "source_ref"),
    [
        ("FMP", "fmp:aapl"),
        ("FinancialModelingPrep", "provider:aapl"),
        ("Reuters", "https://financialmodelingprep.com/stable/quote?symbol=AAPL"),
    ],
)
def test_radar_forbids_fmp_sources(source: str, source_ref: str) -> None:
    with pytest.raises(ValueError, match="FMP"):
        RecommendationAthenaRadarService().build(
            as_of=AS_OF,
            candidates=(
                candidate(
                    "issuer:a",
                    "AAA",
                    evidence("fmp", source=source, source_ref=source_ref),
                ),
            ),
        )


def test_radar_api_is_registered_and_preserves_fail_closed_contract() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/recommendations/professional-research/athena-radar",
        json=request_payload(),
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "research_attention_queue_ready"
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["sourceSecurity"] == "fmp_and_financialmodelingprep_sources_forbidden"
    assert payload["candidates"][0]["symbol"] == "AAPL"


def test_radar_api_rejects_timezone_naive_as_of_with_400() -> None:
    client = TestClient(app)
    payload = request_payload()
    payload["asOf"] = "2026-09-08T02:30:00"
    response = client.post(
        "/api/v1/recommendations/professional-research/athena-radar",
        json=payload,
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]


def test_radar_api_rejects_timezone_naive_evidence_with_400() -> None:
    client = TestClient(app)
    payload = request_payload()
    payload["candidates"][0]["evidence"][0]["availableAt"] = "2026-09-08T02:25:00"
    response = client.post(
        "/api/v1/recommendations/professional-research/athena-radar",
        json=payload,
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
