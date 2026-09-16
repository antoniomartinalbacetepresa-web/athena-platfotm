import pytest
from fastapi import HTTPException

from app.api.recommendation_portfolio_performance_attribution import _require_sealed_nlv_twr


def _artifact() -> dict[str, object]:
    return {
        "nlvEvidence": {
            "callerSuppliedValuesAccepted": False,
            "tamperVerified": True,
            "binding": "regular_or_exact_pre_post_external_flow_snapshots",
            "snapshotKeys": ["1" * 64, "2" * 64],
        },
        "policy": {
            "callerSuppliedValuationValues": False,
            "valuationEvidence": "persisted_tamper_verified_portfolio_nlv_snapshots",
        },
    }


def test_accepts_only_canonical_sealed_nlv_twr() -> None:
    assert _require_sealed_nlv_twr(_artifact()) == ["1" * 64, "2" * 64]


def test_rejects_legacy_twr_without_nlv_binding() -> None:
    with pytest.raises(HTTPException, match="snapshots NLV sellados"):
        _require_sealed_nlv_twr({"policy": {}})


def test_rejects_caller_supplied_valuation_values() -> None:
    artifact = _artifact()
    artifact["policy"]["callerSuppliedValuationValues"] = True
    with pytest.raises(HTTPException, match="prohibición explícita"):
        _require_sealed_nlv_twr(artifact)
