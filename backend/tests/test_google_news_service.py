from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.google_news_service import GoogleNewsService


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class FakeClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.urls: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.urls.append(url)
        return FakeResponse(self.text)


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Markets rise after earnings</title>
      <link>https://news.google.com/rss/articles/one</link>
      <pubDate>Thu, 03 Sep 2026 12:00:00 GMT</pubDate>
      <source url="https://www.reuters.com">Reuters</source>
    </item>
    <item>
      <title>Markets rise after earnings</title>
      <link>https://news.google.com/rss/articles/duplicate</link>
      <pubDate>Thu, 03 Sep 2026 12:00:00 GMT</pubDate>
      <source url="https://www.reuters.com">Reuters</source>
    </item>
    <item>
      <title>Economy update</title>
      <link>https://news.google.com/rss/articles/two</link>
      <pubDate>Thu, 03 Sep 2026 13:00:00 GMT</pubDate>
      <source url="http://unsafe.example.com">Example Publisher</source>
    </item>
    <item>
      <title>Unsafe article</title>
      <link>http://example.com/not-https</link>
      <pubDate>Thu, 03 Sep 2026 14:00:00 GMT</pubDate>
      <source url="https://example.com">Example</source>
    </item>
  </channel>
</rss>
"""


def test_google_news_feed_preserves_source_publication_and_retrieval_provenance() -> None:
    client = FakeClient(RSS)
    result = GoogleNewsService(client=client).get_feed(
        query="markets earnings",
        limit=8,
        language="en",
        country="US",
    )

    assert len(client.urls) == 1
    assert client.urls[0].startswith("https://news.google.com/rss/search?")
    assert "q=markets+earnings" in client.urls[0]
    assert result["status"] == "news_feed_ready"
    assert result["sourceProvider"] == "google_news_rss"
    assert result["count"] == 2
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["policy"] == {
        "athenaRecommendationInfluence": False,
        "automaticScoring": False,
        "automaticTrading": False,
    }

    first, second = result["items"]
    assert first["title"] == "Economy update"
    assert first["publisher"] == "Example Publisher"
    assert first["publisherUrl"] is None
    assert first["articleUrl"] == "https://news.google.com/rss/articles/two"
    assert first["publishedAt"] == "2026-09-03T13:00:00+00:00"
    assert first["sourceProvider"] == "google_news_rss"
    assert first["retrievedAt"] == result["retrievedAt"]

    assert second["publisher"] == "Reuters"
    assert second["publisherUrl"] == "https://www.reuters.com"
    assert second["publishedAt"] == "2026-09-03T12:00:00+00:00"


def test_google_news_parser_rejects_future_publication_relative_to_retrieval() -> None:
    xml = """<rss><channel><item>
      <title>Future</title>
      <link>https://news.google.com/rss/articles/future</link>
      <pubDate>Sat, 05 Sep 2026 12:00:00 GMT</pubDate>
      <source url="https://example.com">Publisher</source>
    </item></channel></rss>"""

    items = GoogleNewsService._parse_items(
        xml,
        retrieved_at=datetime(2026, 9, 4, 12, tzinfo=timezone.utc),
        limit=8,
    )

    assert items == []


def test_google_news_parser_rejects_invalid_xml() -> None:
    with pytest.raises(RuntimeError, match="RSS inválido"):
        GoogleNewsService._parse_items(
            "<rss>",
            retrieved_at=datetime.now(timezone.utc),
            limit=8,
        )


@pytest.mark.parametrize("limit", [True, 0, 26, 1.5])
def test_google_news_rejects_invalid_limits(limit) -> None:
    with pytest.raises(ValueError, match="limit"):
        GoogleNewsService(client=FakeClient(RSS)).get_feed(limit=limit)


def test_google_news_rejects_empty_or_oversized_queries() -> None:
    service = GoogleNewsService(client=FakeClient(RSS))
    with pytest.raises(ValueError, match="vacía"):
        service.get_feed(query="   ")
    with pytest.raises(ValueError, match="demasiado larga"):
        service.get_feed(query="x" * 201)


def test_google_news_rejects_invalid_locale_codes() -> None:
    service = GoogleNewsService(client=FakeClient(RSS))
    with pytest.raises(ValueError, match="language"):
        service.get_feed(language="eng")
    with pytest.raises(ValueError, match="country"):
        service.get_feed(country="USA")
