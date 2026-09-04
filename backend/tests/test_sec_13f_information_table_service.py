from datetime import datetime, timezone

import pytest

from app.services.sec_13f_information_table_service import (
    Sec13fInformationTableService,
)


XML = """<?xml version="1.0" encoding="UTF-8"?>
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


def _filing() -> dict[str, str]:
    return {
        "form": "13F-HR",
        "accessionNumber": "0001067983-26-000001",
        "filingDate": "2026-08-14",
        "reportDate": "2026-06-30",
        "acceptanceDateTime": "20260814163422",
    }


def _retrieved() -> datetime:
    return datetime(2026, 8, 14, 17, 0, tzinfo=timezone.utc)


def _url() -> str:
    return (
        "https://www.sec.gov/Archives/edgar/data/1067983/"
        "000106798326000001/infotable.xml"
    )


def test_parses_namespaced_13f_holdings_with_explicit_pit_provenance() -> None:
    result = Sec13fInformationTableService().parse(
        XML,
        filing=_filing(),
        retrieved_at=_retrieved(),
        source_url=_url(),
    )

    assert result["status"] == "sec_13f_information_table_parsed"
    assert result["accessionNumber"] == "0001067983-26-000001"
    assert result["positionDate"] == "2026-06-30"
    assert result["filingDate"] == "2026-08-14"
    assert result["publicationDateTime"] == "2026-08-14T16:34:22Z"
    assert result["retrievedAt"] == "2026-08-14T17:00:00Z"
    assert result["sourceUrl"] == _url()
    assert result["sourceProvider"] == "SEC EDGAR"
    assert result["valueUnit"] == "thousands_usd_as_reported_by_sec_13f"
    assert result["holdingCount"] == 1

    holding = result["holdings"][0]
    assert holding == {
        "cusip": "037833100",
        "issuerName": "APPLE INC",
        "titleOfClass": "COM",
        "valueThousandsUsd": 174570000,
        "shareOrPrincipalAmount": 400000000,
        "shareOrPrincipalType": "SH",
        "putCall": None,
        "investmentDiscretion": "DFND",
        "otherManager": None,
        "votingAuthority": {"sole": 400000000, "shared": 0, "none": 0},
        "canonicalInstrumentId": None,
        "ticker": None,
        "identityResolved": False,
    }

    assert result["identityPolicy"] == {
        "identifier": "cusip_as_reported",
        "canonicalInstrumentResolved": False,
        "tickerResolution": "disabled_until_authoritative_identity_evidence",
        "isWeightingReady": False,
    }
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["athenaRecommendationInfluence"] is False
    assert result["automaticScoring"] is False
    assert result["automaticTrading"] is False


def test_deduplicates_only_identical_rows_not_same_issuer_or_cusip_blindly() -> None:
    first = XML.split("</informationTable>")[0]
    row = first[first.index("  <infoTable>") :]
    second_row = row.replace("<titleOfClass>COM</titleOfClass>", "<titleOfClass>COM CALL</titleOfClass>")
    xml = first + row + second_row + "</informationTable>"

    result = Sec13fInformationTableService().parse(
        xml,
        filing=_filing(),
        retrieved_at=_retrieved(),
        source_url=_url(),
    )

    assert result["holdingCount"] == 2
    assert [item["titleOfClass"] for item in result["holdings"]] == ["COM", "COM CALL"]


def test_rejects_dtd_entities_and_malformed_xml() -> None:
    service = Sec13fInformationTableService()

    with pytest.raises(ValueError, match="DTD/entities"):
        service.parse(
            "<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>",
            filing=_filing(),
            retrieved_at=_retrieved(),
            source_url=_url(),
        )

    with pytest.raises(ValueError, match="malformed"):
        service.parse(
            "<informationTable><infoTable>",
            filing=_filing(),
            retrieved_at=_retrieved(),
            source_url=_url(),
        )


def test_rejects_invalid_numeric_values_and_cusip() -> None:
    service = Sec13fInformationTableService()

    with pytest.raises(ValueError, match="invalid CUSIP"):
        service.parse(
            XML.replace("037833100", "BAD"),
            filing=_filing(),
            retrieved_at=_retrieved(),
            source_url=_url(),
        )

    with pytest.raises(ValueError, match="finite and non-negative"):
        service.parse(
            XML.replace("400000000</sshPrnamt>", "NaN</sshPrnamt>"),
            filing=_filing(),
            retrieved_at=_retrieved(),
            source_url=_url(),
        )

    with pytest.raises(ValueError, match="non-negative integer"):
        service.parse(
            XML.replace("174570000</value>", "-1</value>"),
            filing=_filing(),
            retrieved_at=_retrieved(),
            source_url=_url(),
        )


def test_rejects_retrieval_before_publication_and_non_utc_retrieval() -> None:
    service = Sec13fInformationTableService()

    with pytest.raises(ValueError, match="precedes filing publication"):
        service.parse(
            XML,
            filing=_filing(),
            retrieved_at=datetime(2026, 8, 14, 16, 0, tzinfo=timezone.utc),
            source_url=_url(),
        )

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        service.parse(
            XML,
            filing=_filing(),
            retrieved_at=datetime(2026, 8, 14, 17, 0),
            source_url=_url(),
        )


def test_rejects_unapproved_or_insecure_source_urls() -> None:
    service = Sec13fInformationTableService()

    for source_url in (
        "http://www.sec.gov/Archives/edgar/data/1067983/x.xml",
        "https://example.com/Archives/edgar/data/1067983/x.xml",
        "https://www.sec.gov/files/x.xml",
    ):
        with pytest.raises(ValueError, match="approved EDGAR archive URL"):
            service.parse(
                XML,
                filing=_filing(),
                retrieved_at=_retrieved(),
                source_url=source_url,
            )


def test_does_not_fabricate_ticker_from_issuer_name_or_cusip() -> None:
    result = Sec13fInformationTableService().parse(
        XML,
        filing=_filing(),
        retrieved_at=_retrieved(),
        source_url=_url(),
    )

    holding = result["holdings"][0]
    assert holding["issuerName"] == "APPLE INC"
    assert holding["cusip"] == "037833100"
    assert holding["ticker"] is None
    assert holding["canonicalInstrumentId"] is None
    assert holding["identityResolved"] is False
    assert result["identityPolicy"]["isWeightingReady"] is False
