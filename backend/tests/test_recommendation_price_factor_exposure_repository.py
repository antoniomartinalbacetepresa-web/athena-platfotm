from datetime import datetime, timedelta, timezone
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_price_factor_exposure_repository import (
    RecommendationPriceFactorExposureRepository,
)
from app.services.recommendation_price_factor_exposure_service import (
    RecommendationPriceFactorExposureService,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=20)
AS_OF = END + timedelta(days=1)


class FakeMarketRepository:
    def list_for_instrument(self, instrument_id: int, **kwargs: object):
        price = 100.0
        rows = []
        for index in range(21):
            observed = START + timedelta(days=index)
            if index:
                price *= 1.0 + 0.003 + 0.001 * (index % 3)
            rows.append(
                {
                    "observed_at": observed.isoformat(),
                    "adjusted_close": price,
                    "close": price,
                    "retrieved_at": observed.isoformat(),
                }
            )
        return rows


def artifact(service: RecommendationPriceFactorExposureService):
    return service.evaluate(
        instrument_id=1,
        source_provider="test-provider",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )


def test_repository_is_idempotent_and_tamper_evident(tmp_path) -> None:
    service = RecommendationPriceFactorExposureService(FakeMarketRepository())
    repository = RecommendationPriceFactorExposureRepository(
        database=AthenaDatabase(tmp_path / "athena.db"),
        service=service,
    )
    item = artifact(service)
    first = repository.append(artifact=item)
    second = repository.append(artifact=item)
    assert first["id"] == second["id"]
    key = item["factorExposureKey"]
    loaded = repository.get(factor_exposure_key=key)
    assert loaded is not None
    assert loaded["artifact"] == item

    with repository._database.connect() as connection:  # intentional corruption regression
        raw = connection.execute(
            "SELECT artifact_json FROM athena_price_factor_exposure_artifacts WHERE factor_exposure_key = ?",
            (key,),
        ).fetchone()
        body = json.loads(str(raw["artifact_json"]))
        body["factors"]["momentum"] = 123.0
        connection.execute(
            "UPDATE athena_price_factor_exposure_artifacts SET artifact_json = ? WHERE factor_exposure_key = ?",
            (json.dumps(body), key),
        )

    with pytest.raises(ValueError, match="factorExposureKey"):
        repository.get(factor_exposure_key=key)


def test_repository_rejects_invalid_key(tmp_path) -> None:
    repository = RecommendationPriceFactorExposureRepository(
        database=AthenaDatabase(tmp_path / "athena.db"),
        service=RecommendationPriceFactorExposureService(FakeMarketRepository()),
    )
    with pytest.raises(ValueError, match="SHA-256"):
        repository.get(factor_exposure_key="not-a-hash")
