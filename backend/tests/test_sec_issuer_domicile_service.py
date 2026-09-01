from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.sec_issuer_domicile_service import SecIssuerDomicileService


class FakeSecProvider:
    def __init__(self, payloads: dict[str, dict[str, object]]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def get_submissions(self, cik: str | int) -> dict[str, object]:
        normalized = str(cik)
        self.calls.append(normalized)
        payload = self.payloads[normalized]
        if isinstance(payload, Exception):
            raise payload
        return payload


def _seed_sec_issuer(database: AthenaDatabase, *, cik: str, symbol: str) -> int:
    instruments = InstrumentRepository(database=database)
    instrument_id = instruments.upsert(
        {
            "symbol": symbol,
            "companyName": f"{symbol} Company",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "marketCap": 100.0,
        }
    )
    identities = IssuerIdentityRepository(database=database)
    issuer_id = identities.upsert_external_issuer(
        source_provider="sec_edgar",
        external_id=cik,
        canonical_name=f"{symbol} Company",
        evidence_confidence=0.95,
    )
    identities.link_instrument(
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        evidence_source="sec_company_tickers_exchange",
        resolution_method="exact_ticker_unique_cik",
        confidence=0.95,
    )
    return instrument_id


def test_sec_domicile_resolves_us_state_code(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = _seed_sec_issuer(
        database,
        cik="0000320193",
        symbol="AAPL",
    )
    provider = FakeSecProvider(
        {
            "0000320193": {
                "stateOfIncorporation": "CA",
                "stateOfIncorporationDescription": "CALIFORNIA",
            }
        }
    )

    report = SecIssuerDomicileService(
        database=database,
        sec_provider=provider,
    ).apply(limit=10)

    assert report.resolved_issuer_count == 1
    identity = IssuerIdentityRepository(database=database).get_issuer_for_instrument(
        instrument_id
    )
    assert identity is not None
    assert identity["domicile_country"] == "United States"
    assert identity["region_key"] == "america"


def test_sec_domicile_resolves_foreign_description_only_when_supported(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = _seed_sec_issuer(
        database,
        cik="0000000002",
        symbol="FOREIGN",
    )
    provider = FakeSecProvider(
        {
            "0000000002": {
                "stateOfIncorporation": "X0",
                "stateOfIncorporationDescription": "UNITED KINGDOM",
            }
        }
    )

    report = SecIssuerDomicileService(
        database=database,
        sec_provider=provider,
    ).apply(limit=10)

    assert report.resolved_issuer_count == 1
    identity = IssuerIdentityRepository(database=database).get_issuer_for_instrument(
        instrument_id
    )
    assert identity is not None
    assert identity["domicile_country"] == "United Kingdom"
    assert identity["region_key"] == "europe"


def test_sec_domicile_leaves_unsupported_jurisdiction_unresolved(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = _seed_sec_issuer(
        database,
        cik="0000000003",
        symbol="OFFSHORE",
    )
    provider = FakeSecProvider(
        {
            "0000000003": {
                "stateOfIncorporation": "E9",
                "stateOfIncorporationDescription": "CAYMAN ISLANDS",
            }
        }
    )

    report = SecIssuerDomicileService(
        database=database,
        sec_provider=provider,
    ).apply(limit=10)

    assert report.resolved_issuer_count == 0
    assert report.unresolved_issuer_count == 1
    identity = IssuerIdentityRepository(database=database).get_issuer_for_instrument(
        instrument_id
    )
    assert identity is not None
    assert identity["domicile_country"] is None
    assert identity["region_key"] is None


def test_sec_domicile_honors_limit_and_isolates_failures(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    _seed_sec_issuer(database, cik="0000000001", symbol="ONE")
    _seed_sec_issuer(database, cik="0000000002", symbol="TWO")
    provider = FakeSecProvider(
        {
            "0000000001": RuntimeError("temporary SEC error"),
            "0000000002": {
                "stateOfIncorporation": "DE",
                "stateOfIncorporationDescription": "DELAWARE",
            },
        }
    )

    report = SecIssuerDomicileService(
        database=database,
        sec_provider=provider,
    ).apply(limit=1)

    assert report.eligible_issuer_count == 2
    assert report.attempted_issuer_count == 1
    assert report.failed_issuer_count == 1
    assert report.resolved_issuer_count == 0
    assert report.resolution_rate == pytest.approx(0.0)
    assert provider.calls == ["0000000001"]


def test_sec_domicile_rejects_non_positive_limit(tmp_path: Path) -> None:
    service = SecIssuerDomicileService(
        database=AthenaDatabase(tmp_path / "athena.db"),
        sec_provider=FakeSecProvider({}),
    )

    with pytest.raises(ValueError, match="limit"):
        service.apply(limit=0)
