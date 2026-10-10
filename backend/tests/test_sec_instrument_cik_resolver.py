import pytest

from app.services.sec_instrument_cik_resolver import SecInstrumentCikResolver


class FakeIssuerRepository:
    def __init__(self, issuer=None, external_ids=None):
        self.issuer = issuer
        self.external_ids = list(external_ids or [])

    def get_issuer_for_instrument(self, instrument_id):
        return self.issuer

    def list_external_ids(self, issuer_id):
        return list(self.external_ids)


def issuer(**overrides):
    payload = {
        "issuer_id": 7,
        "canonical_name": "Example Corp",
        "evidence_source": "sec_ticker_mapping",
        "resolution_method": "canonical_security_master",
        "confidence": 0.98,
    }
    payload.update(overrides)
    return payload


def sec_id(value="0000123456", confidence=0.99):
    return {
        "source_provider": "sec_edgar",
        "external_id": value,
        "evidence_confidence": confidence,
    }


def test_resolver_binds_instrument_to_unique_sec_cik_and_preserves_confidence() -> None:
    resolver = SecInstrumentCikResolver(
        FakeIssuerRepository(
            issuer=issuer(),
            external_ids=[
                {"source_provider": "other", "external_id": "abc", "evidence_confidence": 1.0},
                sec_id("123456", 0.97),
            ],
        )
    )
    result = resolver.resolve(instrument_id=42)
    payload = result.to_api_dict()

    assert result.instrument_id == 42
    assert result.issuer_id == 7
    assert result.cik == "0000123456"
    assert result.link_confidence == 0.98
    assert result.external_id_confidence == 0.97
    assert len(result.identity_key) == 64
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["uniqueSecCikRequired"] is True
    assert payload["policy"]["confidenceThreshold"] == "none_selected_here"


def test_resolver_fails_closed_when_instrument_or_sec_identity_is_missing() -> None:
    with pytest.raises(ValueError, match="emisor canónico"):
        SecInstrumentCikResolver(FakeIssuerRepository()).resolve(instrument_id=42)

    with pytest.raises(ValueError, match="no tiene CIK SEC"):
        SecInstrumentCikResolver(
            FakeIssuerRepository(issuer=issuer(), external_ids=[])
        ).resolve(instrument_id=42)


def test_resolver_fails_closed_on_multiple_distinct_sec_ciks() -> None:
    resolver = SecInstrumentCikResolver(
        FakeIssuerRepository(
            issuer=issuer(),
            external_ids=[sec_id("123456"), sec_id("654321")],
        )
    )
    with pytest.raises(ValueError, match="múltiples CIK"):
        resolver.resolve(instrument_id=42)


def test_resolver_deduplicates_same_cik_and_keeps_highest_external_confidence() -> None:
    resolver = SecInstrumentCikResolver(
        FakeIssuerRepository(
            issuer=issuer(),
            external_ids=[sec_id("123456", 0.80), sec_id("0000123456", 0.95)],
        )
    )
    result = resolver.resolve(instrument_id=42)
    assert result.cik == "0000123456"
    assert result.external_id_confidence == 0.95


def test_resolver_rejects_nonfinite_confidence_and_invalid_instrument_identity() -> None:
    with pytest.raises(ValueError, match="instrument_id"):
        SecInstrumentCikResolver(FakeIssuerRepository()).resolve(instrument_id=0)

    with pytest.raises(ValueError, match="confidence"):
        SecInstrumentCikResolver(
            FakeIssuerRepository(issuer=issuer(confidence=float("nan")), external_ids=[sec_id()])
        ).resolve(instrument_id=42)
