from __future__ import annotations

from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_professional_research_cycle_repository import (
    RecommendationProfessionalResearchCycleRepository,
)
from app.repositories.recommendation_athena_synthesis_repository import (
    RecommendationAthenaSynthesisRepository,
)


class RecommendationLatestAthenaSynthesisRepository:
    """Select the latest persisted ATHENA synthesis without weakening integrity checks.

    Selection is presentation-only. The canonical synthesis repository remains the
    authority for package validation and this adapter never creates, updates or
    promotes research outputs.
    """

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._canonical = RecommendationAthenaSynthesisRepository(self._database)

    def get_latest(self) -> dict[str, Any]:
        self._canonical.initialize()
        RecommendationProfessionalResearchCycleRepository(self._database).initialize()
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT s.cycle_hash
                FROM athena_research_syntheses AS s
                WHERE NOT EXISTS (
                    SELECT 1 FROM athena_professional_research_cycle_owners AS o
                    WHERE o.cycle_hash = s.cycle_hash
                )
                ORDER BY s.id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            raise ValueError("No existe ninguna ATHENA synthesis persistida.")

        cycle_hash = str(row["cycle_hash"])
        return self._canonical.get_by_cycle_hash(cycle_hash=cycle_hash)
