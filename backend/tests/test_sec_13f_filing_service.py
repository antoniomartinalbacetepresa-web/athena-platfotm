from datetime import datetime, timezone

import httpx
import pytest

from app.services.sec_13f_filing_service import Sec13fFilingService


INFO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>174570000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>400000000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>DFND</investmentDiscretion>
    <votingAuthority>
      <Sole>400000000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>
"""

PRIMARY_XML = """<?xml version="1.0"?><edgarSubmission><formData>13F-HR</formData></edgarSubmission>"""
OTHER_XML = """<?xml version="1.0"?><otherDocument><value>1</value></otherDocument>"""


def _filing() -> dict[str, str]:
    return {
        "form": "13F-HR",
        "accessionNumber": "0001067983-26-000001",
        "filingDate": "2026-08-14",
        "reportDate": "2026-06-30",
        "acceptanceDateTime": "20260814163422",
        "primaryDocument": "primary.xml",
    }


def _retrieved() -> datetime:
    return datetime(2026, 8, 14, 17, 0, tzinfo=timezone.utc)


def _index(items: list[str]) -> dict:
    return {
        "directory": {
            "item": [
                {"name": name, "type": "text/xml", "size": "100"}
                for name in items
            ]
        }
    }


def _client(index_items: list[str], documents: dict[str, str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/index.json"):
            return httpx.Response(200, json=_index(index_items))
        name = request.url.path.rsplit("/", 1)[-1]
        if name in documents:
            return httpx.Response(
                200,
                content=documents[name].encode("utf-8"),
                headers={"Content-Type": "application/xml"},
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_resolves_unique_information_table_from_official_accession_index() -> None:
    client = _client(
        ["primary.xml", "other.xml", "infotable.xml"],
        {"other.xml": OTHER_XML, "infotable.xml": INFO_XML},
    )
    service = Sec13fFilingService(client=client, user_agent="ATHENA test contact@example.com")

    result = service.fetch_and_parse(
        cik="1067983",
        filing=_filing(),
        retrieved_at=_retrieved(),
    )

    base = (
        "https://www.sec.gov/Archives/edgar/data/1067983/"
        "000106798326000001"
    )
    assert result["sourceUrl"] == f"{base}/infotable.xml"
    assert result["accessionIndexUrl"] == f"{base}/index.json"
    assert result["documentSelectionPolicy"] == (
        "official_accession_index_then_unique_information_table_xml"
    )
    assert result["holdingCount"] == 1
    assert result["holdings"][0]["cusip"] == "037833100"
    assert result["holdings"][0]["ticker"] is None
    assert result["identityPolicy"]["isWeightingReady"] is False
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["athenaRecommendationInfluence"] is False
    assert result["automaticTrading"] is False


def test_does_not_assume_first_xml_is_information_table() -> None:
    client = _client(
        ["primary.xml", "first.xml", "second.xml"],
        {"first.xml": OTHER_XML, "second.xml": INFO_XML},
    )
    result = Sec13fFilingService(client=client).fetch_and_parse(
        cik=1067983,
        filing=_filing(),
        retrieved_at=_retrieved(),
    )

    assert result["sourceUrl"].endswith("/second.xml")


def test_fails_closed_when_information_table_is_missing_or_ambiguous() -> None:
    missing = Sec13fFilingService(
        client=_client(["primary.xml", "other.xml"], {"other.xml": OTHER_XML})
    )
    with pytest.raises(ValueError, match="no verifiable information table"):
        missing.fetch_and_parse(
            cik=1067983,
            filing=_filing(),
            retrieved_at=_retrieved(),
        )

    ambiguous = Sec13fFilingService(
        client=_client(
            ["primary.xml", "one.xml", "two.xml"],
            {"one.xml": INFO_XML, "two.xml": INFO_XML},
        )
    )
    with pytest.raises(ValueError, match="multiple information table"):
        ambiguous.fetch_and_parse(
            cik=1067983,
            filing=_filing(),
            retrieved_at=_retrieved(),
        )


def test_rejects_unsafe_index_filename_and_invalid_accession() -> None:
    unsafe = Sec13fFilingService(
        client=_client(["primary.xml", "../evil.xml"], {})
    )
    with pytest.raises(ValueError, match="unsafe filename"):
        unsafe.fetch_and_parse(
            cik=1067983,
            filing=_filing(),
            retrieved_at=_retrieved(),
        )

    invalid_filing = _filing()
    invalid_filing["accessionNumber"] = "../../etc/passwd"
    with pytest.raises(ValueError, match="accession number is invalid"):
        Sec13fFilingService(client=_client([], {})).fetch_and_parse(
            cik=1067983,
            filing=invalid_filing,
            retrieved_at=_retrieved(),
        )


def test_rejects_non_utc_retrieval_before_network_access() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    service = Sec13fFilingService(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        service.fetch_and_parse(
            cik=1067983,
            filing=_filing(),
            retrieved_at=datetime(2026, 8, 14, 17, 0),
        )
    assert called is False


def test_rejects_dtd_in_candidate_document() -> None:
    malicious = "<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><informationTable>&e;</informationTable>"
    service = Sec13fFilingService(
        client=_client(["primary.xml", "candidate.xml"], {"candidate.xml": malicious})
    )

    with pytest.raises(ValueError, match="DTD/entities"):
        service.fetch_and_parse(
            cik=1067983,
            filing=_filing(),
            retrieved_at=_retrieved(),
        )
