from __future__ import annotations

from pathlib import Path

import pytest

from scripts.refresh_weighted_market_universe import (
    DEFAULT_MAX_PAGES_PER_REGION,
    DEFAULT_PAGE_SIZE,
    EXHAUSTIVE_PAGE_SIZE,
    _normalize_regions,
    build_parser,
    run_refresh,
)


def _fake_profile(_database_path: Path | None) -> dict[str, object]:
    return {
        "usableCount": 280,
        "totalMarketCapUsd": 1000.0,
        "topMarketCapShares": {
            "top10": 0.30,
            "top50": 0.60,
            "top100": 0.80,
            "top500": 1.0,
            "top1000": 1.0,
        },
        "regionWeights": {
            "america": 0.55,
            "europe": 0.20,
            "asia": 0.25,
        },
    }


def test_run_refresh_returns_ready_status_and_forwards_limits(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_importer(**kwargs):
        calls.append(kwargs)
        return {
            "source": "yahoo_regional_screener",
            "received": 300,
            "accepted": 295,
            "rejected": 5,
            "inserted": 250,
            "updated": 45,
            "unchanged": 0,
            "activeSourceMemberships": 295,
            "catalogQuality": {
                "isGlobalReady": True,
                "globallyUsableCount": 280,
                "usableCoverage": 0.9,
            },
        }

    result = run_refresh(
        database_path=tmp_path / "athena.db",
        regions=("us", "de", "jp"),
        page_size=75,
        max_pages=2,
        importer=fake_importer,
        profile_builder=_fake_profile,
    )

    assert result["status"] == "ready"
    assert result["source"] == "yahoo_regional_screener"
    assert result["regions"] == ["us", "de", "jp"]
    assert result["catalogQuality"]["globallyUsableCount"] == 280
    assert result["capitalizationProfile"]["usableCount"] == 280
    assert result["exhaustive"] is False
    assert calls == [
        {
            "database_path": tmp_path / "athena.db",
            "regions": ("us", "de", "jp"),
            "page_size": 75,
            "max_pages": 2,
        }
    ]


def test_run_refresh_reports_exhaustive_mode_when_max_pages_is_none() -> None:
    calls: list[dict[str, object]] = []

    def fake_importer(**kwargs):
        calls.append(kwargs)
        return {
            "source": "yahoo_regional_screener",
            "received": 1000,
            "accepted": 995,
            "rejected": 5,
            "inserted": 700,
            "updated": 295,
            "unchanged": 0,
            "activeSourceMemberships": 995,
            "catalogQuality": {
                "isGlobalReady": True,
                "globallyUsableCount": 900,
            },
        }

    result = run_refresh(
        regions=("us", "de", "jp"),
        page_size=250,
        max_pages=None,
        importer=fake_importer,
        profile_builder=_fake_profile,
    )

    assert result["exhaustive"] is True
    assert result["pageSize"] == 250
    assert result["maxPagesPerRegion"] is None
    assert calls[0]["max_pages"] is None


def test_run_refresh_reports_fallback_when_quality_is_not_ready() -> None:
    def fake_importer(**kwargs):
        return {
            "source": "yahoo_regional_screener",
            "received": 30,
            "accepted": 30,
            "rejected": 0,
            "inserted": 30,
            "updated": 0,
            "unchanged": 0,
            "activeSourceMemberships": 30,
            "catalogQuality": {
                "isGlobalReady": False,
                "globallyUsableCount": 30,
            },
        }

    result = run_refresh(
        regions=("us", "de", "jp"),
        importer=fake_importer,
        profile_builder=_fake_profile,
    )

    assert result["status"] == "fallback"


def test_parser_supports_exhaustive_mode() -> None:
    args = build_parser().parse_args(["--exhaustive"])

    assert args.exhaustive is True


def test_default_refresh_limits_are_bounded() -> None:
    assert DEFAULT_PAGE_SIZE == 100
    assert DEFAULT_MAX_PAGES_PER_REGION == 1
    assert EXHAUSTIVE_PAGE_SIZE == 250


def test_normalize_regions_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="al menos una región"):
        _normalize_regions(" , ")


def test_run_refresh_requires_quality_report() -> None:
    def fake_importer(**kwargs):
        return {"source": "yahoo_regional_screener"}

    with pytest.raises(RuntimeError, match="informe de calidad"):
        run_refresh(
            regions=("us",),
            importer=fake_importer,
            profile_builder=_fake_profile,
        )
