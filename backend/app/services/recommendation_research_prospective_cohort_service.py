from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Callable

from app.services.recommendation_research_executed_forecast_store_service import RecommendationResearchExecutedForecastStoreService


class RecommendationResearchProspectiveCohortService:
    """Internal preselection ledger, not another forecast/outcome store.

    References existing observed v3 forecasts. The fixed denominator includes
    missing evaluations; it never infers approval or predictive skill.
    """

    def __init__(self, *, store: RecommendationResearchExecutedForecastStoreService,
                 now_provider: Callable[[], datetime] | None = None) -> None:
        self._store = store
        self._now = now_provider or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    @staticmethod
    def _time(value: str | datetime) -> datetime:
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("La cohorte requiere timestamps con zona horaria.")
        return result.astimezone(timezone.utc)

    @staticmethod
    def _refs(values: list[str]) -> list[str]:
        if not isinstance(values, list) or not 1 <= len(values) <= 5000:
            raise ValueError("La selección requiere entre 1 y 5000 specification hashes.")
        if any(not isinstance(x, str) or not re.fullmatch(r"[0-9a-f]{64}", x) for x in values):
            raise ValueError("Specification hash inválido.")
        if len(set(values)) != len(values):
            raise ValueError("La selección contiene duplicados.")
        return sorted(values)

    def _initialize(self) -> None:
        with self._store._database.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS athena_research_prospective_cohorts (
                cohort_id TEXT PRIMARY KEY, cohort_hash TEXT NOT NULL UNIQUE,
                artifact_json TEXT NOT NULL, created_at TEXT NOT NULL
            )""")

    def _forecasts(self, refs: list[str]) -> list[dict[str, Any]]:
        records = []
        for ref in refs:
            record = self._store.specifications.get_by_hash(specification_hash=ref)
            if record["artifact"]["artifactVersion"] != "research-evaluation-specification-v3":
                raise ValueError("La preselección requiere forecasts v3 observados.")
            receipt = self._store.receipts.get_by_specification_hash(
                specification_hash=ref, specification_record=record)
            if receipt["artifact"]["artifactVersion"] != "research-model-execution-receipt-v2":
                raise ValueError("La preselección no acepta recibos declarativos.")
            record["receipt_created_at"] = receipt["created_at"]
            records.append(record)
        methods = {r["artifact"]["forecastEvidence"]["method"] for r in records}
        horizons = {r["artifact"]["horizonSeconds"] for r in records}
        if len(methods) != 1 or len(horizons) != 1:
            raise ValueError("La cohorte requiere un único método y horizonte.")
        return records

    def register(self, *, cohort_id: str, specification_hashes: list[str]) -> dict[str, Any]:
        if not isinstance(cohort_id, str) or not cohort_id.strip():
            raise ValueError("cohort_id obligatorio.")
        refs = self._refs(specification_hashes)
        self._initialize()
        with self._store._database.connect() as connection:
            existing = connection.execute("SELECT 1 FROM athena_research_prospective_cohorts WHERE cohort_id = ?",
                                          (cohort_id,)).fetchone()
        if existing:
            original = self.get(cohort_id=cohort_id)
            if original["specificationHashes"] != refs:
                raise ValueError("No se puede cambiar la selección precomprometida.")
            return original
        records = self._forecasts(refs)  # Revalidation precedes the SQLite write lock.
        with self._store._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sealed = self._time(self._now())
            if any(not max(self._time(r["created_at"]), self._time(r["receipt_created_at"])) <= sealed <= self._time(r["artifact"]["periodStart"])
                   for r in records):
                raise ValueError("La selección debe sellarse antes del inicio de todos los periodos.")
            artifact = {
                "artifactVersion": "research-prospective-cohort-v1", "cohortId": cohort_id,
                "specificationHashes": refs, "sealedAt": sealed.isoformat(),
                "method": records[0]["artifact"]["forecastEvidence"]["method"],
                "horizonSeconds": records[0]["artifact"]["horizonSeconds"],
                "productionEligible": False, "productionLearningEligible": False,
                "automaticTrading": False,
            }
            artifact["cohortHash"] = self._hash(artifact)
            connection.execute("INSERT INTO athena_research_prospective_cohorts VALUES (?, ?, ?, ?)",
                               (cohort_id, artifact["cohortHash"], json.dumps(artifact), sealed.isoformat()))
        return artifact

    def get(self, *, cohort_id: str) -> dict[str, Any]:
        self._initialize()
        with self._store._database.connect() as connection:
            row = connection.execute("SELECT * FROM athena_research_prospective_cohorts WHERE cohort_id = ?",
                                     (cohort_id,)).fetchone()
        if row is None:
            raise ValueError("No existe la cohorte preseleccionada.")
        artifact = json.loads(row["artifact_json"])
        core = {k: v for k, v in artifact.items() if k != "cohortHash"}
        if (artifact.get("cohortHash") != self._hash(core) or artifact["cohortHash"] != row["cohort_hash"]
                or artifact.get("cohortId") != row["cohort_id"] or artifact.get("sealedAt") != row["created_at"]
                or artifact.get("artifactVersion") != "research-prospective-cohort-v1"):
            raise ValueError("La cohorte preseleccionada fue modificada.")
        if any(artifact.get(flag) is not False for flag in
               ("productionEligible", "productionLearningEligible", "automaticTrading")):
            raise ValueError("La cohorte intentó activar autoridad productiva.")
        refs = self._refs(artifact["specificationHashes"])
        if refs != artifact["specificationHashes"]:
            raise ValueError("La selección perdió su orden canónico.")
        records = self._forecasts(refs)
        sealed = self._time(artifact["sealedAt"])
        if any(not max(self._time(r["created_at"]), self._time(r["receipt_created_at"])) <= sealed <= self._time(r["artifact"]["periodStart"])
               for r in records):
            raise ValueError("La cohorte no tiene selección ex ante válida.")
        if (artifact["method"] != records[0]["artifact"]["forecastEvidence"]["method"] or
                artifact["horizonSeconds"] != records[0]["artifact"]["horizonSeconds"]):
            raise ValueError("La cohorte perdió su método/horizonte.")
        return artifact

    def coverage(self, *, cohort_id: str, evaluated_specification_hashes: list[str]) -> dict[str, Any]:
        """Membership accounting only; supplied refs do not prove outcome measurement."""
        artifact = self.get(cohort_id=cohort_id)
        if not isinstance(evaluated_specification_hashes, list):
            raise ValueError("Las referencias evaluadas deben ser una lista explícita.")
        evaluated = self._refs(evaluated_specification_hashes) if evaluated_specification_hashes else []
        selected = set(artifact["specificationHashes"])
        if set(evaluated) - selected:
            raise ValueError("La evaluación añade forecasts ajenos a la preselección.")
        missing = sorted(selected - set(evaluated))
        return {"cohortHash": artifact["cohortHash"], "selectedCount": len(selected),
                "providedEvaluationCount": len(evaluated), "missingSpecificationHashes": missing,
                "membershipComplete": not missing, "outcomeEvidenceVerified": False,
                "productionEligible": False, "productionLearningEligible": False, "automaticTrading": False}
