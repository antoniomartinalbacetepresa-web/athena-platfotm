"""Latest public feeds must not be displaced by private owner-bound research.

Synthetic SQLite regression: no provider access, Ollama execution or deployment claim.
"""
from __future__ import annotations

import pytest

from app.repositories.recommendation_latest_athena_synthesis_repository import (
    RecommendationLatestAthenaSynthesisRepository,
)
from test_latest_athena_synthesis_repository import _payload
from test_private_research_synthesis_cycle_api import _create_private_cycle, _setup
from test_recommendation_news_synthesis_repository import _synthesis


PUBLIC = "1" * 64
RADAR = "2" * 64


def test_private_newer_news_and_athena_do_not_displace_public_latest(
    tmp_path, monkeypatch,
):
    client, cycles, news, athena = _setup(tmp_path, monkeypatch)
    private_hash = _create_private_cycle(client)
    public_news = news.append(
        cycle_hash=PUBLIC, radar_hash=RADAR, synthesis_payload=_synthesis(),
    )
    public_athena = athena.append(
        cycle_hash=PUBLIC, radar_hash="b" * 64, news_synthesis_hash=None,
        synthesis_payload=_payload(
            cycle_hash=PUBLIC, input_fingerprint="c" * 64,
            output_fingerprint="d" * 64,
        ),
    )
    # Private records are newer but must never become anonymous latest results.
    news.append(
        cycle_hash=private_hash, radar_hash=RADAR, synthesis_payload=_synthesis(),
    )
    athena.append(
        cycle_hash=private_hash, radar_hash="b" * 64, news_synthesis_hash=None,
        synthesis_payload=_payload(
            cycle_hash=private_hash, input_fingerprint="c" * 64,
            output_fingerprint="e" * 64,
        ),
    )
    assert news.get_latest()["synthesis_hash"] == public_news["synthesis_hash"]
    latest = RecommendationLatestAthenaSynthesisRepository(cycles._database).get_latest()
    assert latest["synthesis_hash"] == public_athena["synthesis_hash"]
    assert latest["cycle_hash"] == PUBLIC


def test_only_private_syntheses_produce_no_public_latest(tmp_path, monkeypatch):
    client, cycles, news, athena = _setup(tmp_path, monkeypatch)
    private_hash = _create_private_cycle(client)
    news.append(
        cycle_hash=private_hash, radar_hash=RADAR, synthesis_payload=_synthesis(),
    )
    athena.append(
        cycle_hash=private_hash, radar_hash="b" * 64, news_synthesis_hash=None,
        synthesis_payload=_payload(
            cycle_hash=private_hash, input_fingerprint="c" * 64,
            output_fingerprint="d" * 64,
        ),
    )
    with pytest.raises(ValueError, match="No existe ninguna síntesis News persistida"):
        news.get_latest()
    with pytest.raises(ValueError, match="No existe ninguna ATHENA synthesis persistida"):
        RecommendationLatestAthenaSynthesisRepository(cycles._database).get_latest()
