from __future__ import annotations

import pytest

from app.services.news_synthesis_service import NewsSynthesisService


def _item(**overrides):
    item = {
        "title": "Company raises guidance after earnings beat estimates",
        "publisher": "Example Wire",
        "articleUrl": "https://example.com/article/1",
        "publishedAt": "2026-09-14T12:00:00+00:00",
        "retrievedAt": "2026-09-14T12:05:00+00:00",
        "sourceProvider": "google_news_rss",
    }
    item.update(overrides)
    return item


def test_synthesis_is_ranked_traced_and_never_changes_athena_automatically() -> None:
    report = NewsSynthesisService().synthesize(
        [
            _item(),
            _item(
                title="Company opens a new office",
                articleUrl="https://example.com/article/2",
                publishedAt="2026-09-14T12:01:00+00:00",
            ),
        ]
    ).to_api_dict()

    assert report["status"] == "diagnostic_only"
    assert report["advisoryStatus"] == "no_advice"
    assert report["productionEligible"] is False
    assert report["policy"] == {
        "automaticAthenaScoreImpact": False,
        "automaticRecommendationImpact": False,
        "automaticTrading": False,
        "duplicateEvidenceAmplification": False,
    }
    assert report["items"][0]["importanceScore"] > report["items"][1]["importanceScore"]
    assert report["items"][0]["estimatedImpact"] == "potentially_positive"
    assert report["items"][0]["sourceProvider"] == "google_news_rss"
    assert report["items"][0]["articleUrl"] == "https://example.com/article/1"
    assert report["items"][0]["publishedAt"] == "2026-09-14T12:00:00+00:00"
    assert report["items"][0]["retrievedAt"] == "2026-09-14T12:05:00+00:00"
    assert len(report["items"][0]["evidenceId"]) == 64
    assert set(report["items"][0]["evidenceId"]) <= set("0123456789abcdef")


def test_synthesis_reports_mixed_and_unclear_impact_without_predictive_claim() -> None:
    service = NewsSynthesisService()
    mixed = service.synthesize(
        [_item(title="Company raises guidance but faces lawsuit after earnings")]
    ).to_api_dict()["items"][0]
    unclear = service.synthesize(
        [_item(title="Company schedules investor presentation")]
    ).to_api_dict()["items"][0]

    assert mixed["estimatedImpact"] == "mixed"
    assert unclear["estimatedImpact"] == "unclear"
    assert "no son predicciones" in service.synthesize([_item()]).to_api_dict()["warning"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("publisher", ""),
        ("articleUrl", ""),
        ("sourceProvider", ""),
        ("publishedAt", "2026-09-14T12:00:00"),
        ("retrievedAt", "2026-09-14T12:05:00"),
    ],
)
def test_synthesis_fails_closed_on_missing_or_naive_provenance(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        NewsSynthesisService().synthesize([_item(**{field: value})])


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/article/1",
        "javascript:alert(1)",
        "https://user:secret@example.com/article/1",
        "https:///missing-host",
    ],
)
def test_synthesis_rejects_unsafe_or_non_https_article_urls(url: str) -> None:
    with pytest.raises(ValueError):
        NewsSynthesisService().synthesize([_item(articleUrl=url)])


def test_synthesis_rejects_duplicate_article_evidence_instead_of_amplifying_it() -> None:
    duplicate = _item(
        title="Syndicated copy with a different headline",
        publisher="Another Publisher",
        retrievedAt="2026-09-14T12:06:00+00:00",
    )
    with pytest.raises(ValueError, match="duplicada"):
        NewsSynthesisService().synthesize([_item(), duplicate])


def test_evidence_identity_is_deterministic_and_ignores_url_fragment() -> None:
    service = NewsSynthesisService()
    first = service.synthesize([_item()]).to_api_dict()["items"][0]
    second = service.synthesize(
        [_item(articleUrl="https://EXAMPLE.com/article/1#tracking")]
    ).to_api_dict()["items"][0]
    assert first["articleUrl"] == second["articleUrl"]
    assert first["evidenceId"] == second["evidenceId"]


def test_synthesis_rejects_lookahead_timestamps() -> None:
    with pytest.raises(ValueError, match="publishedAt no puede ser posterior"):
        NewsSynthesisService().synthesize(
            [
                _item(
                    publishedAt="2026-09-14T12:06:00+00:00",
                    retrievedAt="2026-09-14T12:05:00+00:00",
                )
            ]
        )


def test_synthesis_is_deterministic() -> None:
    service = NewsSynthesisService()
    items = [_item(), _item(title="Inflation report prompts rate hike debate", articleUrl="https://example.com/article/2")]
    first = service.synthesize(items).to_api_dict()
    second = service.synthesize(reversed(items)).to_api_dict()
    assert first == second