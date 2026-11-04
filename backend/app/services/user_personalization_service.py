from __future__ import annotations

import hashlib
import json
from typing import Any


class UserPersonalizationService:
    """Build a deterministic presentation-only projection from encrypted preferences.

    The projection intentionally excludes identity, timestamps, capital and currency.
    It is safe to consume by UI/explanation layers only and carries explicit
    non-influence guarantees for recommendation, weighting, learning and trading.
    """

    _SCHEMA = "athena.user-personalization.v1"
    _RISK_TOLERANCES = {"conservative", "balanced", "growth", "aggressive"}
    _OBJECTIVES = {
        "capital_preservation",
        "income",
        "balanced_growth",
        "long_term_growth",
    }
    _EXPERIENCE_LEVELS = {"beginner", "intermediate", "advanced", None}
    _LIQUIDITY_NEEDS = {"low", "medium", "high", None}

    def build(self, preferences: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize(preferences)
        fingerprint_payload = {
            "schema": self._SCHEMA,
            "inputs": normalized,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        return {
            "schema": self._SCHEMA,
            "fingerprint": fingerprint,
            "presentation": {
                "detailLevel": self._detail_level(normalized["experienceLevel"]),
                "explanationStyle": self._explanation_style(normalized["experienceLevel"]),
                "riskEmphasis": self._risk_emphasis(normalized),
                "horizonEmphasis": self._horizon_emphasis(
                    normalized["investmentHorizonYears"]
                ),
                "liquidityEmphasis": normalized["liquidityNeed"] or "unspecified",
                "objectiveFocus": normalized["objective"],
            },
            "policy": {
                "presentationOnly": True,
                "recommendationScoringInfluence": False,
                "canonicalWeightingInfluence": False,
                "automaticLearningPromotion": False,
                "automaticTrading": False,
                "sensitiveValuesIncluded": False,
            },
        }

    def _normalize(self, preferences: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(preferences, dict):
            raise ValueError("preferences debe ser un objeto.")

        risk = preferences.get("riskTolerance")
        if risk not in self._RISK_TOLERANCES:
            raise ValueError("riskTolerance no es válido.")

        objective = preferences.get("objective")
        if objective not in self._OBJECTIVES:
            raise ValueError("objective no es válido.")

        experience = preferences.get("experienceLevel")
        if experience not in self._EXPERIENCE_LEVELS:
            raise ValueError("experienceLevel no es válido.")

        liquidity = preferences.get("liquidityNeed")
        if liquidity not in self._LIQUIDITY_NEEDS:
            raise ValueError("liquidityNeed no es válido.")

        horizon = preferences.get("investmentHorizonYears")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 60:
            raise ValueError("investmentHorizonYears no es válido.")

        drawdown = preferences.get("maxDrawdownTolerancePct")
        if drawdown is not None and (
            isinstance(drawdown, bool)
            or not isinstance(drawdown, int)
            or not 5 <= drawdown <= 60
        ):
            raise ValueError("maxDrawdownTolerancePct no es válido.")

        return {
            "riskTolerance": risk,
            "investmentHorizonYears": horizon,
            "objective": objective,
            "experienceLevel": experience,
            "liquidityNeed": liquidity,
            "maxDrawdownTolerancePct": drawdown,
        }

    @staticmethod
    def _detail_level(experience: str | None) -> str:
        return {
            "beginner": "guided",
            "intermediate": "standard",
            "advanced": "technical",
            None: "standard",
        }[experience]

    @staticmethod
    def _explanation_style(experience: str | None) -> str:
        return {
            "beginner": "plain_language",
            "intermediate": "balanced",
            "advanced": "analytical",
            None: "balanced",
        }[experience]

    @staticmethod
    def _horizon_emphasis(horizon_years: int) -> str:
        if horizon_years <= 3:
            return "short_term"
        if horizon_years <= 10:
            return "medium_term"
        return "long_term"

    @staticmethod
    def _risk_emphasis(normalized: dict[str, Any]) -> str:
        risk = normalized["riskTolerance"]
        drawdown = normalized["maxDrawdownTolerancePct"]
        liquidity = normalized["liquidityNeed"]
        if risk == "conservative" or liquidity == "high" or (
            drawdown is not None and drawdown <= 15
        ):
            return "high"
        if risk == "aggressive" and liquidity != "high" and (
            drawdown is None or drawdown >= 35
        ):
            return "low"
        return "standard"
