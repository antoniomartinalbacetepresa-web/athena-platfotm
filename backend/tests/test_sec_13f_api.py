from datetime import timezone

import pytest
from fastapi import HTTPException

from app.api import sec as sec_api


class FakeEdgarService:
    def __init__(self, filings):
        self.filings = filings
        self.closed = False

    def get_institutional_filings(self, cik):
        assert cik == "1067983"
        return self.filings

    def close(self):
        self.closed = True


class Fake13fService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.closed = False

    def fetch_and_parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload

    def close(self):
        self.closed = True


def _filing(accession, acceptance, report_date="2026-06-30"):
    return {
        "form": "13F-HR",
        "accessionNumber": accession,
        "filingDate": acceptance[:4] + "-" + acceptance[4:6] + "-" + acceptance[6:8],
        "reportDate": report_date,
        "acceptanceDateTime": acceptance,
        "primaryDocument": "primary.xml",
    }


def _passive_payload():
    return {
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "athenaRecommendationInfluence": False,
        "automaticScoring": False,
        "automaticTrading": False,
        "identityPolicy": {
            "isWeightingReady": False,
        },
        "holdings": [
            {
                "cusip": "037833100",
                "ticker": None,
                "canonicalInstrumentId": None,
                "identityResolved": False,
            }
        ],
    }


def test_latest_13f_endpoint_selects_newest_acceptance_and_keeps_passive_contract(monkeypatch):
    older = _filing("0001067983-26-000001", "20260814120000")
    newer = _filing("0001067983-26-000002", "20260815120000")
    edgar = FakeEdgarService([older, newer])
    parser = Fake13fService(_passive_payload())
    monkeypatch.setattr(sec_api, "_edgar_service", lambda: edgar)
    monkeypatch.setattr(sec_api, "_sec_13f_service", lambda: parser)

    result = sec_api.get_latest_institutional_holdings(cik="1067983")

    assert result["selectedFiling"]["accessionNumber"] == newer["accessionNumber"]
    assert len(parser.calls) == 1
    call = parser.calls[0]
    assert call["cik"] == "1067983"
    assert call["filing"] is newer
    assert call["retrieved_at"].tzinfo is timezone.utc
    assert result["data"]["advisoryStatus"] == "no_advice"
    assert result["data"]["productionEligible"] is False
    assert result["data"]["athenaRecommendationInfluence"] is False
    assert result["data"]["automaticTrading"] is False
    assert result["data"]["identityPolicy"]["isWeightingReady"] is False
    assert edgar.closed is True
    assert parser.closed is True


def test_latest_13f_endpoint_returns_404_when_no_filing_exists(monkeypatch):
    edgar = FakeEdgarService([])
    parser = Fake13fService(_passive_payload())
    monkeypatch.setattr(sec_api, "_edgar_service", lambda: edgar)
    monkeypatch.setattr(sec_api, "_sec_13f_service", lambda: parser)

    with pytest.raises(HTTPException) as error:
        sec_api.get_latest_institutional_holdings(cik="1067983")

    assert error.value.status_code == 404
    assert parser.calls == []
    assert edgar.closed is True
    assert parser.closed is True


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("advisoryStatus", "advice"),
        ("productionEligible", True),
        ("athenaRecommendationInfluence", True),
        ("automaticScoring", True),
        ("automaticTrading", True),
    ],
)
def test_latest_13f_endpoint_fails_closed_if_parser_breaks_passive_invariant(
    monkeypatch,
    field,
    unsafe_value,
):
    payload = _passive_payload()
    payload[field] = unsafe_value
    edgar = FakeEdgarService([_filing("0001067983-26-000001", "20260814120000")])
    parser = Fake13fService(payload)
    monkeypatch.setattr(sec_api, "_edgar_service", lambda: edgar)
    monkeypatch.setattr(sec_api, "_sec_13f_service", lambda: parser)

    with pytest.raises(HTTPException) as error:
        sec_api.get_latest_institutional_holdings(cik="1067983")

    assert error.value.status_code == 502
    assert edgar.closed is True
    assert parser.closed is True


def test_latest_13f_endpoint_fails_closed_if_identity_becomes_weighting_ready(monkeypatch):
    payload = _passive_payload()
    payload["identityPolicy"] = {"isWeightingReady": True}
    edgar = FakeEdgarService([_filing("0001067983-26-000001", "20260814120000")])
    parser = Fake13fService(payload)
    monkeypatch.setattr(sec_api, "_edgar_service", lambda: edgar)
    monkeypatch.setattr(sec_api, "_sec_13f_service", lambda: parser)

    with pytest.raises(HTTPException) as error:
        sec_api.get_latest_institutional_holdings(cik="1067983")

    assert error.value.status_code == 502
    assert edgar.closed is True
    assert parser.closed is True
