from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from statistics import fmean
from typing import Any, Protocol

from app.services.recommendation_shadow_action_calibration_integrity_service import (
    RecommendationShadowActionCalibrationIntegrityService,
)
from app.services.recommendation_shadow_action_calibration_split_service import (
    RecommendationShadowActionCalibrationSplitService,
)


class _FingerprintValidator(Protocol):
    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class _SemanticValidator(Protocol):
    def validate(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationShadowActionCalibrationEvidenceService:
    """Measure whether a PIT split contains credible threshold-research evidence.

    This service deliberately does *not* fit BUY/HOLD/REDUCE/SELL thresholds. The
    current live calibration rows contain prediction and realized excess return,
    but they do not yet encode portfolio ownership/state, trade size or an
    immutable transaction-cost/slippage objective. Optimizing reduce/sell without
    those inputs would silently invent economic semantics.

    The service therefore performs the useful preceding step: revalidate the
    split cryptographically and semantically, then measure signal discrimination,
    outcome balance and train-to-validation stability by horizon. Future-reserve
    rows remain unavailable and untouched.
    """

    ARTIFACT_VERSION = "shadow-action-calibration-evidence-v1"

    def __init__(
        self,
        *,
        fingerprint_validator: _FingerprintValidator | None = None,
        semantic_validator: _SemanticValidator | None = None,
        min_train_rows: int = 20,
        min_validation_rows: int = 10,
        min_outcome_sign_rows: int = 3,
    ) -> None:
        if min_train_rows < 4 or min_validation_rows < 4:
            raise ValueError("Los mínimos train/validation deben ser al menos 4.")
        if min_outcome_sign_rows < 1:
            raise ValueError("min_outcome_sign_rows debe ser positivo.")
        self._fingerprint_validator = (
            fingerprint_validator or RecommendationShadowActionCalibrationSplitService()
        )
        self._semantic_validator = (
            semantic_validator or RecommendationShadowActionCalibrationIntegrityService()
        )
        self._min_train_rows = min_train_rows
        self._min_validation_rows = min_validation_rows
        self._min_outcome_sign_rows = min_outcome_sign_rows

    def assess(self, split: dict[str, Any]) -> dict[str, Any]:
        # Both barriers are mandatory. A valid SHA-256 does not prove PIT semantics,
        # and semantically plausible caller JSON is not enough without provenance.
        validated = self._fingerprint_validator.validate_artifact(split)
        if validated is not split:
            raise ValueError("El validador de fingerprint sustituyó el artefacto.")
        semantic = self._semantic_validator.validate(split)
        if semantic is not split:
            raise ValueError("El validador semántico sustituyó el artefacto.")

        train_rows = self._rows(split.get("trainRows"), "trainRows")
        validation_rows = self._rows(split.get("validationRows"), "validationRows")
        requested = self._horizons(split.get("requestedHorizons"))
        train_by_horizon = self._group(train_rows)
        validation_by_horizon = self._group(validation_rows)

        horizons: dict[str, Any] = {}
        sufficient_count = 0
        validation_support_count = 0
        for horizon in requested:
            train_metrics = self._partition_metrics(train_by_horizon.get(horizon, []))
            validation_metrics = self._partition_metrics(
                validation_by_horizon.get(horizon, [])
            )
            evidence_reasons: list[str] = []
            if train_metrics["rowCount"] < self._min_train_rows:
                evidence_reasons.append("insufficient_train_rows")
            if validation_metrics["rowCount"] < self._min_validation_rows:
                evidence_reasons.append("insufficient_validation_rows")
            for partition_name, metrics in (
                ("train", train_metrics),
                ("validation", validation_metrics),
            ):
                if metrics["positiveOutcomeCount"] < self._min_outcome_sign_rows:
                    evidence_reasons.append(f"insufficient_{partition_name}_positive_outcomes")
                if metrics["negativeOutcomeCount"] < self._min_outcome_sign_rows:
                    evidence_reasons.append(f"insufficient_{partition_name}_negative_outcomes")
                if metrics["spearmanCorrelation"] is None:
                    evidence_reasons.append(f"degenerate_{partition_name}_signal")

            evidence_sufficient = not evidence_reasons
            if evidence_sufficient:
                sufficient_count += 1

            validation_support_reasons: list[str] = []
            if not evidence_sufficient:
                validation_support_reasons.append("evidence_not_sufficient")
            else:
                validation_corr = validation_metrics["spearmanCorrelation"]
                validation_spread = validation_metrics["tailRealizedSpread"]
                train_spread = train_metrics["tailRealizedSpread"]
                if validation_corr is None or validation_corr <= 0.0:
                    validation_support_reasons.append("nonpositive_validation_rank_correlation")
                if validation_spread is None or validation_spread <= 0.0:
                    validation_support_reasons.append("nonpositive_validation_tail_spread")
                if train_spread is None or train_spread <= 0.0:
                    validation_support_reasons.append("nonpositive_train_tail_spread")

            validation_support = not validation_support_reasons
            if validation_support:
                validation_support_count += 1

            horizons[str(horizon)] = {
                "horizonDays": horizon,
                "train": train_metrics,
                "validation": validation_metrics,
                "evidenceSufficientForThresholdResearch": evidence_sufficient,
                "evidenceReasons": evidence_reasons,
                "validationSupportsSignalDiscrimination": validation_support,
                "validationSupportReasons": validation_support_reasons,
            }

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "sourceSplitFingerprint": self._sha256(split.get("splitFingerprint"), "splitFingerprint"),
            "trainEnd": split.get("trainEnd"),
            "validationEnd": split.get("validationEnd"),
            "asOf": split.get("asOf"),
            "requestedHorizons": requested,
            "horizonCount": len(requested),
            "evidenceSufficientHorizonCount": sufficient_count,
            "validationSupportHorizonCount": validation_support_count,
            "horizons": horizons,
            "criteria": {
                "minTrainRowsPerHorizon": self._min_train_rows,
                "minValidationRowsPerHorizon": self._min_validation_rows,
                "minPositiveAndNegativeOutcomesPerPartition": self._min_outcome_sign_rows,
                "validationSignalChecks": [
                    "positive_spearman_rank_correlation",
                    "positive_top_minus_bottom_quartile_realized_excess_spread",
                ],
            },
        }
        return {
            "status": (
                "shadow_action_calibration_evidence_available"
                if sufficient_count > 0
                else "shadow_action_calibration_evidence_insufficient"
            ),
            **core,
            "evidenceFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "blockingRequirementsBeforeActionThresholdFitting": [
                "immutable_position_state_and_action_semantics_contract",
                "precommitted_transaction_cost_and_slippage_objective",
                "threshold_candidate_generation_from_train_only",
                "threshold_selection_from_validation_only",
                "untouched_future_temporal_reserve_for_threshold_confirmation",
            ],
            "policy": {
                "purpose": "diagnostic_evidence_gate_not_action_calibration",
                "futureReserveConsumed": False,
                "thresholdFitting": "not_performed",
                "scoreCalibration": "not_performed",
                "convictionCalibration": "not_performed",
                "economicUtilityAssumptionsInvented": False,
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _partition_metrics(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        pairs: list[tuple[float, float]] = []
        for row in rows:
            expected = self._finite(row.get("expectedExcessReturn"), "expectedExcessReturn")
            realized = self._finite(row.get("realizedExcessReturn"), "realizedExcessReturn")
            pairs.append((expected, realized))

        positives = sum(1 for _, realized in pairs if realized > 0.0)
        negatives = sum(1 for _, realized in pairs if realized < 0.0)
        zeros = len(pairs) - positives - negatives
        sign_correct = sum(
            1
            for expected, realized in pairs
            if (expected > 0.0 and realized > 0.0)
            or (expected < 0.0 and realized < 0.0)
            or (expected == 0.0 and realized == 0.0)
        )
        correlation = self._spearman(pairs)
        spread = self._tail_spread(pairs)
        return {
            "rowCount": len(pairs),
            "positiveOutcomeCount": positives,
            "negativeOutcomeCount": negatives,
            "zeroOutcomeCount": zeros,
            "directionAccuracy": (sign_correct / len(pairs)) if pairs else None,
            "meanExpectedExcessReturn": fmean(item[0] for item in pairs) if pairs else None,
            "meanRealizedExcessReturn": fmean(item[1] for item in pairs) if pairs else None,
            "spearmanCorrelation": correlation,
            "tailRealizedSpread": spread,
        }

    def _tail_spread(self, pairs: list[tuple[float, float]]) -> float | None:
        if len(pairs) < 4:
            return None
        ordered = sorted(pairs, key=lambda item: (item[0], item[1]))
        count = max(1, len(ordered) // 4)
        low = fmean(item[1] for item in ordered[:count])
        high = fmean(item[1] for item in ordered[-count:])
        return high - low

    def _spearman(self, pairs: list[tuple[float, float]]) -> float | None:
        if len(pairs) < 2:
            return None
        expected = [item[0] for item in pairs]
        realized = [item[1] for item in pairs]
        x = self._average_ranks(expected)
        y = self._average_ranks(realized)
        x_mean = fmean(x)
        y_mean = fmean(y)
        numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
        x_sq = sum((a - x_mean) ** 2 for a in x)
        y_sq = sum((b - y_mean) ** 2 for b in y)
        if x_sq <= 0.0 or y_sq <= 0.0:
            return None
        return numerator / math.sqrt(x_sq * y_sq)

    def _average_ranks(self, values: list[float]) -> list[float]:
        ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
        ranks = [0.0] * len(values)
        index = 0
        while index < len(ordered):
            end = index + 1
            while end < len(ordered) and ordered[end][1] == ordered[index][1]:
                end += 1
            average_rank = ((index + 1) + end) / 2.0
            for position in range(index, end):
                ranks[ordered[position][0]] = average_rank
            index = end
        return ranks

    def _group(self, rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
        result: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            horizon = self._positive_int(row.get("horizonDays"), "horizonDays")
            result[horizon].append(row)
        return dict(result)

    def _rows(self, value: object, field: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError(f"{field} debe ser una lista.")
        if any(not isinstance(item, dict) for item in value):
            raise ValueError(f"{field} contiene una fila inválida.")
        return list(value)

    def _horizons(self, value: object) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("requestedHorizons debe ser una lista no vacía.")
        result: list[int] = []
        seen: set[int] = set()
        for raw in value:
            horizon = self._positive_int(raw, "requestedHorizons")
            if horizon in seen:
                raise ValueError("requestedHorizons contiene duplicados.")
            seen.add(horizon)
            result.append(horizon)
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
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
