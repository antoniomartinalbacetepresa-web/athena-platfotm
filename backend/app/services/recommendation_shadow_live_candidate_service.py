from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Protocol

from app.services.recommendation_evidence_gate_service import (
    RecommendationEvidenceGateService,
)
from app.services.recommendation_shadow_gated_freeze_service import (
    RecommendationShadowGatedFreezeService,
)
from app.services.recommendation_shadow_post_selection_multi_horizon_service import (
    RecommendationShadowPostSelectionMultiHorizonService,
)


class _EvidenceGateService(Protocol):
    def evaluate(self, *, symbol: str, as_of: datetime) -> object: ...


class RecommendationShadowLiveCandidateService:
    """Apply confirmed frozen models to current PIT evidence without advice.

    The output is deliberately narrower than a recommendation: a continuous
    expected excess-return point estimate for individually confirmed horizons,
    plus transparent standardized feature contributions. Action thresholds,
    conviction and scenarios remain unavailable until separately calibrated and
    validated on evidence that has not already been consumed by confirmation.
    """

    ARTIFACT_VERSION = "shadow-live-candidate-v1"
    FEATURE_SCHEMA_VERSION = "shadow-evidence-v1"

    def __init__(
        self,
        *,
        evidence_gate_service: _EvidenceGateService | None = None,
        gated_freeze_service: RecommendationShadowGatedFreezeService | None = None,
        confirmation_service: RecommendationShadowPostSelectionMultiHorizonService | None = None,
    ) -> None:
        self._evidence_gate_service = (
            evidence_gate_service or RecommendationEvidenceGateService()
        )
        self._gated_freeze_service = (
            gated_freeze_service or RecommendationShadowGatedFreezeService()
        )
        self._confirmation_service = (
            confirmation_service or RecommendationShadowPostSelectionMultiHorizonService()
        )

    def build(
        self,
        *,
        symbol: str,
        as_of: datetime,
        gated_bundles: list[dict[str, Any]],
        confirmation_artifact: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        cutoff = self._aware_utc(as_of, "as_of")

        confirmation = self._confirmation_service.validate_artifact(
            confirmation_artifact
        )
        self._assert_shadow(confirmation, "confirmation_artifact")
        if confirmation.get("postSelectionProtocolEvidenceReady") is not True:
            return self._blocked(
                symbol=normalized_symbol,
                cutoff=cutoff,
                reason="post_selection_multi_horizon_confirmation_not_ready",
                confirmation=confirmation,
            )
        confirmation_as_of = self._parse_aware(confirmation.get("asOf"), "confirmation.asOf")
        if confirmation_as_of > cutoff:
            raise ValueError("La confirmación no puede proceder del futuro respecto al as_of actual.")

        bundles = self._validated_bundle_map(gated_bundles, confirmation)
        gate_payload = self._gate_payload(normalized_symbol, cutoff)
        if gate_payload.get("status") != "evidence_ready_for_calibration":
            return self._blocked(
                symbol=normalized_symbol,
                cutoff=cutoff,
                reason="current_point_in_time_evidence_not_ready",
                confirmation=confirmation,
                blockers=list(gate_payload.get("blockers") or []),
            )

        current_features = self._feature_map(gate_payload)
        horizon_outputs: dict[str, dict[str, Any]] = {}
        for raw_horizon in confirmation.get("requestedHorizons", []):
            horizon = int(raw_horizon)
            confirmation_horizon = confirmation.get("horizons", {}).get(str(horizon))
            if not isinstance(confirmation_horizon, dict):
                raise ValueError("La confirmación carece del detalle de un horizonte solicitado.")
            if confirmation_horizon.get("passesConfirmationProtocol") is not True:
                horizon_outputs[str(horizon)] = {
                    "horizonDays": horizon,
                    "status": "not_inferred_horizon_not_confirmed",
                    "expectedExcessReturn": None,
                    "modelFingerprint": confirmation_horizon.get("modelFingerprint"),
                }
                continue

            bundle = bundles.get(horizon)
            if bundle is None:
                raise ValueError("Falta el gated bundle de un horizonte confirmado.")
            model = bundle["frozenModel"]
            if model.get("fingerprint") != confirmation_horizon.get("modelFingerprint"):
                raise ValueError("El modelo live no coincide con el modelo confirmado.")
            prediction, explanation = self._predict(current_features, model)
            horizon_outputs[str(horizon)] = {
                "horizonDays": horizon,
                "status": "shadow_continuous_excess_return_inferred",
                "expectedExcessReturn": prediction,
                "modelFingerprint": model["fingerprint"],
                "bundleFingerprint": bundle["bundleFingerprint"],
                "featureSchemaVersion": model.get("featureSchemaVersion"),
                "explanation": explanation,
                "uncertaintyStatus": "not_calibrated_for_live_decision",
                "scenarioStatus": "not_calibrated",
            }

        inferred_count = sum(
            1
            for payload in horizon_outputs.values()
            if payload.get("expectedExcessReturn") is not None
        )
        if inferred_count == 0:
            return self._blocked(
                symbol=normalized_symbol,
                cutoff=cutoff,
                reason="no_individually_confirmed_horizon_available_for_inference",
                confirmation=confirmation,
            )

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "symbol": normalized_symbol,
            "asOf": cutoff.isoformat(),
            "instrumentId": gate_payload.get("instrumentId"),
            "currentEvidenceStatus": gate_payload.get("status"),
            "confirmationEvidenceFingerprint": confirmation[
                "confirmationEvidenceFingerprint"
            ],
            "researchGateFingerprint": confirmation.get("researchGateFingerprint"),
            "researchCutoff": confirmation.get("researchCutoff"),
            "inferredHorizonCount": inferred_count,
            "horizons": horizon_outputs,
            "riskContext": self._risk_context(gate_payload),
            "valuationContext": self._valuation_context(gate_payload),
            "fundamentalContext": self._fundamental_context(gate_payload),
        }
        fingerprint = self._fingerprint(core)
        return {
            "status": "shadow_live_candidate_inferred",
            **core,
            "candidateFingerprint": fingerprint,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": {
                "pointEstimateTarget": "continuous_excess_return_vs_frozen_benchmark",
                "onlyIndividuallyConfirmedHorizonsInferred": True,
                "modelParameters": "frozen_and_integrity_verified",
                "currentEvidence": "same_point_in_time_evidence_gate_contract",
                "missingFeatures": "frozen_training_median_imputation_disclosed_per_horizon",
                "featureContributionExplanation": "standardized_linear_contribution",
                "actionThresholds": "not_calibrated",
                "conviction": "not_calibrated",
                "scenarios": "not_calibrated",
                "confirmationEvidenceCanFitActionThresholds": False,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        self._assert_shadow(artifact, "live_candidate")
        if artifact.get("recommendationCandidateReady") is not False:
            raise ValueError("El candidato shadow no puede habilitar recommendationCandidateReady.")
        if artifact.get("action") is not None:
            raise ValueError("El candidato shadow no puede contener una acción.")
        if artifact.get("score") is not None or artifact.get("conviction") is not None:
            raise ValueError("Score y convicción deben permanecer sin calibrar.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de live candidate no compatible.")
        fingerprint = artifact.get("candidateFingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("El live candidate requiere fingerprint.")
        core_keys = (
            "artifactVersion",
            "symbol",
            "asOf",
            "instrumentId",
            "currentEvidenceStatus",
            "confirmationEvidenceFingerprint",
            "researchGateFingerprint",
            "researchCutoff",
            "inferredHorizonCount",
            "horizons",
            "riskContext",
            "valuationContext",
            "fundamentalContext",
        )
        core = {key: artifact.get(key) for key in core_keys}
        if self._fingerprint(core) != fingerprint:
            raise ValueError("El live candidate fue modificado tras su creación.")
        return artifact

    def _validated_bundle_map(
        self,
        gated_bundles: list[dict[str, Any]],
        confirmation: dict[str, Any],
    ) -> dict[int, dict[str, Any]]:
        if not isinstance(gated_bundles, list):
            raise ValueError("gated_bundles debe ser una lista.")
        result: dict[int, dict[str, Any]] = {}
        expected_gate = confirmation.get("researchGateFingerprint")
        expected_cutoff = confirmation.get("researchCutoff")
        for bundle in gated_bundles:
            validated = self._gated_freeze_service.validate_bundle(bundle)
            self._assert_shadow(validated, "gated_bundle")
            if validated.get("researchGateFingerprint") != expected_gate:
                raise ValueError("El gated bundle no pertenece a la research gate confirmada.")
            if validated.get("researchCutoff") != expected_cutoff:
                raise ValueError("El gated bundle no comparte el researchCutoff confirmado.")
            horizon = int(validated.get("horizonDays", -1))
            if horizon <= 0:
                raise ValueError("El gated bundle contiene un horizonte inválido.")
            if horizon in result:
                raise ValueError("Existe más de un gated bundle para el mismo horizonte.")
            result[horizon] = validated
        return result

    def _gate_payload(self, symbol: str, cutoff: datetime) -> dict[str, Any]:
        gate = self._evidence_gate_service.evaluate(symbol=symbol, as_of=cutoff)
        to_api_dict = getattr(gate, "to_api_dict", None)
        if not callable(to_api_dict):
            raise RuntimeError("El evidence gate no respeta el contrato de ATHENA.")
        payload = to_api_dict()
        if not isinstance(payload, dict):
            raise RuntimeError("El evidence gate devolvió un contrato inválido.")
        if payload.get("productionEligible") is not False:
            raise RuntimeError("El evidence gate intentó declararse productivo.")
        if payload.get("recommendationCandidateReady") is not False:
            raise RuntimeError("El evidence gate intentó habilitar consejo prematuramente.")
        if str(payload.get("symbol") or "").upper() != symbol:
            raise RuntimeError("El evidence gate devolvió otro símbolo.")
        payload_as_of = self._parse_aware(payload.get("asOf"), "evidenceGate.asOf")
        if payload_as_of != cutoff:
            raise RuntimeError("El evidence gate cambió el corte point-in-time.")
        return payload

    def _feature_map(self, gate: dict[str, Any]) -> dict[str, float | None]:
        market = gate.get("market")
        fundamentals = gate.get("fundamentals")
        valuation = gate.get("valuation")
        if not all(isinstance(item, dict) for item in (market, fundamentals, valuation)):
            raise RuntimeError("El evidence gate listo carece de bloques de evidencia completos.")
        ratios = fundamentals.get("ratios")
        if ratios is None:
            ratios = {}
        if not isinstance(ratios, dict):
            raise RuntimeError("Los ratios fundamentales tienen formato inválido.")
        return {
            "technicalScore": self._optional_finite(market.get("technicalScore")),
            "riskScore": self._optional_finite(market.get("riskScore")),
            "return20d": self._optional_finite(market.get("return20d")),
            "return60d": self._optional_finite(market.get("return60d")),
            "annualizedVolatility": self._optional_finite(
                market.get("annualizedVolatility")
            ),
            "maxDrawdown60d": self._optional_finite(market.get("maxDrawdown60d")),
            "fundamentalCoverageRatio": self._optional_finite(
                fundamentals.get("coverageRatio")
            ),
            "revenueGrowth": self._optional_finite(ratios.get("revenueGrowth")),
            "netMargin": self._optional_finite(ratios.get("netMargin")),
            "liabilitiesToAssets": self._optional_finite(
                ratios.get("liabilitiesToAssets")
            ),
            "reportedAnnualPe": self._optional_finite(
                valuation.get("reportedAnnualPe")
            ),
        }

    def _predict(
        self,
        current_features: dict[str, float | None],
        model: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        if model.get("featureSchemaVersion") != self.FEATURE_SCHEMA_VERSION:
            raise ValueError("El modelo congelado usa otro feature schema.")
        features = model.get("features")
        means = model.get("means")
        scales = model.get("scales")
        coefficients = model.get("coefficients")
        medians = model.get("medians")
        if not (
            isinstance(features, list)
            and isinstance(means, list)
            and isinstance(scales, list)
            and isinstance(coefficients, list)
            and isinstance(medians, dict)
            and len(features) == len(means) == len(scales) == len(coefficients)
        ):
            raise ValueError("El modelo congelado tiene dimensiones inválidas para inferencia.")

        intercept = self._required_finite(model.get("intercept"), "intercept")
        contributions: list[dict[str, Any]] = []
        prediction = intercept
        imputed_features: list[str] = []
        for index, feature in enumerate(features):
            name = str(feature)
            raw = current_features.get(name)
            imputed = raw is None
            if imputed:
                raw = self._required_finite(medians.get(name), f"median.{name}")
                imputed_features.append(name)
            mean = self._required_finite(means[index], f"mean.{name}")
            scale = self._required_finite(scales[index], f"scale.{name}")
            if scale <= 0:
                raise ValueError("La escala congelada debe ser positiva.")
            coefficient = self._required_finite(
                coefficients[index], f"coefficient.{name}"
            )
            standardized = (float(raw) - mean) / scale
            contribution = coefficient * standardized
            if not math.isfinite(contribution):
                raise ValueError("Una contribución de inferencia no es finita.")
            prediction += contribution
            contributions.append(
                {
                    "feature": name,
                    "rawValue": float(raw),
                    "imputed": imputed,
                    "standardizedValue": standardized,
                    "coefficient": coefficient,
                    "contribution": contribution,
                }
            )
        if not math.isfinite(prediction):
            raise ValueError("La inferencia produjo un valor no finito.")
        ranked = sorted(
            contributions,
            key=lambda item: abs(float(item["contribution"])),
            reverse=True,
        )
        return prediction, {
            "intercept": intercept,
            "imputedFeatures": imputed_features,
            "imputedFeatureCount": len(imputed_features),
            "contributions": contributions,
            "largestAbsoluteContributors": ranked[:5],
        }

    def _risk_context(self, gate: dict[str, Any]) -> dict[str, Any]:
        market = gate.get("market") if isinstance(gate.get("market"), dict) else {}
        return {
            "riskScore": self._optional_finite(market.get("riskScore")),
            "annualizedVolatility": self._optional_finite(
                market.get("annualizedVolatility")
            ),
            "maxDrawdown60d": self._optional_finite(market.get("maxDrawdown60d")),
            "status": market.get("status"),
        }

    def _valuation_context(self, gate: dict[str, Any]) -> dict[str, Any]:
        valuation = gate.get("valuation") if isinstance(gate.get("valuation"), dict) else {}
        return {
            "reportedAnnualPe": self._optional_finite(
                valuation.get("reportedAnnualPe")
            ),
            "status": valuation.get("status"),
        }

    def _fundamental_context(self, gate: dict[str, Any]) -> dict[str, Any]:
        fundamentals = (
            gate.get("fundamentals") if isinstance(gate.get("fundamentals"), dict) else {}
        )
        return {
            "coverageRatio": self._optional_finite(fundamentals.get("coverageRatio")),
            "status": fundamentals.get("status"),
        }

    def _blocked(
        self,
        *,
        symbol: str,
        cutoff: datetime,
        reason: str,
        confirmation: dict[str, Any],
        blockers: list[Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "shadow_live_candidate_blocked",
            "symbol": symbol,
            "asOf": cutoff.isoformat(),
            "reason": reason,
            "blockers": list(blockers or []),
            "confirmationEvidenceFingerprint": confirmation.get(
                "confirmationEvidenceFingerprint"
            ),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "action": None,
            "score": None,
            "conviction": None,
        }

    def _assert_shadow(self, payload: dict[str, Any], stage: str) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{stage} violó productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{stage} violó advisoryStatus=no_advice.")

    def _optional_finite(self, value: object) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    def _required_finite(self, value: object, field: str) -> float:
        parsed = self._optional_finite(value)
        if parsed is None:
            raise ValueError(f"{field} debe ser finito.")
        return parsed

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

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
