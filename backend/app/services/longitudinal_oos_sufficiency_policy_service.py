from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any


class LongitudinalOosSufficiencyPolicyService:
    """Evaluate OOS evidence against an externally selected, human-approved policy.

    This service deliberately does not choose thresholds or approve policies.  It
    only validates an explicit precommitment and binds any approval to the exact
    canonical policy fingerprint before evaluating observed evidence.
    """

    MODULE = "longitudinal_oos_sufficiency_policy"

    def evaluate(
        self,
        *,
        as_of: datetime,
        measurement: dict[str, Any],
        policy_record: dict[str, Any] | None,
        approval_record: dict[str, Any] | None,
    ) -> dict[str, Any]:
        cutoff = self._aware(as_of, "as_of")
        if policy_record is None:
            return self._pending("policy_not_precommitted")

        artifact = policy_record.get("artifact") if isinstance(policy_record, dict) else None
        if not isinstance(artifact, dict) or artifact.get("module") != self.MODULE:
            raise ValueError("La política longitudinal persistida no es canónica.")

        policy_id = self._text(artifact.get("policyId"), "policyId")
        version = self._positive_int(artifact.get("version"), "version")
        criteria = artifact.get("criteria")
        if not isinstance(criteria, dict):
            raise ValueError("La política longitudinal carece de criteria.")
        normalized = {
            "module": self.MODULE,
            "policyId": policy_id,
            "version": version,
            "criteria": {
                "minimumEvaluationSpanDays": self._nonnegative_number(
                    criteria.get("minimumEvaluationSpanDays"), "minimumEvaluationSpanDays"
                ),
                "minimumDistinctEvaluationPeriods": self._positive_int(
                    criteria.get("minimumDistinctEvaluationPeriods"),
                    "minimumDistinctEvaluationPeriods",
                ),
                "minimumEligibleOutcomes": self._positive_int(
                    criteria.get("minimumEligibleOutcomes"), "minimumEligibleOutcomes"
                ),
                "minimumDistinctResolvedIssuers": self._positive_int(
                    criteria.get("minimumDistinctResolvedIssuers"),
                    "minimumDistinctResolvedIssuers",
                ),
                "requiredHorizonSeconds": sorted(
                    {self._positive_int(value, "requiredHorizonSeconds") for value in self._list(criteria.get("requiredHorizonSeconds"))}
                ),
                "dependencyHandling": self._text(
                    criteria.get("dependencyHandling"), "dependencyHandling"
                ),
            },
        }
        fingerprint = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        stored_fingerprint = self._sha(artifact.get("policyFingerprint"), "policyFingerprint")
        if stored_fingerprint != fingerprint:
            raise ValueError("policyFingerprint no coincide con el contenido precomprometido.")

        if approval_record is None:
            return self._result(normalized, fingerprint, "policy_approval_required", False, False, [])
        approval = approval_record.get("artifact") if isinstance(approval_record, dict) else None
        if not isinstance(approval, dict):
            raise ValueError("La aprobación longitudinal persistida no es válida.")
        if approval.get("status") != "approved":
            return self._result(normalized, fingerprint, "policy_approval_required", False, False, [])
        if self._sha(approval.get("policyFingerprint"), "approval.policyFingerprint") != fingerprint:
            return self._result(normalized, fingerprint, "policy_approval_stale", False, False, [])
        self._text(approval.get("approvedBy"), "approval.approvedBy")
        self._text(approval.get("evidenceRef"), "approval.evidenceRef")
        approved_at = self._iso(approval.get("approvedAt"), "approval.approvedAt")
        if approved_at > cutoff:
            raise ValueError("La aprobación longitudinal es posterior al as_of.")

        c = normalized["criteria"]
        checks = [
            float(measurement.get("evaluationSpanDays", -1)) >= c["minimumEvaluationSpanDays"],
            int(measurement.get("distinctEvaluationPeriodCount", -1)) >= c["minimumDistinctEvaluationPeriods"],
            int(measurement.get("eligibleOutcomeCount", -1)) >= c["minimumEligibleOutcomes"],
            int(measurement.get("distinctResolvedIssuerCount", -1)) >= c["minimumDistinctResolvedIssuers"],
        ]
        horizons = measurement.get("horizons")
        if not isinstance(horizons, dict):
            checks.append(False)
        else:
            available = {int(key) for key in horizons.keys()}
            checks.append(set(c["requiredHorizonSeconds"]).issubset(available))
        satisfied = all(checks)
        return self._result(
            normalized,
            fingerprint,
            "precommitted_policy_satisfied" if satisfied else "precommitted_policy_not_satisfied",
            True,
            satisfied,
            checks,
        )

    def _result(self, policy: dict[str, Any], fingerprint: str, status: str, approved: bool, verified: bool, checks: list[bool]) -> dict[str, Any]:
        return {
            "status": status,
            "policyId": policy["policyId"],
            "policyVersion": policy["version"],
            "policyFingerprint": fingerprint,
            "policyApproved": approved,
            "acceptanceEvidenceVerified": verified,
            "productionSufficiencyClaimed": False,
            "criteriaCheckCount": len(checks),
            "satisfiedCriteriaCount": sum(1 for value in checks if value),
            "automaticApproval": False,
            "automaticProductionPromotion": False,
        }

    def _pending(self, status: str) -> dict[str, Any]:
        return {
            "status": status,
            "policyId": None,
            "policyVersion": None,
            "policyFingerprint": None,
            "policyApproved": False,
            "acceptanceEvidenceVerified": False,
            "productionSufficiencyClaimed": False,
            "criteriaCheckCount": 0,
            "satisfiedCriteriaCount": 0,
            "automaticApproval": False,
            "automaticProductionPromotion": False,
        }

    @staticmethod
    def fingerprint(*, policy_id: str, version: int, criteria: dict[str, Any]) -> str:
        service = LongitudinalOosSufficiencyPolicyService()
        normalized = {
            "module": service.MODULE,
            "policyId": service._text(policy_id, "policyId"),
            "version": service._positive_int(version, "version"),
            "criteria": {
                "minimumEvaluationSpanDays": service._nonnegative_number(criteria.get("minimumEvaluationSpanDays"), "minimumEvaluationSpanDays"),
                "minimumDistinctEvaluationPeriods": service._positive_int(criteria.get("minimumDistinctEvaluationPeriods"), "minimumDistinctEvaluationPeriods"),
                "minimumEligibleOutcomes": service._positive_int(criteria.get("minimumEligibleOutcomes"), "minimumEligibleOutcomes"),
                "minimumDistinctResolvedIssuers": service._positive_int(criteria.get("minimumDistinctResolvedIssuers"), "minimumDistinctResolvedIssuers"),
                "requiredHorizonSeconds": sorted({service._positive_int(v, "requiredHorizonSeconds") for v in service._list(criteria.get("requiredHorizonSeconds"))}),
                "dependencyHandling": service._text(criteria.get("dependencyHandling"), "dependencyHandling"),
            },
        }
        return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @staticmethod
    def _aware(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"{field} debe incluir timezone.")
        return value.astimezone(timezone.utc)

    def _iso(self, value: Any, field: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError(f"{field} debe ser ISO-8601.")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return self._aware(parsed, field)

    @staticmethod
    def _text(value: Any, field: str) -> str:
        text = str(value).strip() if value is not None else ""
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    @staticmethod
    def _positive_int(value: Any, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero positivo.")
        number = int(value)
        if number <= 0 or number != float(value):
            raise ValueError(f"{field} debe ser entero positivo.")
        return number

    @staticmethod
    def _nonnegative_number(value: Any, field: str) -> float:
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{field} debe ser finito y no negativo.")
        return number

    @staticmethod
    def _list(value: Any) -> list[Any]:
        if not isinstance(value, list) or not value:
            raise ValueError("requiredHorizonSeconds debe ser una lista no vacía.")
        return value

    @staticmethod
    def _sha(value: Any, field: str) -> str:
        text = LongitudinalOosSufficiencyPolicyService._text(value, field).lower()
        if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return text
