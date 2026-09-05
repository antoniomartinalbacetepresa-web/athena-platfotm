from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
)


class _Validator:
    def validate_artifact(self, artifact):
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("advice no permitido")
        if artifact.get("productionEligible") is not False:
            raise ValueError("producción no permitida")
        if artifact.get("automaticTrading") is not False:
            raise ValueError("trading no permitido")
        core = {
            key: artifact.get(key)
            for key in (
                "artifactVersion",
                "asOf",
                "baseCurrency",
                "valuationScope",
                "cashIncluded",
                "liabilitiesIncluded",
                "positionCount",
                "positions",
                "investedPositionsValueInBaseCurrency",
            )
        }
        expected = hashlib.sha256(
            json.dumps(
                core,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        if artifact.get("portfolioValuationEvidenceFingerprint") != expected:
            raise ValueError("artefacto modificado")
        return artifact


def _artifact():
    core = {
        "artifactVersion": "athena-portfolio-valuation-evidence-v1",
        "asOf": "2026-09-05T12:00:00+00:00",
        "baseCurrency": "EUR",
        "valuationScope": "invested_long_positions_only_cash_liabilities_unsettled_excluded",
        "cashIncluded": False,
        "liabilitiesIncluded": False,
        "positionCount": 1,
        "positions": [
            {
                "instrumentId": 10,
                "positionValueInBaseCurrency": 1234.5,
            }
        ],
        "investedPositionsValueInBaseCurrency": 1234.5,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            core,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "status": "portfolio_valuation_evidence_verified_non_advisory",
        **core,
        "portfolioValuationEvidenceFingerprint": fingerprint,
        "portfolioValuationEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "automaticTrading": False,
    }


def _repo(tmp_path):
    return RecommendationPortfolioValuationEvidenceRepository(
        AthenaDatabase(tmp_path / "athena.db"),
        validator=_Validator(),
    )


def test_seal_roundtrip_is_append_only_and_validated(tmp_path):
    repository = _repo(tmp_path)
    artifact = _artifact()

    first = repository.seal(artifact=artifact)
    second = repository.seal(artifact=artifact)
    loaded = repository.get(
        valuation_fingerprint=artifact["portfolioValuationEvidenceFingerprint"]
    )

    assert second == first
    assert loaded == first
    assert first["artifact"] == artifact
    assert first["base_currency"] == "EUR"
    assert repository.validate_record(first) is first


def test_tampered_persisted_json_fails_closed(tmp_path):
    repository = _repo(tmp_path)
    record = repository.seal(artifact=_artifact())

    with repository._database.connect() as connection:
        tampered = deepcopy(record["artifact"])
        tampered["investedPositionsValueInBaseCurrency"] = 999999.0
        connection.execute(
            """
            UPDATE athena_recommendation_portfolio_valuation_evidence
            SET artifact_json = ?
            WHERE id = ?
            """,
            (json.dumps(tampered), record["id"]),
        )

    with pytest.raises(ValueError):
        repository.get(valuation_fingerprint=record["valuation_fingerprint"])


def test_non_advisory_invariants_are_required_before_persistence(tmp_path):
    repository = _repo(tmp_path)
    artifact = _artifact()
    artifact["productionEligible"] = True

    with pytest.raises(ValueError, match="producción"):
        repository.seal(artifact=artifact)


def test_non_finite_payload_cannot_be_persisted_even_with_weak_validator(tmp_path):
    class _WeakValidator:
        def validate_artifact(self, artifact):
            return artifact

    repository = RecommendationPortfolioValuationEvidenceRepository(
        AthenaDatabase(tmp_path / "athena.db"),
        validator=_WeakValidator(),
    )
    artifact = _artifact()
    artifact["positions"][0]["positionValueInBaseCurrency"] = float("nan")

    with pytest.raises(ValueError, match="no serializables o no finitos"):
        repository.seal(artifact=artifact)
