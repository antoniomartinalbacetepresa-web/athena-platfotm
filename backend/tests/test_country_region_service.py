from app.services.country_region_service import CountryRegionService


def test_country_region_service_maps_supported_countries() -> None:
    service = CountryRegionService()

    assert service.region_for_country("United States") == "america"
    assert service.region_for_country("Canada") == "america"
    assert service.region_for_country("Germany") == "europe"
    assert service.region_for_country("United Kingdom") == "europe"
    assert service.region_for_country("Japan") == "asia"
    assert service.region_for_country("South Korea") == "asia"


def test_country_region_service_normalizes_common_aliases() -> None:
    service = CountryRegionService()

    assert service.canonical_country_name("USA") == "United States"
    assert service.canonical_country_name("UK") == "United Kingdom"
    assert service.canonical_country_name("Republic of Korea") == "South Korea"


def test_country_region_service_leaves_unsupported_country_unresolved() -> None:
    service = CountryRegionService()

    assert service.region_for_country("Cayman Islands") is None
    assert service.canonical_country_name("Cayman Islands") is None
