from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.issuer_region_resolution_service import (
    IssuerRegionResolutionService,
)


class FakeMetadataProvider:
    def __init__(self, countries: dict[str, str | Exception]) -> None:
        self._countries = countries
        self.calls: list[str] = []

    def get_metadata(self, symbol: str) -> dict[str, object]:
        self.calls.append(symbol)
        value = self._countries[symbol]
        if isinstance(value, Exception):
            raise value
        return {"country": value}


def _insert_cross_region_company(
    repository: InstrumentRepository,
    *,
    company_name: str,
    symbols: tuple[tuple[str, str, str, float], ...],
) -> None:
    repository.upsert_many(
        [
            {
                "symbol": symbol,
                "companyName": company_name,
                "country": country,
                "regionKey": region,
                "exchangeShortName": "TEST",
                "currency": "USD",
                "marketCap": cap,
            }
            for symbol, country, region, cap in symbols
        ]
    )


def test_resolves_cross_region_group_from_issuer_country(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    _insert_cross_region_company(
        repository,
        company_name="The Coca-Cola Company",
        symbols=(
            ("KO", "United States", "america", 385.0),
            ("COLA.WA", "Poland", "europe", 386.0),
            ("KO80.BK", "Thailand", "asia", 384.0),
        ),
    )

    metadata = FakeMetadataProvider(
        {
            "KO": "United States",
            "COLA.WA": "United States",
            "KO80.BK": "United States",
        }
    )
    report = IssuerRegionResolutionService(
        database=database,
        metadata_provider=metadata,
    ).get_report()

    assert report.cross_region_group_count == 1
    assert report.attempted_group_count == 1
    assert report.resolved_group_count == 1
    assert report.unresolved_group_count == 0
    assert report.resolved_market_cap_usd == pytest.approx(385.0)
    assert report.region_market_cap_usd == pytest.approx(
        {"america": 385.0, "europe": 0.0, "asia": 0.0}
    )
    assert report.region_weights == pytest.approx(
        {"america": 1.0, "europe": 0.0, "asia": 0.0}
    )
    group = report.resolved_groups[0]
    assert group["issuerCountry"] == "United States"
    assert group["issuerRegionKey"] == "america"
    assert group["countryAgreement"] is True


def test_keeps_group_unresolved_when_metadata_regions_conflict(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    _insert_cross_region_company(
        repository,
        company_name="Ambiguous Holdings",
        symbols=(
            ("AMB", "United States", "america", 100.0),
            ("AMB.DE", "Germany", "europe", 101.0),
        ),
    )

    metadata = FakeMetadataProvider(
        {"AMB": "United States", "AMB.DE": "Germany"}
    )
    report = IssuerRegionResolutionService(
        database=database,
        metadata_provider=metadata,
    ).get_report()

    assert report.resolved_group_count == 0
    assert report.unresolved_group_count == 1
    assert report.unresolved_market_cap_usd == pytest.approx(100.5)
    assert report.unresolved_groups[0]["reason"] == "conflicting_issuer_regions"


def test_ignores_single_region_groups_and_honors_limit(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    _insert_cross_region_company(
        repository,
        company_name="Large Corp",
        symbols=(
            ("LARGE", "United States", "america", 500.0),
            ("LARGE.DE", "Germany", "europe", 510.0),
        ),
    )
    _insert_cross_region_company(
        repository,
        company_name="Small Corp",
        symbols=(
            ("SMALL", "United States", "america", 100.0),
            ("SMALL.DE", "Germany", "europe", 102.0),
        ),
    )
    repository.upsert_many(
        [
            {
                "symbol": "JP1",
                "companyName": "Japan Only",
                "country": "Japan",
                "regionKey": "asia",
                "exchangeShortName": "TSE",
                "currency": "JPY",
                "marketCap": 200.0,
            }
        ]
    )

    metadata = FakeMetadataProvider(
        {
            "LARGE": "United States",
            "LARGE.DE": "United States",
            "SMALL": "United States",
            "SMALL.DE": "United States",
        }
    )
    report = IssuerRegionResolutionService(
        database=database,
        metadata_provider=metadata,
    ).get_report(max_groups=1)

    assert report.cross_region_group_count == 2
    assert report.attempted_group_count == 1
    assert report.resolved_group_count == 1
    assert report.resolved_groups[0]["companyName"] == "Large Corp"


def test_rejects_invalid_group_limit(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    service = IssuerRegionResolutionService(
        database=database,
        metadata_provider=FakeMetadataProvider({}),
    )

    with pytest.raises(ValueError):
        service.get_report(max_groups=0)
