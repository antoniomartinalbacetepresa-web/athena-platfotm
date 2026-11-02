from datetime import datetime, timezone

import pytest

from app.services.recommendation_dividend_evidence_contract_service import (
    RecommendationDividendEvidenceContractService,
)


AS_OF = datetime(2026, 8, 2, tzinfo=timezone.utc)


class _Result:
    def __init__(self, payload): self._payload = payload
    def to_api_dict(self): return self._payload


class _Signal:
    def __init__(self, payload): self.payload = payload
    def evaluate(self, *, symbol, as_of, sustainability_provider=None): return _Result(self.payload)


def _payload():
    cutoff = AS_OF.isoformat()
    return {
        "status": "diagnostic_ready", "symbol": "DIV", "asOf": cutoff,
        "dividend": {"frequency": "quarterly", "trailingYield": 0.04, "dividendGrowthRate": 0.05,
                     "paymentStabilityScore": 0.92, "knowledgeCutoff": cutoff, "pitSafe": True},
        "totalReturn60d": 0.07, "earningsPayoutRatio": 0.45, "fcfPayoutRatio": 0.50,
        "financialPeriodSustainability": {"earningsPayoutRatio": 0.45, "fcfPayoutRatio": 0.50,
            "sustainabilityScore": 0.525, "sourceProvider": "issuer_filing", "knowledgeCutoff": cutoff, "pitSafe": True},
        "productionEligible": False,
    }


def test_contract_preserves_all_requested_dividend_dimensions_without_authority_escalation():
    result = RecommendationDividendEvidenceContractService(signal_service=_Signal(_payload())).evaluate(
        symbol="DIV", as_of=AS_OF, sustainability_provider="issuer_filing").to_api_dict()
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
    payload = _payload(); payload["dividend"]["knowledgeCutoff"] = datetime(2026, 8, 1, tzinfo=timezone.utc).isoformat()
    with pytest.raises(RuntimeError, match="otro knowledge_cutoff"):
        RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF)


def test_contract_rejects_sustainability_from_different_cutoff():
    payload = _payload(); payload["financialPeriodSustainability"]["knowledgeCutoff"] = datetime(2026, 8, 1, tzinfo=timezone.utc).isoformat()
    with pytest.raises(RuntimeError, match="sostenibilidad.*otro knowledge_cutoff"):
        RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF)


def test_contract_rejects_authority_escalation():
    payload = _payload(); payload["productionEligible"] = True
    with pytest.raises(RuntimeError, match="elevar autoridad"):
        RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF)


def test_contract_keeps_missing_optional_evidence_unknown_instead_of_fabricating_it():
    payload = _payload(); payload["dividend"]["dividendGrowthRate"] = None; payload["dividend"]["paymentStabilityScore"] = None
    payload["fcfPayoutRatio"] = None; payload["financialPeriodSustainability"] = None
    result = RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF).to_api_dict()
    assert result["signal"]["dividend"]["dividendGrowthRate"] is None
    assert result["signal"]["dividend"]["paymentStabilityScore"] is None
    assert result["signal"]["fcfPayoutRatio"] is None
    assert result["signal"]["financialPeriodSustainability"] is None


@pytest.mark.parametrize("frequency", ["monthly", "quarterly", "semiannual", "annual", "irregular"])
def test_contract_accepts_all_supported_dividend_frequencies(frequency):
    payload = _payload(); payload["dividend"]["frequency"] = frequency
    result = RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF).to_api_dict()
    assert result["signal"]["dividend"]["frequency"] == frequency


def test_contract_rejects_unknown_frequency_and_invalid_numeric_evidence():
    payload = _payload(); payload["dividend"]["frequency"] = "weekly"
    with pytest.raises(RuntimeError, match="frecuencia"):
        RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF)
    payload = _payload(); payload["dividend"]["paymentStabilityScore"] = 1.01
    with pytest.raises(RuntimeError, match="máximo"):
        RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF)
    payload = _payload(); payload["earningsPayoutRatio"] = float("nan")
    with pytest.raises(RuntimeError, match="finito"):
        RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF)


def test_contract_requires_sustainability_provenance_when_sustainability_exists():
    payload = _payload(); payload["financialPeriodSustainability"]["sourceProvider"] = ""
    with pytest.raises(RuntimeError, match="provenance"):
        RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF)



@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("dividendGrowthRate", float("nan"), "finito"),
        ("dividendGrowthRate", float("inf"), "finito"),
    ],
)
def test_contract_rejects_non_finite_dividend_growth(field, value, message):
    payload = _payload(); payload["dividend"][field] = value
    with pytest.raises(RuntimeError, match=message):
        RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_contract_rejects_non_finite_total_return(value):
    payload = _payload(); payload["totalReturn60d"] = value
    with pytest.raises(RuntimeError, match="totalReturn60d.*finito"):
        RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF)


def test_contract_rejects_sustainability_without_explicit_pit_safety():
    payload = _payload(); payload["financialPeriodSustainability"]["pitSafe"] = False
    with pytest.raises(RuntimeError, match="sostenibilidad.*PIT-safe"):
        RecommendationDividendEvidenceContractService(signal_service=_Signal(payload)).evaluate(symbol="DIV", as_of=AS_OF)


def _quarantined_payload():
    payload = _payload()
    payload.update(
        status="corporate_action_capture_unverified",
        dividend=None,
        totalReturn60d=None,
        earningsPayoutRatio=None,
        fcfPayoutRatio=None,
        financialPeriodSustainability=None,
    )
    return payload


@pytest.mark.parametrize(
    "field",
    [
        "dividend",
        "totalReturn60d",
        "earningsPayoutRatio",
        "fcfPayoutRatio",
        "financialPeriodSustainability",
    ],
)
def test_unverified_capture_status_cannot_reintroduce_derived_evidence(field):
    payload = _quarantined_payload()
    payload[field] = _payload()[field]
    with pytest.raises(RuntimeError, match="cuarentena"):
        RecommendationDividendEvidenceContractService(
            signal_service=_Signal(payload)
        ).evaluate(symbol="DIV", as_of=AS_OF)


def test_quarantined_capture_keeps_independent_market_evidence_without_dividend_authority():
    payload = _quarantined_payload()
    payload["priceReturn60d"] = 0.04
    result = RecommendationDividendEvidenceContractService(
        signal_service=_Signal(payload)
    ).evaluate(symbol="DIV", as_of=AS_OF).to_api_dict()
    assert result["signal"]["priceReturn60d"] == pytest.approx(0.04)
    assert result["signal"]["totalReturn60d"] is None
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False


def test_unready_market_status_cannot_publish_dividend_metrics():
    payload = _quarantined_payload()
    payload["status"] = "market_evidence_not_ready"
    payload["dividend"] = _payload()["dividend"]
    with pytest.raises(RuntimeError, match="cuarentena"):
        RecommendationDividendEvidenceContractService(
            signal_service=_Signal(payload)
        ).evaluate(symbol="DIV", as_of=AS_OF)


def test_unknown_dividend_signal_status_fails_closed():
    payload = _quarantined_payload()
    payload["status"] = "unknown_capture_status"
    with pytest.raises(RuntimeError, match="no reconocido"):
        RecommendationDividendEvidenceContractService(
            signal_service=_Signal(payload)
        ).evaluate(symbol="DIV", as_of=AS_OF)


def test_derived_total_return_requires_dividend_evidence_even_if_status_claims_ready():
    payload = _quarantined_payload()
    payload["status"] = "diagnostic_ready"
    payload["totalReturn60d"] = 0.07
    with pytest.raises(RuntimeError, match="sin evidencia de dividendos"):
        RecommendationDividendEvidenceContractService(
            signal_service=_Signal(payload)
        ).evaluate(symbol="DIV", as_of=AS_OF)


@pytest.mark.parametrize("wrong_symbol", ["MSFT", "DIV.A", "", None, 123])
def test_contract_rejects_foreign_or_missing_dividend_issuer(wrong_symbol):
    payload = _payload()
    payload["symbol"] = wrong_symbol
    with pytest.raises(RuntimeError, match="símbolo solicitado"):
        RecommendationDividendEvidenceContractService(
            signal_service=_Signal(payload)
        ).evaluate(symbol="DIV", as_of=AS_OF)


def test_contract_accepts_same_issuer_with_normalized_case():
    payload = _payload()
    payload["symbol"] = " div "
    result = RecommendationDividendEvidenceContractService(
        signal_service=_Signal(payload)
    ).evaluate(symbol="DIV", as_of=AS_OF).to_api_dict()
    assert result["signal"]["symbol"] == " div "
    assert result["productionEligible"] is False
