from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol

from app.services.recommendation_shadow_action_calibration_dataset_service import (
    RecommendationShadowActionCalibrationDatasetService,
)


class _DatasetService(Protocol):
    def build(
        self,
        *,
        as_of: datetime,
        symbol: str | None = None,
        horizons: tuple[int, ...] | list[int] = (7, 30, 90, 180, 365),
    ) -> dict[str, Any]: ...


class RecommendationShadowActionCalibrationSplitService:
    """Create purged chronological threshold-research partitions from live evidence.

    Training labels must have been known by ``train_end``. Validation labels must
    have been known by ``validation_end``. Evidence after ``validation_end`` is
    counted but deliberately not returned, preserving a later temporal reserve.
    No action threshold, score, conviction or recommendation is fit here.
    """

    ARTIFACT_VERSION = "shadow-action-calibration-split-v1"

    def __init__(self, *, dataset_service: _DatasetService | None = None) -> None:
        self._dataset_service = (
            dataset_service or RecommendationShadowActionCalibrationDatasetService()
        )

    def build(
        self,
        *,
        train_end: datetime,
        validation_end: datetime,
        as_of: datetime,
        symbol: str | None = None,
        horizons: tuple[int, ...] | list[int] = (7, 30, 90, 180, 365),
    ) -> dict[str, Any]:
        train_cutoff = self._aware_utc(train_end, "train_end")
        validation_cutoff = self._aware_utc(validation_end, "validation_end")
        final_cutoff = self._aware_utc(as_of, "as_of")
        if not train_cutoff < validation_cutoff < final_cutoff:
            raise ValueError("Debe cumplirse train_end < validation_end < as_of.")

        dataset = self._dataset_service.build(
            as_of=final_cutoff,
            symbol=symbol,
            horizons=horizons,
        )
        self._assert_dataset_contract(dataset)
        rows = dataset.get("rows")
        if not isinstance(rows, list):
            raise ValueError("El dataset de calibración carece de rows válidas.")

        train_rows: list[dict[str, Any]] = []
        validation_rows: list[dict[str, Any]] = []
        purged_train_count = 0
        purged_validation_count = 0
        reserved_row_count = 0
        seen_identity: set[tuple[int, int]] = set()

        for raw in rows:
            if not isinstance(raw, dict):
                raise ValueError("Una fila de calibración tiene formato inválido.")
            candidate_id = self._positive_int(raw.get("candidateId"), "candidateId")
            horizon = self._positive_int(raw.get("horizonDays"), "horizonDays")
            identity = (candidate_id, horizon)
            if identity in seen_identity:
                raise ValueError("El dataset contiene una fila candidate/horizon duplicada.")
            seen_identity.add(identity)

            candidate_as_of = self._parse_aware(raw.get("candidateAsOf"), "candidateAsOf")
            outcome_evaluated_at = self._parse_aware(
                raw.get("outcomeEvaluatedAt"), "outcomeEvaluatedAt"
            )
            outcome_due_at = self._parse_aware(raw.get("outcomeDueAt"), "outcomeDueAt")
            if outcome_evaluated_at < outcome_due_at:
                raise ValueError("Una fila fue evaluada antes de que madurase su outcome.")
            if outcome_evaluated_at > final_cutoff:
                raise ValueError("Una etiqueta futura atravesó as_of.")

            copied = dict(raw)
            if candidate_as_of <= train_cutoff:
                if outcome_evaluated_at <= train_cutoff:
                    train_rows.append(copied)
                else:
                    purged_train_count += 1
                continue
            if candidate_as_of <= validation_cutoff:
                if outcome_evaluated_at <= validation_cutoff:
                    validation_rows.append(copied)
                else:
                    purged_validation_count += 1
                continue
            reserved_row_count += 1

        train_rows.sort(key=self._row_sort_key)
        validation_rows.sort(key=self._row_sort_key)
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "sourceDatasetVersion": dataset.get("datasetVersion"),
            "sourceDatasetFingerprint": self._sha256(
                dataset.get("datasetFingerprint"), "datasetFingerprint"
            ),
            "trainEnd": train_cutoff.isoformat(),
            "validationEnd": validation_cutoff.isoformat(),
            "asOf": final_cutoff.isoformat(),
            "symbol": dataset.get("symbol"),
            "requestedHorizons": list(dataset.get("requestedHorizons") or []),
            "trainRowCount": len(train_rows),
            "validationRowCount": len(validation_rows),
            "purgedTrainRowCount": purged_train_count,
            "purgedValidationRowCount": purged_validation_count,
            "reservedFutureRowCount": reserved_row_count,
            "trainRows": train_rows,
            "validationRows": validation_rows,
        }
        return {
            "status": (
                "shadow_action_calibration_split_available"
                if train_rows and validation_rows
                else "shadow_action_calibration_split_insufficient"
            ),
            **core,
            "splitFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": {
                "ordering": "strict_chronological_no_random_shuffle",
                "trainAdmission": "candidate_as_of_lte_train_end_and_outcome_known_by_train_end",
                "validationAdmission": "train_end_lt_candidate_as_of_lte_validation_end_and_outcome_known_by_validation_end",
                "purging": "labels_unknown_at_partition_boundary_are_excluded",
                "futureReserve": "rows_after_validation_end_counted_but_not_returned",
                "futureReserveConsumed": False,
                "thresholdFitting": "not_performed",
                "scoreCalibration": "not_performed",
                "convictionCalibration": "not_performed",
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de split de calibración no compatible.")
        self._assert_shadow(artifact, "split")
        fingerprint = self._sha256(artifact.get("splitFingerprint"), "splitFingerprint")
        core_keys = (
            "artifactVersion",
            "sourceDatasetVersion",
            "sourceDatasetFingerprint",
            "trainEnd",
            "validationEnd",
            "asOf",
            "symbol",
            "requestedHorizons",
            "trainRowCount",
            "validationRowCount",
            "purgedTrainRowCount",
            "purgedValidationRowCount",
            "reservedFutureRowCount",
            "trainRows",
            "validationRows",
        )
        core = {key: artifact.get(key) for key in core_keys}
        if self._fingerprint(core) != fingerprint:
            raise ValueError("El split de calibración fue modificado tras su creación.")
        return artifact

    def _assert_dataset_contract(self, payload: dict[str, Any]) -> None:
        self._assert_shadow(payload, "dataset")
        if payload.get("datasetVersion") != "shadow-action-calibration-v2":
            raise ValueError("El split exige el dataset de calibración provenance-gated v2.")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El dataset carece de policy válida.")
        if policy.get("evidenceSource") != "trusted_persisted_live_cycle_attestation_v1_only":
            raise ValueError("El dataset carece de provenance live confiable.")
        if policy.get("researchHoldoutReuse") is not False:
            raise ValueError("El dataset no puede reutilizar research/holdout.")

    def _assert_shadow(self, payload: dict[str, Any], field: str) -> None:
        if not isinstance(payload, dict):
            raise ValueError(f"{field} debe ser un objeto.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{field} debe mantener advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{field} debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError(f"{field} no puede habilitar recomendaciones.")
        if payload.get("actionThresholdCalibrationResearchEligible") is not False:
            raise ValueError(f"{field} no puede promover calibración automáticamente.")
        if payload.get("action") is not None:
            raise ValueError(f"{field} no puede contener action.")
        if payload.get("score") is not None or payload.get("conviction") is not None:
            raise ValueError(f"{field} no puede publicar score/conviction no calibrados.")

    def _row_sort_key(self, row: dict[str, Any]) -> tuple[str, str, int, int]:
        return (
            str(row.get("candidateAsOf") or ""),
            str(row.get("symbol") or ""),
            self._positive_int(row.get("candidateId"), "candidateId"),
            self._positive_int(row.get("horizonDays"), "horizonDays"),
        )

    def _parse_aware(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero positivo.")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero positivo.") from exc
        if result <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return result

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return result

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
