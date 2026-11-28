from app.services.market_region_classifier import MarketRegionClassifier


def test_classifier_maps_supported_regions() -> None:
    classifier = MarketRegionClassifier()

    assert classifier.classify("United States") == "america"
    assert classifier.classify("Germany") == "europe"
    assert classifier.classify("Japan") == "asia"


def test_classifier_normalizes_case_and_whitespace() -> None:
    classifier = MarketRegionClassifier()

    assert classifier.classify("  SOUTH KOREA ") == "asia"
    assert classifier.classify(" united kingdom ") == "europe"


def test_classifier_returns_none_for_unknown_or_empty_country() -> None:
    classifier = MarketRegionClassifier()

    assert classifier.classify("Australia") is None
    assert classifier.classify("") is None
    assert classifier.classify(None) is None
