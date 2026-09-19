from __future__ import annotations


class CountryRegionService:
    """Maps supported issuer domicile countries to ATHENA macro regions."""

    _AMERICA = frozenset(
        {
            "argentina",
            "brazil",
            "canada",
            "chile",
            "colombia",
            "mexico",
            "peru",
            "united states",
            "united states of america",
        }
    )
    _EUROPE = frozenset(
        {
            "austria",
            "belgium",
            "denmark",
            "finland",
            "france",
            "germany",
            "ireland",
            "italy",
            "netherlands",
            "norway",
            "poland",
            "portugal",
            "spain",
            "sweden",
            "switzerland",
            "united kingdom",
        }
    )
    _ASIA = frozenset(
        {
            "china",
            "hong kong",
            "india",
            "indonesia",
            "japan",
            "malaysia",
            "philippines",
            "singapore",
            "south korea",
            "taiwan",
            "thailand",
            "vietnam",
        }
    )

    _ALIASES = {
        "korea, republic of": "south korea",
        "republic of korea": "south korea",
        "korea": "south korea",
        "uk": "united kingdom",
        "u.k.": "united kingdom",
        "usa": "united states",
        "u.s.a.": "united states",
        "us": "united states",
        "u.s.": "united states",
    }

    def normalize_country(self, country: str | None) -> str | None:
        if country is None:
            return None
        normalized = " ".join(str(country).strip().casefold().split())
        if not normalized:
            return None
        return self._ALIASES.get(normalized, normalized)

    def region_for_country(self, country: str | None) -> str | None:
        normalized = self.normalize_country(country)
        if normalized is None:
            return None
        if normalized in self._AMERICA:
            return "america"
        if normalized in self._EUROPE:
            return "europe"
        if normalized in self._ASIA:
            return "asia"
        return None

    def canonical_country_name(self, country: str | None) -> str | None:
        normalized = self.normalize_country(country)
        if normalized is None or self.region_for_country(normalized) is None:
            return None
        special = {
            "united states": "United States",
            "united states of america": "United States",
            "united kingdom": "United Kingdom",
            "south korea": "South Korea",
            "hong kong": "Hong Kong",
        }
        return special.get(normalized, normalized.title())
