from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository


def _create_instrument(database: AthenaDatabase, symbol: str) -> int:
    return InstrumentRepository(database=database).upsert(
        {
            "symbol": symbol,
            "companyName": f"{symbol} Company",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "marketCap": 100.0,
        }
    )


def test_external_id_reuses_same_canonical_issuer(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = IssuerIdentityRepository(database=database)

    first = repository.upsert_external_issuer(
        source_provider="sec_edgar",
        external_id="0000320193",
        canonical_name="Apple Inc.",
        evidence_confidence=0.95,
    )
    second = repository.upsert_external_issuer(
        source_provider="sec_edgar",
        external_id="0000320193",
        canonical_name="Apple Inc.",
        evidence_confidence=0.98,
        domicile_country="United States",
        region_key="america",
    )

    assert first == second
    external_ids = repository.list_external_ids(first)
    assert external_ids == [
        {
            "source_provider": "sec_edgar",
            "external_id": "0000320193",
            "evidence_confidence": pytest.approx(0.98),
        }
    ]


def test_instrument_link_keeps_identity_evidence(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = _create_instrument(database, "AAPL")
    repository = IssuerIdentityRepository(database=database)
    issuer_id = repository.upsert_external_issuer(
        source_provider="sec_edgar",
        external_id="0000320193",
        canonical_name="Apple Inc.",
        evidence_confidence=0.95,
    )

    repository.link_instrument(
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        evidence_source="sec_company_tickers_exchange",
        resolution_method="exact_ticker_unique_cik",
        confidence=0.95,
    )

    resolved = repository.get_issuer_for_instrument(instrument_id)
    assert resolved is not None
    assert resolved["issuer_id"] == issuer_id
    assert resolved["canonical_name"] == "Apple Inc."
    assert resolved["evidence_source"] == "sec_company_tickers_exchange"
    assert resolved["resolution_method"] == "exact_ticker_unique_cik"
    assert resolved["confidence"] == pytest.approx(0.95)


def test_link_can_be_replaced_by_stronger_evidence(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = _create_instrument(database, "TEST")
    repository = IssuerIdentityRepository(database=database)
    first_issuer = repository.upsert_external_issuer(
        source_provider="source_a",
        external_id="A",
        canonical_name="First Issuer",
        evidence_confidence=0.7,
    )
    second_issuer = repository.upsert_external_issuer(
        source_provider="source_b",
        external_id="B",
        canonical_name="Second Issuer",
        evidence_confidence=0.99,
    )

    repository.link_instrument(
        instrument_id=instrument_id,
        issuer_id=first_issuer,
        evidence_source="source_a",
        resolution_method="heuristic",
        confidence=0.7,
    )
    repository.link_instrument(
        instrument_id=instrument_id,
        issuer_id=second_issuer,
        evidence_source="source_b",
        resolution_method="official_identifier",
        confidence=0.99,
    )

    resolved = repository.get_issuer_for_instrument(instrument_id)
    assert resolved is not None
    assert resolved["issuer_id"] == second_issuer
    assert resolved["confidence"] == pytest.approx(0.99)


def test_repository_rejects_invalid_confidence(tmp_path: Path) -> None:
    repository = IssuerIdentityRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )

    with pytest.raises(ValueError, match="confidence"):
        repository.upsert_external_issuer(
            source_provider="sec_edgar",
            external_id="0000320193",
            canonical_name="Apple Inc.",
            evidence_confidence=1.1,
        )
