from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.instrument_type_market_cap_service import (
    InstrumentTypeMarketCapService,
)
from app.services.market_observation_coverage_service import (
    MarketObservationCoverageService,
)
from app.services.market_weighting_readiness_service import (
    MarketWeightingReadinessService,
)
from app.services.persisted_market_universe_service import (
    PersistedMarketUniverseService,
)
from app.services.recommendation_learning_status_service import (
    RecommendationLearningStatusService,
)


def build_report(
    *,
    database: AthenaDatabase | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    effective_database = database if database is not None else AthenaDatabase()
    effective_as_of = as_of if as_of is not None else datetime.now(timezone.utc)
    if effective_as_of.tzinfo is None or effective_as_of.utcoffset() is None:
        raise ValueError("as_of debe incluir zona horaria.")

    universe = PersistedMarketUniverseService(
        database=effective_database,
    ).get_quality_report()
    weighting = MarketWeightingReadinessService(
        database=effective_database,
    ).get_report()
    instrument_types = InstrumentTypeMarketCapService(
        database=effective_database,
    ).get_report()
    market_history = MarketObservationCoverageService(
        database=effective_database,
    ).get_report()
    learning = RecommendationLearningStatusService(
        database=effective_database,
    ).get_status(
        as_of=effective_as_of,
    )

    return {
        "status": "athena_readiness_diagnostics",
        "asOf": effective_as_of.astimezone(timezone.utc).isoformat(),
        "marketUniverse": universe.to_api_dict(),
        "marketWeighting": weighting.to_api_dict(),
        "instrumentTypes": instrument_types.to_api_dict(),
        "marketHistory": market_history.to_api_dict(),
        "recommendationLearning": learning,
        "automaticActivation": False,
    }


def main() -> None:
    print(
        json.dumps(
            build_report(),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
