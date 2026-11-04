from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class RecommendationPortfolioPolicyStateService:
    """Validate user-owned portfolio state without inventing exposure thresholds.

    `flat` may be derived only from an explicit absence of a position. A positive
    position must explicitly declare either `reduced_long` or `full_long`; ATHENA
    never infers that distinction from shares, market value, or a hidden cutoff.
    """

    ARTIFACT_VERSION = "athena-portfolio-policy-state-v1"
    STATES = ("flat", "reduced_long", "full_long")

    def build(
        self,
        *,
        instrument_id: int,
        canonical_instrument_id: str,
        policy_state: str,
        position_present: bool,
        shares: float,
        identity_risk_ready: bool,
        identity_exchange_verified: bool,
    ) -> dict[str, Any]:
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("instrument_id debe ser entero positivo.")
        canonical = str(canonical_instrument_id or "").strip()
        if not canonical:
            raise ValueError("canonical_instrument_id es obligatorio.")
        state = str(policy_state or "").strip().lower()
        if state not in self.STATES:
            raise ValueError("policy_state no pertenece al contrato de cartera.")
        if not isinstance(position_present, bool):
            raise ValueError("position_present debe ser booleano.")
        share_count = self._finite(shares, "shares")
        if share_count < 0:
            raise ValueError("shares no puede ser negativo.")
        if identity_risk_ready is not True or identity_exchange_verified is not True:
            raise ValueError("La identidad canónica de la posición no está verificada para riesgo.")

        if state == "flat":
            if position_present or share_count != 0.0:
                raise ValueError("flat exige ausencia explícita de posición y shares=0.")
        else:
            if not position_present or share_count <= 0.0:
                raise ValueError(f"{state} exige una posición real con shares>0.")

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "instrumentId": instrument_id,
            "canonicalInstrumentId": canonical,
            "policyState": state,
            "positionPresent": position_present,
            "shares": share_count,
            "identityRiskReady": True,
            "identityExchangeVerified": True,
        }
        return {
            **core,
            "portfolioPolicyStateFingerprint": self._fingerprint(core),
            "advisoryStatus": "portfolio_context_only",
            "productionEligible": False,
            "automaticTrading": False,
            "policy": {
                "reducedVsFullExposureInferredFromShares": False,
                "nonFlatStateMustBeExplicit": True,
                "reduceOrSellRequiresPosition": True,
                "automaticTrading": False,
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict) or artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de contexto de cartera no compatible.")
        rebuilt = self.build(
            instrument_id=artifact.get("instrumentId"),
            canonical_instrument_id=artifact.get("canonicalInstrumentId"),
            policy_state=artifact.get("policyState"),
            position_present=artifact.get("positionPresent"),
            shares=artifact.get("shares"),
            identity_risk_ready=artifact.get("identityRiskReady"),
            identity_exchange_verified=artifact.get("identityExchangeVerified"),
        )
        supplied = str(artifact.get("portfolioPolicyStateFingerprint") or "").strip().lower()
        if supplied != rebuilt["portfolioPolicyStateFingerprint"]:
            raise ValueError("El contexto de cartera fue modificado tras su creación.")
        if artifact.get("productionEligible") is not False or artifact.get("automaticTrading") is not False:
            raise ValueError("El contexto de cartera no puede habilitar producción ni trading.")
        return artifact

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

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
