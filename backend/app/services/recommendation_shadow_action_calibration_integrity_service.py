from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class RecommendationShadowActionCalibrationIntegrityService:
    """Fail-closed semantic validation for calibration split artifacts.

    Fingerprints protect persisted bytes from accidental mutation, but a caller
    must not be able to construct a new self-consistent artifact whose rows
    violate the point-in-time partition semantics. This validator therefore
    re-checks the temporal and shadow contracts independently of the producer.
    """

    EXPECTED_VERSION = "shadow-action-calibration-split-v1"

    def validate(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("El split de calibración debe ser un objeto.")
        if artifact.get("artifactVersion") != self.EXPECTED_VERSION:
            raise ValueError("Versión de split de calibración no compatible.")

        self._assert_shadow_contract(artifact)

        train_end = self._parse_aware(artifact.get("trainEnd"), "trainEnd")
        validation_end = self._parse_aware(
            artifact.get("validationEnd"), "validationEnd"
        )
        as_of = self._parse_aware(artifact.get("asOf"), "asOf")
        if not train_end < validation_end < as_of:
            raise ValueError("El split no respeta trainEnd < validationEnd < asOf.")

        requested_horizons = self._horizons(artifact.get("requestedHorizons"))
        train_rows = self._rows(artifact.get("trainRows"), "trainRows")
        validation_rows = self._rows(
            artifact.get("validationRows"), "validationRows"
        )

        self._exact_nonnegative_int(
            artifact.get("purgedTrainRowCount"), "purgedTrainRowCount"
        )
        self._exact_nonnegative_int(
            artifact.get("purgedValidationRowCount"), "purgedValidationRowCount"
        )
        self._exact_nonnegative_int(
            artifact.get("reservedFutureRowCount"), "reservedFutureRowCount"
        )
        if self._exact_nonnegative_int(
            artifact.get("trainRowCount"), "trainRowCount"
        ) != len(train_rows):
            raise ValueError("trainRowCount no coincide con las filas devueltas.")
        if self._exact_nonnegative_int(
            artifact.get("validationRowCount"), "validationRowCount"
        ) != len(validation_rows):
            raise ValueError("validationRowCount no coincide con las filas devueltas.")

        seen: set[tuple[int, int]] = set()
        previous_key: tuple[datetime, str, int, int] | None = None
        for partition, rows in (("train", train_rows), ("validation", validation_rows)):
            for row in rows:
                identity, sort_key = self._validate_row(
                    row=row,
                    partition=partition,
                    train_end=train_end,
                    validation_end=validation_end,
                    as_of=as_of,
                    requested_horizons=requested_horizons,
                )
                if identity in seen:
                    raise ValueError("Una fila candidate/horizon aparece más de una vez.")
                seen.add(identity)
                if previous_key is not None and sort_key < previous_key:
                    raise ValueError("Las filas del split no mantienen orden cronológico.")
                previous_key = sort_key

        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El split carece de policy válida.")
        required_policy = {
            "ordering": "strict_chronological_no_random_shuffle",
            "purging": "labels_unknown_at_partition_boundary_are_excluded",
            "futureReserveConsumed": False,
            "thresholdFitting": "not_performed",
            "scoreCalibration": "not_performed",
            "convictionCalibration": "not_performed",
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }
        for key, expected in required_policy.items():
            if policy.get(key) != expected:
                raise ValueError(f"La policy del split viola {key}.")

        return artifact

    def _validate_row(
        self,
        *,
        row: dict[str, Any],
        partition: str,
        train_end: datetime,
        validation_end: datetime,
        as_of: datetime,
        requested_horizons: set[int],
    ) -> tuple[tuple[int, int], tuple[datetime, str, int, int]]:
        candidate_id = self._positive_int(row.get("candidateId"), "candidateId")
        horizon = self._positive_int(row.get("horizonDays"), "horizonDays")
        if requested_horizons and horizon not in requested_horizons:
            raise ValueError("Una fila usa un horizonte no solicitado.")

        candidate_as_of = self._parse_aware(row.get("candidateAsOf"), "candidateAsOf")
        due_at = self._parse_aware(row.get("outcomeDueAt"), "outcomeDueAt")
        evaluated_at = self._parse_aware(
            row.get("outcomeEvaluatedAt"), "outcomeEvaluatedAt"
        )
        if evaluated_at < due_at:
            raise ValueError("Una fila fue evaluada antes de madurar su outcome.")
        if evaluated_at > as_of:
            raise ValueError("Una fila contiene una etiqueta conocida después de asOf.")

        if partition == "train":
            if candidate_as_of > train_end or evaluated_at > train_end:
                raise ValueError("Una fila train viola la frontera point-in-time.")
        elif partition == "validation":
            if not train_end < candidate_as_of <= validation_end:
                raise ValueError("Una fila validation viola su frontera cronológica.")
            if evaluated_at > validation_end:
                raise ValueError("Una etiqueta validation no era conocida en su frontera.")
        else:
            raise ValueError("Partición de calibración desconocida.")

        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            raise ValueError("Una fila de calibración carece de symbol.")
        return (candidate_id, horizon), (candidate_as_of, symbol, candidate_id, horizon)

    def _assert_shadow_contract(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El split debe mantener advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("El split debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("El split no puede habilitar recomendaciones.")
        if payload.get("actionThresholdCalibrationResearchEligible") is not False:
            raise ValueError("El split no puede promover calibración automáticamente.")
        if payload.get("action") is not None:
            raise ValueError("El split no puede contener action.")
        if payload.get("score") is not None or payload.get("conviction") is not None:
            raise ValueError("El split no puede publicar score/conviction.")
        if payload.get("actionThresholds") is not None:
            raise ValueError("El split no puede contener umbrales ya ajustados.")

    def _rows(self, value: object, field: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError(f"{field} debe ser una lista.")
        rows: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError(f"{field} contiene una fila inválida.")
            rows.append(item)
        return rows

    def _horizons(self, value: object) -> set[int]:
        if not isinstance(value, list):
            raise ValueError("requestedHorizons debe ser una lista.")
        result: set[int] = set()
        for raw in value:
            horizon = self._positive_int(raw, "requestedHorizons")
            if horizon in result:
                raise ValueError("requestedHorizons contiene duplicados.")
            result.add(horizon)
        return result

    def _parse_aware(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _positive_int(self, value: object, field: str) -> int:
        result = self._exact_nonnegative_int(value, field)
        if result <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return result

    def _exact_nonnegative_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} debe ser entero no negativo.")
        return value
