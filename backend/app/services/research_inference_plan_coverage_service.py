"""Reconcile planned intent with existing observed forecasts, never infer outcomes."""
from copy import deepcopy

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_research_evaluation_specification_repository import RecommendationResearchEvaluationSpecificationRepository
from app.repositories.recommendation_research_model_execution_receipt_repository import RecommendationResearchModelExecutionReceiptRepository
from app.services.research_inference_selection_plan_service import ResearchInferenceSelectionPlanService
from app.services.recommendation_research_prospective_cohort_service import RecommendationResearchProspectiveCohortService as Cohorts


class ResearchInferencePlanCoverageService:
    def __init__(self, *, database=None, plans=None, specifications=None, receipts=None):
        self._database = database if database is not None else AthenaDatabase()
        self._plans = plans if plans is not None else ResearchInferenceSelectionPlanService(database=self._database)
        self._specifications = specifications if specifications is not None else RecommendationResearchEvaluationSpecificationRepository(self._database)
        self._receipts = receipts if receipts is not None else RecommendationResearchModelExecutionReceiptRepository(self._database)

    def build(self, *, plan_id):
        plan = self._plans.get(plan_id=plan_id)
        self._specifications.initialize()
        generated, missing = [], []
        for template in plan["templates"]:
            with self._database.connect() as connection:
                rows = connection.execute(
                    "SELECT specification_hash FROM athena_research_evaluation_specifications "
                    "WHERE specification_id = ? OR (cycle_hash = ? AND horizon_seconds = ?)",
                    (template["specificationId"], template["cycleHash"], template["horizonSeconds"]),
                ).fetchall()
            if not rows:
                missing.append(template["specificationHash"])
                continue
            if len(rows) != 1:
                raise ValueError("Ambiguous planned forecast identity")
            ref = rows[0]["specification_hash"]
            record = self._specifications.get_by_hash(specification_hash=ref)
            final = record["artifact"]
            restored = deepcopy(final)
            restored["specificationHash"] = template["specificationHash"]
            restored["expectedValue"] = template["expectedValue"]
            restored["forecastEvidence"]["availableAt"] = template["forecastEvidence"]["availableAt"]
            if restored != template:
                raise ValueError("Generated forecast changed the planned template")
            if Cohorts._time(final["forecastEvidence"]["availableAt"]) > Cohorts._time(template["forecastEvidence"]["availableAt"]):
                raise ValueError("Generated forecast missed its planned deadline")
            receipt = self._receipts.get_by_specification_hash(specification_hash=ref, specification_record=record)["artifact"]
            if receipt["artifactVersion"] != "research-model-execution-receipt-v2":
                raise ValueError("Planned coverage requires observed execution")
            if receipt["model"]["artifactHash"] != plan["modelArtifactHash"]:
                raise ValueError("Generated model does not match planned artifact")
            if Cohorts._time(receipt["observation"]["startedAt"]) < Cohorts._time(plan["sealedAt"]):
                raise ValueError("Execution began before selection was sealed")
            generated.append({"templateHash": template["specificationHash"], "specificationHash": ref,
                              "receiptHash": receipt["receiptHash"]})
        return {"planHash": plan["planHash"], "selectedCount": len(plan["templates"]),
                "generatedCount": len(generated), "generated": generated,
                "missingTemplateHashes": sorted(missing), "generationComplete": not missing,
                "missingReason": "unknown_no_persisted_generation", "outcomeEvidenceVerified": False,
                "productionEligible": False, "productionLearningEligible": False,
                "automaticTrading": False}
