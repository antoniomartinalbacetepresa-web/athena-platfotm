from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Callable

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_research_evaluation_specification_repository import RecommendationResearchEvaluationSpecificationRepository
from app.repositories.recommendation_research_model_execution_receipt_repository import RecommendationResearchModelExecutionReceiptRepository
from app.services.recommendation_research_model_execution_receipt_service import RecommendationResearchModelExecutionReceiptService
from app.services.recommendation_research_model_executor_service import RecommendationResearchModelExecutorService
from app.services.recommendation_research_evaluation_specification_service import RecommendationResearchEvaluationSpecificationService


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
        RecommendationResearchEvaluationSpecificationService().validate_artifact(specification)
        if not isinstance(model_bytes, bytes) or not 0 < len(model_bytes) <= 10_000_000:
            raise ValueError("Se requieren bytes de modelo limitados a 10 MB.")
        actual_hash = hashlib.sha256(model_bytes).hexdigest()
        if actual_hash != pinned_artifact_hash:
            raise ValueError("Los bytes cargados no coinciden con el artefacto fijado.")
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT specification_hash FROM athena_research_evaluation_specifications WHERE specification_hash = ?",
                (specification["specificationHash"],),
            ).fetchone()
        if existing is not None:
            record = self.specifications.get_by_hash(specification_hash=specification["specificationHash"])
            if record["artifact"] != specification:
                raise ValueError("El reintento no conserva la specification original exacta.")
            persisted = self.receipts.get_by_specification_hash(
                specification_hash=specification["specificationHash"], specification_record=record,
            )
            receipt = persisted["artifact"]
            if receipt["artifactVersion"] != "research-model-execution-receipt-v2":
                raise ValueError("No se puede reutilizar un recibo declarativo como ejecución observada.")
            if receipt["model"]["artifactHash"] != actual_hash:
                raise ValueError("El reintento cambió los bytes del modelo original.")
            return {
                "specification": record, "receipt": persisted, "reused": True,
                "productionEligible": False, "productionLearningEligible": False,
                "automaticTrading": False,
            }
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
            "reused": False,
            "productionEligible": False,
            "productionLearningEligible": False,
            "automaticTrading": False,
        }
