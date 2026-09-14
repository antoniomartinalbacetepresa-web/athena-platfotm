from __future__ import annotations

from typing import Any, Sequence

from app.services.recommendation_research_forecast_error_service import RecommendationResearchForecastErrorService


class RecommendationResearchProspectiveCohortErrorBindingService:
    """Bind measured errors to a frozen cohort without claiming skill."""

    def __init__(self) -> None:
        self._errors = RecommendationResearchForecastErrorService()

    def bind(self, *, cohort: dict[str, Any], error_records: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(cohort, dict) or cohort.get("artifactVersion") != "research-prospective-cohort-v1":
            raise ValueError("Se requiere una cohorte prospectiva preseleccionada.")
        if any(cohort.get(flag) is not False for flag in ("productionEligible", "productionLearningEligible", "automaticTrading")):
            raise ValueError("La cohorte intentó activar autoridad productiva.")
        selected = cohort.get("specificationHashes")
        if not isinstance(selected, list) or len(set(selected)) != len(selected) or selected != sorted(selected):
            raise ValueError("La cohorte no conserva una selección canónica única.")
        if not isinstance(error_records, Sequence) or isinstance(error_records, (str, bytes)):
            raise ValueError("error_records debe ser una secuencia explícita.")
        seen: set[str] = set()
        for record in error_records:
            artifact = record.get("artifact") if isinstance(record, dict) else None
            if not isinstance(artifact, dict):
                raise ValueError("Forecast error persistido inválido.")
            self._errors.validate_artifact(artifact)
            spec_hash = artifact.get("specificationHash")
            if spec_hash not in selected:
                raise ValueError("El error pertenece a un forecast ajeno a la cohorte.")
            if spec_hash in seen:
                raise ValueError("La cohorte reutiliza el mismo forecast error.")
            seen.add(spec_hash)
        missing = sorted(set(selected) - seen)
        return {"cohortHash": cohort.get("cohortHash"), "selectedCount": len(selected),
                "measuredErrorCount": len(seen), "missingSpecificationHashes": missing,
                "membershipComplete": not missing, "outcomeEvidenceVerified": bool(seen),
                "skillClaim": "forbidden", "productionEligible": False,
                "productionLearningEligible": False, "automaticTrading": False}
