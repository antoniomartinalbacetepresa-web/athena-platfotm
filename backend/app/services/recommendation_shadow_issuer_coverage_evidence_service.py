from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any, Protocol

from app.repositories.issuer_identity_repository import IssuerIdentityRepository


class _IssuerIdentityRepository(Protocol):
    def get_issuer_for_instrument(self, instrument_id: int) -> dict[str, Any] | None: ...


class RecommendationShadowIssuerCoverageEvidenceService:
    """Measure canonical-issuer coverage/concentration in matured shadow OOS evidence.

    This service is deliberately observational.  It binds issuer-resolution evidence
    to an immutable calibration dataset but does not deduplicate economically distinct
    securities, claim statistical independence, choose readiness thresholds, promote a
    model, or create investment advice.  A future production protocol may precommit
    issuer-coverage/concentration requirements against this sealed evidence.
    """

    ARTIFACT_VERSION = "shadow-issuer-coverage-evidence-v1"
    DATASET_VERSION = "shadow-action-calibration-v2"

    def __init__(
        self,
        *,
        identity_repository: _IssuerIdentityRepository | None = None,
    ) -> None:
        self._identity_repository = identity_repository or IssuerIdentityRepository()

    def build(self, dataset: dict[str, Any]) -> dict[str, Any]:
        validated = self._validate_dataset(dataset)
        rows = validated["rows"]

        instrument_evidence: dict[int, dict[str, Any]] = {}
        row_issuer_ids: list[int | None] = []
        horizon_issuer_ids: dict[int, list[int | None]] = {
            horizon: [] for horizon in validated["requestedHorizons"]
        }

        for row in rows:
            instrument_id = self._positive_int(row.get("instrumentId"), "row.instrumentId")
            horizon = self._positive_int(row.get("horizonDays"), "row.horizonDays")
            if horizon not in horizon_issuer_ids:
                raise ValueError("Una fila OOS contiene un horizonte no solicitado.")

            evidence = instrument_evidence.get(instrument_id)
            if evidence is None:
                evidence = self._issuer_evidence(instrument_id)
                instrument_evidence[instrument_id] = evidence
            issuer_id = evidence.get("issuerId")
            row_issuer_ids.append(issuer_id if isinstance(issuer_id, int) else None)
            horizon_issuer_ids[horizon].append(
                issuer_id if isinstance(issuer_id, int) else None
            )

        resolved_row_count = sum(issuer_id is not None for issuer_id in row_issuer_ids)
        unresolved_row_count = len(row_issuer_ids) - resolved_row_count
        distinct_issuer_ids = sorted(
            {issuer_id for issuer_id in row_issuer_ids if issuer_id is not None}
        )
        issuer_counts = Counter(
            issuer_id for issuer_id in row_issuer_ids if issuer_id is not None
        )
        maximum_rows_per_issuer = max(issuer_counts.values(), default=0)

        horizon_coverage: dict[str, dict[str, Any]] = {}
        for horizon, issuer_ids in sorted(horizon_issuer_ids.items()):
            resolved = [issuer_id for issuer_id in issuer_ids if issuer_id is not None]
            counts = Counter(resolved)
            horizon_coverage[str(horizon)] = {
                "horizonDays": horizon,
                "rowCount": len(issuer_ids),
                "resolvedIssuerRowCount": len(resolved),
                "unresolvedIssuerRowCount": len(issuer_ids) - len(resolved),
                "distinctResolvedIssuerCount": len(set(resolved)),
                "maximumRowsPerResolvedIssuer": max(counts.values(), default=0),
            }

        identity_evidence = [
            instrument_evidence[instrument_id]
            for instrument_id in sorted(instrument_evidence)
        ]
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "datasetFingerprint": validated["datasetFingerprint"],
            "datasetAsOf": validated["asOf"],
            "requestedHorizons": list(validated["requestedHorizons"]),
            "rowCount": len(rows),
            "resolvedIssuerRowCount": resolved_row_count,
            "unresolvedIssuerRowCount": unresolved_row_count,
            "distinctResolvedIssuerCount": len(distinct_issuer_ids),
            "maximumRowsPerResolvedIssuer": maximum_rows_per_issuer,
            "instrumentIdentityEvidence": identity_evidence,
            "horizons": horizon_coverage,
        }
        return {
            "status": (
                "shadow_issuer_coverage_evidence_available"
                if rows
                else "shadow_issuer_coverage_evidence_pending"
            ),
            **core,
            "issuerCoverageEvidenceFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "isWeightingReady": False,
            "issuerCoverageGatePassed": False,
            "policy": {
                "canonicalIssuerIdentity": "evidence_backed_instrument_issuer_link_only",
                "unresolvedIssuerIdentity": "preserved_and_counted_not_inferred",
                "securityDeduplication": "not_performed_by_issuer",
                "statisticalIndependence": "not_claimed",
                "issuerCoverageThresholds": "not_selected_here",
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("issuer coverage evidence debe ser un objeto.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de issuer coverage evidence no compatible.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("issuer coverage evidence debe permanecer no_advice.")
        for key in (
            "productionEligible",
            "recommendationCandidateReady",
            "isWeightingReady",
            "issuerCoverageGatePassed",
        ):
            if artifact.get(key) is not False:
                raise ValueError(f"{key} no puede activarse desde issuer coverage evidence.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("issuer coverage evidence carece de policy.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("issuer coverage evidence no puede promover automáticamente.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("issuer coverage evidence no puede habilitar trading automático.")
        if policy.get("statisticalIndependence") != "not_claimed":
            raise ValueError("issuer coverage evidence no puede afirmar independencia estadística.")
        if policy.get("securityDeduplication") != "not_performed_by_issuer":
            raise ValueError("issuer coverage evidence no puede colapsar securities por emisor.")

        fingerprint = self._sha256(
            artifact.get("issuerCoverageEvidenceFingerprint"),
            "issuerCoverageEvidenceFingerprint",
        )
        core_keys = (
            "artifactVersion",
            "datasetFingerprint",
            "datasetAsOf",
            "requestedHorizons",
            "rowCount",
            "resolvedIssuerRowCount",
            "unresolvedIssuerRowCount",
            "distinctResolvedIssuerCount",
            "maximumRowsPerResolvedIssuer",
            "instrumentIdentityEvidence",
            "horizons",
        )
        core = {key: artifact.get(key) for key in core_keys}
        if self._fingerprint(core) != fingerprint:
            raise ValueError("issuer coverage evidence fue modificado tras su creación.")
        return artifact

    def _validate_dataset(self, dataset: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(dataset, dict):
            raise ValueError("dataset debe ser un objeto.")
        if dataset.get("datasetVersion") != self.DATASET_VERSION:
            raise ValueError("Versión de calibration dataset no compatible.")
        if dataset.get("advisoryStatus") != "no_advice":
            raise ValueError("El calibration dataset debe permanecer no_advice.")
        if dataset.get("productionEligible") is not False:
            raise ValueError("El calibration dataset intentó habilitar producción.")
        if dataset.get("recommendationCandidateReady") is not False:
            raise ValueError("El calibration dataset intentó habilitar recomendación.")
        if dataset.get("actionThresholdCalibrationResearchEligible") is not False:
            raise ValueError("El calibration dataset intentó habilitar calibración prematuramente.")
        if any(dataset.get(key) is not None for key in ("actionThresholds", "action", "score", "conviction")):
            raise ValueError("El calibration dataset contiene decisión o score no permitidos.")

        rows = dataset.get("rows")
        horizons = dataset.get("requestedHorizons")
        if not isinstance(rows, list) or not isinstance(horizons, list):
            raise ValueError("El calibration dataset carece de rows/requestedHorizons válidos.")
        requested_horizons = tuple(self._positive_int(value, "requestedHorizons") for value in horizons)
        if len(set(requested_horizons)) != len(requested_horizons):
            raise ValueError("requestedHorizons contiene duplicados.")
        if self._nonnegative_int(dataset.get("rowCount"), "rowCount") != len(rows):
            raise ValueError("rowCount no coincide con las filas OOS.")

        dataset_fingerprint = self._sha256(dataset.get("datasetFingerprint"), "datasetFingerprint")
        core = {
            "datasetVersion": dataset.get("datasetVersion"),
            "asOf": dataset.get("asOf"),
            "symbol": dataset.get("symbol"),
            "requestedHorizons": list(requested_horizons),
            "rowCount": len(rows),
            "rows": rows,
        }
        if self._fingerprint(core) != dataset_fingerprint:
            raise ValueError("El calibration dataset fue modificado tras su creación.")
        return {
            **dataset,
            "requestedHorizons": requested_horizons,
            "datasetFingerprint": dataset_fingerprint,
        }

    def _issuer_evidence(self, instrument_id: int) -> dict[str, Any]:
        raw = self._identity_repository.get_issuer_for_instrument(instrument_id)
        if raw is None:
            return {
                "instrumentId": instrument_id,
                "status": "issuer_identity_unresolved",
                "issuerId": None,
                "evidenceSource": None,
                "resolutionMethod": None,
                "confidence": None,
                "domicileCountry": None,
                "regionKey": None,
            }
        if not isinstance(raw, dict):
            raise ValueError("El repositorio de identidad devolvió un contrato inválido.")
        issuer_id = self._positive_int(raw.get("issuer_id"), "issuer.issuer_id")
        confidence = self._confidence(raw.get("confidence"))
        return {
            "instrumentId": instrument_id,
            "status": "issuer_identity_resolved",
            "issuerId": issuer_id,
            "evidenceSource": self._required_text(raw.get("evidence_source"), "issuer.evidence_source"),
            "resolutionMethod": self._required_text(raw.get("resolution_method"), "issuer.resolution_method"),
            "confidence": confidence,
            "domicileCountry": self._optional_text(raw.get("domicile_country")),
            "regionKey": self._optional_text(raw.get("region_key")),
        }

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero positivo.")
        try:
            result = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero positivo.") from exc
        if result <= 0 or str(result) != str(value).strip():
            raise ValueError(f"{field} debe ser entero positivo.")
        return result

    def _nonnegative_int(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero no negativo.")
        try:
            result = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero no negativo.") from exc
        if result < 0 or str(result) != str(value).strip():
            raise ValueError(f"{field} debe ser entero no negativo.")
        return result

    def _confidence(self, value: object) -> float:
        try:
            result = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("issuer.confidence debe ser finita y estar entre 0 y 1.") from exc
        if not math.isfinite(result) or result < 0 or result > 1:
            raise ValueError("issuer.confidence debe ser finita y estar entre 0 y 1.")
        return result

    def _required_text(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _optional_text(self, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError(f"{field} debe ser sha256 hexadecimal.")
        return normalized

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
