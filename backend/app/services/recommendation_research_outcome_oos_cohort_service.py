from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from statistics import median
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SOURCE_MARKERS = ("financialmodelingprep", "financial modeling prep")


@dataclass(frozen=True)
class OutcomeIssuerIdentityEvidence:
    instrument_id: str
    issuer_id: str | None
    available_at: datetime
    source: str
    source_ref: str
    resolution_method: str


class RecommendationResearchOutcomeOosCohortService:
    """Build a PIT, issuer-aware OOS research cohort from persisted outcomes.

    The cohort is descriptive and observational. Every input outcome must already
    be a tamper-verified persisted Research Cycle outcome attribution. Repeated
    observations from one issuer remain visible, but never masquerade as
    independent issuer diversity. Horizons are partitioned by exact elapsed
    seconds and are never pooled implicitly.
    """

    ARTIFACT_VERSION = "research-outcome-oos-cohort-v1"

    def build(
        self,
        *,
        cohort_id: str,
        as_of: datetime,
        outcome_records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        issuer_evidence: list[OutcomeIssuerIdentityEvidence]
        | tuple[OutcomeIssuerIdentityEvidence, ...],
    ) -> dict[str, Any]:
        cohort_id_normalized = self._text(cohort_id, "cohort_id")
        cutoff = self._aware_utc(as_of, "as_of")
        if not isinstance(outcome_records, (list, tuple)) or not outcome_records:
            raise ValueError("outcome_records debe contener al menos un outcome persistido.")
        if len(outcome_records) > 5000:
            raise ValueError("outcome_records supera el límite de investigación de 5000 filas.")

        identities = self._identity_map(issuer_evidence, cutoff)
        normalized_rows: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        seen_outcome_ids: set[tuple[str, str]] = set()

        for record in outcome_records:
            row = self._normalize_outcome(record, cutoff=cutoff)
            outcome_hash = str(row["outcomeHash"])
            if outcome_hash in seen_hashes:
                raise ValueError("outcome_records contiene outcomeHash duplicado.")
            seen_hashes.add(outcome_hash)
            outcome_identity = (str(row["cycleHash"]), str(row["outcomeId"]))
            if outcome_identity in seen_outcome_ids:
                raise ValueError("outcome_records repite outcomeId dentro del mismo cycleHash.")
            seen_outcome_ids.add(outcome_identity)

            instrument_id = str(row["instrumentId"])
            identity = identities.get(instrument_id)
            if identity is None:
                raise ValueError(
                    f"Falta evidencia explícita de identidad de emisor para {instrument_id}."
                )
            row["issuerIdentity"] = identity
            normalized_rows.append(row)

        unused_identity = sorted(set(identities) - {str(row["instrumentId"]) for row in normalized_rows})
        if unused_identity:
            raise ValueError("issuer_evidence contiene instrumentos que no pertenecen a la cohorte.")

        normalized_rows.sort(
            key=lambda item: (
                int(item["horizonSeconds"]),
                str(item["periodEnd"]),
                str(item["instrumentId"]),
                str(item["outcomeHash"]),
            )
        )

        horizons: dict[str, dict[str, Any]] = {}
        by_horizon: dict[int, list[dict[str, Any]]] = {}
        for row in normalized_rows:
            by_horizon.setdefault(int(row["horizonSeconds"]), []).append(row)

        for horizon_seconds, rows in sorted(by_horizon.items()):
            resolved_issuers = [
                str(row["issuerIdentity"]["issuerId"])
                for row in rows
                if row["issuerIdentity"]["issuerId"] is not None
            ]
            issuer_counts = Counter(resolved_issuers)
            horizons[str(horizon_seconds)] = {
                "horizonSeconds": horizon_seconds,
                "horizonDays": (
                    horizon_seconds // 86400 if horizon_seconds % 86400 == 0 else None
                ),
                "observationCount": len(rows),
                "resolvedIssuerObservationCount": len(resolved_issuers),
                "unresolvedIssuerObservationCount": len(rows) - len(resolved_issuers),
                "distinctResolvedIssuerCount": len(issuer_counts),
                "maximumObservationsPerResolvedIssuer": max(issuer_counts.values(), default=0),
                "issuerObservationCounts": dict(sorted(issuer_counts.items())),
                "metrics": self._metrics(rows),
                "outcomeHashes": [str(row["outcomeHash"]) for row in rows],
            }

        all_resolved = [
            str(row["issuerIdentity"]["issuerId"])
            for row in normalized_rows
            if row["issuerIdentity"]["issuerId"] is not None
        ]
        all_issuer_counts = Counter(all_resolved)
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "cohortId": cohort_id_normalized,
            "asOf": cutoff.isoformat(),
            "observationCount": len(normalized_rows),
            "distinctOutcomeCount": len(seen_hashes),
            "resolvedIssuerObservationCount": len(all_resolved),
            "unresolvedIssuerObservationCount": len(normalized_rows) - len(all_resolved),
            "distinctResolvedIssuerCount": len(all_issuer_counts),
            "maximumObservationsPerResolvedIssuer": max(all_issuer_counts.values(), default=0),
            "horizonCount": len(horizons),
            "horizons": horizons,
            "rows": normalized_rows,
        }
        cohort_hash = self._canonical_hash(core)
        return {
            "module": "research_outcome_oos_cohort",
            **core,
            "cohortHash": cohort_hash,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "recommendationCandidateReady": False,
            "learningResearchDatasetReady": True,
            "productionLearningEligible": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "automaticModelMutation": False,
                "learningUse": "research_only_dataset_not_automatic_model_update",
                "lookAhead": "only_persisted_outcomes_and_identity_evidence_available_at_or_before_cohort_as_of",
                "outcomeIntegrity": "every_row_bound_to_tamper_verified_persisted_outcome_hash",
                "issuerDiversity": "resolved_canonical_issuer_counts_reported_separately_from_observation_counts",
                "unresolvedIssuerIdentity": "explicit_unknown_never_inferred_or_counted_as_distinct",
                "statisticalIndependence": "not_claimed",
                "horizonPooling": "forbidden_exact_elapsed_horizons_partitioned",
                "measurement": "descriptive_posterior_attribution_only",
                "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
                "causalClaim": "forbidden",
                "fx": "explicit_not_silently_neutralized",
                "thresholds": "none_selected_here",
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("OOS cohort debe ser un objeto.")
        if artifact.get("module") != "research_outcome_oos_cohort":
            raise ValueError("OOS cohort perdió module.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de OOS cohort no compatible.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("OOS cohort perdió no_advice.")
        for field in (
            "productionEligible",
            "isWeightingReady",
            "recommendationCandidateReady",
            "productionLearningEligible",
        ):
            if artifact.get(field) is not False:
                raise ValueError(f"OOS cohort intentó activar {field}.")
        if artifact.get("learningResearchDatasetReady") is not True:
            raise ValueError("OOS cohort perdió su uso explícito como dataset de investigación.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("OOS cohort perdió policy.")
        required_policy = {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
            "learningUse": "research_only_dataset_not_automatic_model_update",
            "statisticalIndependence": "not_claimed",
            "horizonPooling": "forbidden_exact_elapsed_horizons_partitioned",
            "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
            "causalClaim": "forbidden",
            "fx": "explicit_not_silently_neutralized",
            "thresholds": "none_selected_here",
        }
        for key, expected in required_policy.items():
            if policy.get(key) != expected:
                raise ValueError(f"OOS cohort violó policy.{key}.")

        cohort_hash = self._sha256(artifact.get("cohortHash"), "cohortHash")
        core_keys = (
            "artifactVersion",
            "cohortId",
            "asOf",
            "observationCount",
            "distinctOutcomeCount",
            "resolvedIssuerObservationCount",
            "unresolvedIssuerObservationCount",
            "distinctResolvedIssuerCount",
            "maximumObservationsPerResolvedIssuer",
            "horizonCount",
            "horizons",
            "rows",
        )
        core = {key: artifact.get(key) for key in core_keys}
        if self._canonical_hash(core) != cohort_hash:
            raise ValueError("OOS cohort fue modificado tras crear cohortHash.")
        return artifact

    def _identity_map(
        self,
        evidence_items: list[OutcomeIssuerIdentityEvidence]
        | tuple[OutcomeIssuerIdentityEvidence, ...],
        cutoff: datetime,
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(evidence_items, (list, tuple)) or not evidence_items:
            raise ValueError("issuer_evidence debe cubrir explícitamente todos los instrumentos.")
        result: dict[str, dict[str, Any]] = {}
        seen_provenance: set[tuple[str, str]] = set()
        for item in evidence_items:
            instrument_id = self._text(item.instrument_id, "issuer.instrument_id")
            if instrument_id in result:
                raise ValueError("issuer_evidence contiene instrumentId duplicado.")
            issuer_id = None
            if item.issuer_id is not None:
                issuer_id = self._text(item.issuer_id, "issuer.issuer_id")
            available_at = self._aware_utc(item.available_at, "issuer.available_at")
            if available_at > cutoff:
                raise ValueError("issuer_evidence introduce look-ahead respecto a cohort asOf.")
            source = self._text(item.source, "issuer.source")
            source_ref = self._text(item.source_ref, "issuer.source_ref")
            resolution_method = self._text(item.resolution_method, "issuer.resolution_method")
            self._assert_source_allowed(source)
            self._assert_source_allowed(source_ref)
            provenance = (source.casefold(), source_ref.casefold())
            if provenance in seen_provenance:
                raise ValueError("issuer_evidence contiene provenance duplicada.")
            seen_provenance.add(provenance)
            result[instrument_id] = {
                "status": "resolved" if issuer_id is not None else "unresolved",
                "issuerId": issuer_id,
                "availableAt": available_at.isoformat(),
                "source": source,
                "sourceRef": source_ref,
                "resolutionMethod": resolution_method,
            }
        return result

    def _normalize_outcome(self, record: dict[str, Any], *, cutoff: datetime) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("Cada outcome debe ser un registro persistido verificado.")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("El outcome persistido carece de payload.")
        if payload.get("module") != "research_outcome_attribution":
            raise ValueError("La cohorte solo admite research_outcome_attribution.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El outcome perdió no_advice.")
        if payload.get("productionEligible") is not False or payload.get("isWeightingReady") is not False:
            raise ValueError("El outcome intentó habilitar producción o weighting.")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El outcome perdió policy.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("El outcome intentó trading automático.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("El outcome intentó promoción automática.")
        if policy.get("learning") != "research_only_not_automatic_model_update":
            raise ValueError("El outcome no está autorizado para uso learning research-only.")
        if policy.get("residualInterpretation") != "unexplained_not_automatic_stock_selection_alpha":
            raise ValueError("El outcome intentó convertir residual en alpha.")
        if policy.get("fx") != "explicit_not_silently_neutralized":
            raise ValueError("El outcome perdió seguridad FX.")

        outcome_hash = self._sha256(payload.get("outcomeHash"), "outcome.outcomeHash")
        if self._sha256(record.get("outcome_hash"), "record.outcome_hash") != outcome_hash:
            raise ValueError("El registro persistido no coincide con outcomeHash.")
        cycle_hash = self._sha256(payload.get("cycleHash"), "outcome.cycleHash")
        if self._sha256(record.get("cycle_hash"), "record.cycle_hash") != cycle_hash:
            raise ValueError("El registro persistido no coincide con cycleHash.")

        outcome_as_of = self._aware_iso(payload.get("asOf"), "outcome.asOf")
        if outcome_as_of > cutoff:
            raise ValueError("La cohorte intentó incluir un outcome posterior a cohort asOf.")
        period_start = self._aware_iso(payload.get("periodStart"), "outcome.periodStart")
        period_end = self._aware_iso(payload.get("periodEnd"), "outcome.periodEnd")
        if period_end <= period_start or period_end > outcome_as_of:
            raise ValueError("El outcome contiene un periodo inválido.")
        duration = (period_end - period_start).total_seconds()
        if not math.isfinite(duration) or duration <= 0 or not float(duration).is_integer():
            raise ValueError("El horizonte del outcome debe expresarse en segundos enteros positivos.")
        horizon_seconds = int(duration)

        attribution = payload.get("attribution")
        if not isinstance(attribution, dict) or attribution.get("module") != "performance_attribution":
            raise ValueError("El outcome perdió Performance Attribution canónico.")
        attribution_policy = attribution.get("policy")
        if not isinstance(attribution_policy, dict):
            raise ValueError("Performance Attribution perdió policy.")
        if attribution_policy.get("causalClaim") != "forbidden_arithmetic_attribution_only":
            raise ValueError("Performance Attribution intentó inferencia causal.")
        if attribution_policy.get("residualInterpretation") != "unexplained_not_automatic_stock_selection_alpha":
            raise ValueError("Performance Attribution intentó interpretar residual como alpha.")
        if attribution_policy.get("fx") != "explicit_not_silently_neutralized":
            raise ValueError("Performance Attribution perdió FX explícito.")

        total = self._finite(attribution.get("totalReturn"), "totalReturn")
        explained = self._finite(attribution.get("explainedReturn"), "explainedReturn")
        residual = self._finite(attribution.get("residualReturn"), "residualReturn")
        market = self._finite(attribution.get("marketContribution"), "marketContribution")
        fx = self._finite(attribution.get("fxContribution"), "fxContribution")
        if not math.isclose(total, explained + residual, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("El outcome no reconcilia totalReturn = explainedReturn + residualReturn.")

        factor_values = attribution.get("factorContributions")
        if not isinstance(factor_values, dict):
            raise ValueError("Performance Attribution perdió factorContributions.")
        factor_sum = sum(
            self._finite(value, f"factorContributions.{name}")
            for name, value in factor_values.items()
        )
        if not math.isclose(explained, market + fx + factor_sum, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("El outcome no reconcilia explainedReturn con sus contribuciones.")

        instrument_id = self._text(payload.get("instrumentId"), "outcome.instrumentId")
        symbol = self._text(payload.get("symbol"), "outcome.symbol").upper()
        outcome_id = self._text(payload.get("outcomeId"), "outcome.outcomeId")
        return {
            "outcomeId": outcome_id,
            "outcomeHash": outcome_hash,
            "cycleHash": cycle_hash,
            "instrumentId": instrument_id,
            "symbol": symbol,
            "cycleAsOf": self._aware_iso(payload.get("cycleAsOf"), "outcome.cycleAsOf").isoformat(),
            "asOf": outcome_as_of.isoformat(),
            "periodStart": period_start.isoformat(),
            "periodEnd": period_end.isoformat(),
            "horizonSeconds": horizon_seconds,
            "totalReturn": total,
            "explainedReturn": explained,
            "residualReturn": residual,
            "marketContribution": market,
            "fxContribution": fx,
            "factorContributions": {
                str(name): self._finite(value, f"factorContributions.{name}")
                for name, value in sorted(factor_values.items())
            },
        }

    def _metrics(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        totals = [self._finite(row["totalReturn"], "row.totalReturn") for row in rows]
        explained = [self._finite(row["explainedReturn"], "row.explainedReturn") for row in rows]
        residuals = [self._finite(row["residualReturn"], "row.residualReturn") for row in rows]
        markets = [self._finite(row["marketContribution"], "row.marketContribution") for row in rows]
        fx_values = [self._finite(row["fxContribution"], "row.fxContribution") for row in rows]
        count = len(rows)
        if count <= 0:
            raise ValueError("No se pueden calcular métricas sin outcomes.")
        metrics = {
            "meanTotalReturn": sum(totals) / count,
            "medianTotalReturn": median(totals),
            "meanExplainedReturn": sum(explained) / count,
            "meanResidualReturn": sum(residuals) / count,
            "meanAbsoluteResidualReturn": sum(abs(value) for value in residuals) / count,
            "meanMarketContribution": sum(markets) / count,
            "meanFxContribution": sum(fx_values) / count,
            "positiveTotalReturnCount": sum(value > 0 for value in totals),
            "zeroTotalReturnCount": sum(value == 0 for value in totals),
            "negativeTotalReturnCount": sum(value < 0 for value in totals),
        }
        for key, value in metrics.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"La métrica {key} no es finita.")
        return metrics

    def _assert_source_allowed(self, value: str) -> None:
        normalized = value.casefold().replace("_", " ").replace("-", " ")
        compact = normalized.replace(" ", "")
        if compact == "fmp" or any(marker in normalized for marker in _FORBIDDEN_SOURCE_MARKERS):
            raise ValueError("FMP/Financial Modeling Prep está prohibido en OOS cohort.")

    def _canonical_hash(self, payload: object) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

    def _text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    def _aware_iso(self, value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} debe ser numérico finito.")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result
