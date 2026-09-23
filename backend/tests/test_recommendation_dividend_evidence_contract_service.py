from datetime import datetime, timezone

import pytest

from app.services.recommendation_dividend_evidence_contract_service import (
    RecommendationDividendEvidenceContractService,
)


AS_OF = datetime(2026, 8, 2, tzinfo=timezone.utc)


class _Result:
    def __init__(self, payload):
        self._payload = payload

    def to_api_dict(self):
        return self._payload


class _Signal:
    def __init__(self, payload):
        self.payload = payload

    def evaluate(self, *, symbol, as_of, sustainability_provider=None):
        return _Result(self.payload)


def _payload():
    cutoff = AS_OF.isoformat()
    return {
        "status": "diagnostic_ready",
        "symbol": "DIV",
        "asOf": cutoff,
        "dividend": {
            "frequency": "quarterly",
            "trailingYield": 0.04,
            "dividendGrowthRate": 0.05,
            "paymentStabilityScore": 0.92,
            "knowledgeCutoff": cutoff,
            "pitSafe": True,
        },
        "totalReturn60d": 0.07,
        "earningsPayoutRatio": 0.45,
        "fcfPayoutRatio": 0.50,
        "financialPeriodSustainability": {
            "earningsPayoutRatio": 0.45,
            "fcfPayoutRatio": 0.50,
            "sustainabilityScore": 0.525,
            "sourceProvider": "issuer_filing",
            "knowledgeCutoff": cutoff,
        },
        "productionEligible": False,
    }


def test_contract_preserves_all_requested_dividend_dimensions_without_authority_escalation():
    result = RecommendationDividendEvidenceContractService(signal_service=_Signal(_payload())).evaluate(
        symbol="DIV",
        as_of=AS_OF,
        sustainability_provider="issuer_filing",
    ).to_api_dict()

    signal = result["signal"]
    assert signal["dividend"]["frequency"] == "quarterly"
    assert signal["dividend"]["trailingYield"] == pytest.approx(0.04)
    assert signal["dividend"]["dividendGrowthRate"] == pytest.approx(0.05)
    assert signal["dividend"]["paymentStabilityScore"] == pytest.approx(0.92)
    assert signal["earningsPayoutRatio"] == pytest.approx(0.45)
    assert signal["fcfPayoutRatio"] == pytest.approx(0.50)
    assert signal["financialPeriodSustainability"]["sourceProvider"] == "issuer_filing"
    assert signal["totalReturn60d"] == pytest.approx(0.07)
    assert result["knowledgeCutoff"] == AS_OF.isoformat()
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False


def test_contract_rejects_dividend_evidence_from_different_cutoff():
    payload = _payload()
    payload["dividend"]["knowledgeCutoff"] = datetime(2026, 8, 1, tzinfo=timezone.utc).isoformat()
    service = RecommendationDividendEvidenceContractService(signal_service=_Signal(payload))
    with pytest.raises(RuntimeError, match="otro knowledge_cutoff"):
        service.evaluate(symbol="DIV", as_of=AS_OF)


def test_contract_rejects_sustainability_from_different_cutoff():
    payload = _payload()
    payload["financialPeriodSustainability"]["knowledgeCutoff"] = datetime(2026, 8, 1, tzinfo=timezone.utc).isoformat()
    service = RecommendationDividendEvidenceContractService(signal_service=_Signal(payload))
    with pytest.raises(RuntimeError, match="sostenibilidad.*otro knowledge_cutoff"):
        service.evaluate(symbol="DIV", as_of=AS_OF)


def test_contract_rejects_authority_escalation():
    payload = _payload()
    payload["productionEligible"] = True
    service = RecommendationDividendEvidenceContractService(signal_service=_Signal(payload))
    with pytest.raises(RuntimeError, match="elevar autoridad"):
        service.evaluate(symbol="DIV", as_of=AS_OF)


def test_contract_keeps_missing_optional_evidence_unknown_instead_of_fabricating_it():
    payload = _payload()
    payload["dividend"]["dividendGrowthRate"] = None
    payload["dividend"]["paymentStabilityScore"] = None
    payload["fcfPayoutRatio"] = None
    payload["financialPeriodSustainability"] = None
    result = RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(
        symbol="DIV", as_of=AS_OF
    ).to_api_dict()
    assert result["signal"]["dividend"]["dividendGrowthRate"] is None
    assert result["signal"]["dividend"]["paymentStabilityScore"] is None
    assert result["signal"]["fcfPayoutRatio"] is None
    assert result["signal"]["financialPeriodSustainability"] is None
