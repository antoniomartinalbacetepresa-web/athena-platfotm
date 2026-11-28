"""Pre-inference intent ledger, not forecast evidence or promotion authority."""
from datetime import datetime, timezone
import json
import re

from app.database.athena_database import AthenaDatabase
from app.services.persisted_forecast_input_manifest_service import PersistedForecastInputManifestService
from app.services.recommendation_research_prospective_cohort_service import RecommendationResearchProspectiveCohortService as Cohorts


class ResearchInferenceSelectionPlanService:
    def __init__(self, *, database=None, manifest_service=None, now_provider=None):
        self._database = database if database is not None else AthenaDatabase()
        self._manifest = manifest_service if manifest_service is not None else PersistedForecastInputManifestService()
        self._now = now_provider or (lambda: datetime.now(timezone.utc))

    def _initialize(self):
        with self._database.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS athena_research_inference_selection_plans (
                plan_id TEXT PRIMARY KEY, plan_hash TEXT NOT NULL UNIQUE,
                artifact_json TEXT NOT NULL, created_at TEXT NOT NULL)""")

    def _templates(self, templates):
        if not isinstance(templates, list) or not 1 <= len(templates) <= 200:
            raise ValueError("Explicit bounded template universe required")
        result = json.loads(json.dumps(templates, allow_nan=False))
        identities, cycles = set(), set()
        for template in result:
            self._manifest.materialize_specification(template)
            identity = template["specificationId"]
            cycle = (template["cycleHash"], template["horizonSeconds"])
            if identity in identities or cycle in cycles:
                raise ValueError("Duplicated planned forecast identity")
            identities.add(identity)
            cycles.add(cycle)
        return sorted(result, key=lambda item: item["specificationHash"])

    def register(self, *, plan_id, templates, model_artifact_hash):
        if not isinstance(plan_id, str) or not plan_id.strip():
            raise ValueError("Explicit plan identity required")
        if not isinstance(model_artifact_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", model_artifact_hash):
            raise ValueError("Explicit model artifact pin required")
        selected = self._templates(templates)
        self._initialize()
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT * FROM athena_research_inference_selection_plans WHERE plan_id = ?", (plan_id,)).fetchone()
            if existing is not None:
                artifact = self._validate(existing, validated_templates=selected)
                if artifact["templates"] != selected or artifact["modelArtifactHash"] != model_artifact_hash:
                    raise ValueError("Cannot replace sealed inference selection")
                return artifact
            sealed = Cohorts._time(self._now())
            if any(not max(Cohorts._time(i["availableAt"]) for i in t["inputEvidence"]) <= sealed <= Cohorts._time(t["forecastEvidence"]["availableAt"]) <= Cohorts._time(t["periodStart"]) for t in selected):
                raise ValueError("Inference selection must precede forecast deadlines")
            artifact = {"artifactVersion": "research-inference-selection-plan-v1", "planId": plan_id,
                        "templates": selected, "modelArtifactHash": model_artifact_hash,
                        "sealedAt": sealed.isoformat(), "forecastEvidenceProduced": False,
                        "executionEnforcementImplemented": False, "productionEligible": False,
                        "productionLearningEligible": False, "automaticTrading": False}
            artifact["planHash"] = Cohorts._hash(artifact)
            connection.execute("INSERT INTO athena_research_inference_selection_plans VALUES (?, ?, ?, ?)",
                               (plan_id, artifact["planHash"], json.dumps(artifact), sealed.isoformat()))
            return artifact

    def _validate(self, row, *, validated_templates=None):
        artifact = json.loads(row["artifact_json"])
        core = {k: v for k, v in artifact.items() if k != "planHash"}
        if (artifact.get("planHash") != Cohorts._hash(core) or artifact["planHash"] != row["plan_hash"]
                or artifact.get("planId") != row["plan_id"] or artifact.get("sealedAt") != row["created_at"]
                or artifact.get("artifactVersion") != "research-inference-selection-plan-v1"):
            raise ValueError("Inference selection was modified")
        if any(artifact.get(flag) is not False for flag in ("forecastEvidenceProduced", "executionEnforcementImplemented",
                "productionEligible", "productionLearningEligible", "automaticTrading")):
            raise ValueError("Inference plan cannot confer authority")
        # Input revalidation writes legacy schema metadata; perform it before
        # acquiring the selection write lock, never through a second connection.
        selected = validated_templates if validated_templates is not None else self._templates(artifact["templates"])
        if selected != artifact["templates"] or any(not max(Cohorts._time(i["availableAt"]) for i in t["inputEvidence"]) <= Cohorts._time(artifact["sealedAt"]) <= Cohorts._time(t["forecastEvidence"]["availableAt"]) <= Cohorts._time(t["periodStart"]) for t in selected):
            raise ValueError("Invalid sealed selection timing/order")
        if not re.fullmatch(r"[0-9a-f]{64}", artifact["modelArtifactHash"]):
            raise ValueError("Invalid model pin")
        return artifact

    def get(self, *, plan_id):
        self._initialize()
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM athena_research_inference_selection_plans WHERE plan_id = ?", (plan_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown inference selection plan")
        return self._validate(row)
