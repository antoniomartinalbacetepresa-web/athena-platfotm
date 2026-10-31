from datetime import datetime, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)


def test_recommendation_freezes_explicit_benchmark_symbol(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = RecommendationHistoryRepository(database=database)
    generated = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    recommendation_id = repository.create_recommendation(
        symbol="AAPL",
        benchmark_symbol=" ^gspc ",
        action="buy",
        score=80,
        conviction=0.8,
        horizon_days=90,
        generated_at=generated,
        data_cutoff_at=generated,
        model_version="v1",
        rationale={},
        input_snapshot={},
    )

    recommendation = repository.get_recommendation(recommendation_id)

    assert recommendation is not None
    assert recommendation["benchmark_symbol"] == "^GSPC"


def test_recommendation_benchmark_remains_optional_for_legacy_flows(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = RecommendationHistoryRepository(database=database)
    generated = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    recommendation_id = repository.create_recommendation(
        symbol="AAPL",
        action="hold",
        score=50,
        conviction=0.5,
        horizon_days=30,
        generated_at=generated,
        data_cutoff_at=generated,
        model_version="v1",
        rationale={},
        input_snapshot={},
    )

    recommendation = repository.get_recommendation(recommendation_id)

    assert recommendation is not None
    assert recommendation["benchmark_symbol"] is None


def test_initialize_migrates_existing_recommendation_table_without_benchmark(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE athena_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id INTEGER,
                canonical_issuer_id INTEGER,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                score REAL NOT NULL,
                conviction REAL NOT NULL,
                risk_score REAL,
                horizon_days INTEGER NOT NULL,
                generated_at TEXT NOT NULL,
                data_cutoff_at TEXT NOT NULL,
                model_version TEXT NOT NULL,
                rationale_json TEXT NOT NULL,
                input_snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO athena_recommendations (
                symbol,
                action,
                score,
                conviction,
                horizon_days,
                generated_at,
                data_cutoff_at,
                model_version,
                rationale_json,
                input_snapshot_json,
                created_at
            ) VALUES (
                'LEGACY',
                'hold',
                50,
                0.5,
                30,
                '2026-01-01T12:00:00+00:00',
                '2026-01-01T12:00:00+00:00',
                'legacy-v1',
                '{}',
                '{}',
                '2026-01-01T12:00:00+00:00'
            )
            """
        )

    repository = RecommendationHistoryRepository(database=database)
    repository.initialize()

    with database.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(athena_recommendations)"
            ).fetchall()
        }
        row = connection.execute(
            "SELECT symbol, benchmark_symbol FROM athena_recommendations"
        ).fetchone()

    assert "benchmark_symbol" in columns
    assert row["symbol"] == "LEGACY"
    assert row["benchmark_symbol"] is None
