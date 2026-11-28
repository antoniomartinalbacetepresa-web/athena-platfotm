from __future__ import annotations


class MarketRegionClassifier:
    """Classifies a normalized country name into ATHENA market regions."""

    _AMERICA = {
        "argentina",
        "bermuda",
        "brazil",
        "canada",
        "chile",
        "colombia",
        "costa rica",
        "mexico",
        "panama",
        "peru",
        "united states",
        "united states of america",
        "uruguay",
        "us",
        "usa",
    }
    _EUROPE = {
        "austria",
        "belgium",
        "czech republic",
        "czechia",
        "denmark",
        "finland",
        "france",
        "germany",
        "great britain",
        "greece",
        "hungary",
        "iceland",
        "ireland",
        "italy",
        "luxembourg",
        "netherlands",
        "norway",
        "poland",
        "portugal",
        "romania",
        "spain",
        "sweden",
        "switzerland",
        "uk",
        "united kingdom",
    }
    _ASIA = {
        "china",
        "hong kong",
        "india",
        "indonesia",
        "japan",
        "korea",
        "malaysia",
        "philippines",
        "singapore",
        "south korea",
        "taiwan",
        "thailand",
        "vietnam",
    }

    def classify(self, country: str | None) -> str | None:
        normalized = str(country or "").strip().lower()
        if not normalized:
            return None
        if normalized in self._AMERICA:
            return "america"
        if normalized in self._EUROPE:
            return "europe"
        if normalized in self._ASIA:
            return "asia"
        return None
