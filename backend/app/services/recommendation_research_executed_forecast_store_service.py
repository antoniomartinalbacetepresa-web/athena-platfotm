from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_research_evaluation_specification_repository import RecommendationResearchEvaluationSpecificationRepository
from app.repositories.recommendation_research_model_execution_receipt_repository import RecommendationResearchModelExecutionReceiptRepository
from app.services.recommendation_research_model_execution_receipt_service import RecommendationResearchModelExecutionReceiptService
from app.services.recommendation_research_model_executor_service import RecommendationResearchModelExecutorService


class RecommendationResearchExecutedForecastStoreService:
    """Internal observed execution → atomic specification/receipt-v2 persistence.

    Uses the existing two tables, not a parallel forecast store. Deployment owns
    runner selection and artifact pinning; no HTTP caller supplies observations.
    """

    def __init__(
        self, *, database: AthenaDatabase, executor: RecommendationResearchModelExecutorService,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._executor = executor
        self._now = now_provider or (lambda: datetime.now(timezone.utc))
        self.receipt_service = RecommendationResearchModelExecutionReceiptService(model_executor=executor)
        self.specifications = RecommendationResearchEvaluationSpecificationRepository(database, now_provider=self._now)
        self.receipts = RecommendationResearchModelExecutionReceiptRepository(
            database, service=self.receipt_service, now_provider=self._now,
        )

    def execute_and_persist(
        self, *, specification: dict[str, Any], model_bytes: bytes, pinned_artifact_hash: str,
    ) -> dict[str, Any]:
        self.specifications.initialize()
        self.receipts.initialize()
        observation = self._executor.execute(
            specification=specification, model_bytes=model_bytes,
            pinned_artifact_hash=pinned_artifact_hash,
        )
        snapshot = self._executor._manifest.materialize_specification(specification)
        # Validate payloads before acquiring the database write lock. Repository
        # read initialization also writes schema metadata on this legacy database.
        provisional_record = {
            "artifact": specification,
            "specification_hash": specification["specificationHash"],
            "created_at": self._now().isoformat(),
        }
        receipt = self.receipt_service.build_observed(
            specification_record=provisional_record, observation=observation, model_bytes=model_bytes,
        )
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = self.specifications.append(artifact=specification, connection=connection)
            persisted = self.receipts.append(
                artifact=receipt, specification_record=record, connection=connection,
                allow_observed_receipt=True,
                materialized_snapshot=snapshot,
            )
        return {
            "specification": record,
            "receipt": persisted,
            "productionEligible": False,
            "productionLearningEligible": False,
            "automaticTrading": False,
        }
