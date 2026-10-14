from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_performance_attribution_service import (
    AttributionEvidence,
    FactorContributionEvidence,
    RecommendationPerformanceAttributionInput,
    RecommendationPerformanceAttributionService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationPerformanceAttributionRepository:
    """Append-only, tamper-evident storage for PIT arithmetic attribution artifacts."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationPerformanceAttributionService | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._service = service or RecommendationPerformanceAttributionService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_performance_attribution_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attribution_key TEXT NOT NULL UNIQUE,
                    instrument_id TEXT NOT NULL,
                    benchmark_id TEXT NOT NULL,
                    reporting_currency TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_performance_attribution_instrument_period
                ON athena_performance_attribution_artifacts(
                    instrument_id, benchmark_id, reporting_currency, period_start, period_end, as_of, id
                );
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._validate_artifact(artifact)
        key = self._sha256(validated.get("attributionKey"), "attributionKey")
        serialized = self._serialize(validated)
        artifact_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()
        currency = validated["currency"]
        assert isinstance(currency, dict)

        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_performance_attribution_artifacts WHERE attribution_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record["artifact_hash"] != artifact_hash:
                    raise ValueError("attributionKey ya existe con contenido distinto.")
                return self.validate_record(record)

            connection.execute(
                """
                INSERT INTO athena_performance_attribution_artifacts (
                    attribution_key, instrument_id, benchmark_id, reporting_currency,
                    period_start, period_end, as_of, artifact_hash, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    str(validated["instrumentId"]),
                    str(validated["benchmarkId"]),
                    str(currency["reportingCurrency"]),
                    str(validated["periodStart"]),
                    str(validated["periodEnd"]),
                    str(validated["asOf"]),
                    artifact_hash,
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_performance_attribution_artifacts WHERE attribution_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("No se pudo recuperar Performance Attribution persistida.")
        return self.validate_record(self._row(row))

    def get_by_key(self, *, attribution_key: str) -> dict[str, Any]:
        self.initialize()
        key = self._sha256(attribution_key, "attribution_key")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_performance_attribution_artifacts WHERE attribution_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe Performance Attribution persistida con ese attributionKey.")
        return self.validate_record(self._row(row))

    def require_attribution(
        self,
        *,
        attribution_key: str,
        instrument_id: str,
        benchmark_id: str,
        reporting_currency: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
    ) -> dict[str, Any]:
        for value, name in ((period_start, "period_start"), (period_end, "period_end"), (as_of, "as_of")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} debe incluir zona horaria.")
        record = self.get_by_key(attribution_key=attribution_key)
        artifact = record["artifact"]
        currency = artifact["currency"]
        assert isinstance(currency, dict)
        expected = {
            "instrumentId": str(instrument_id).strip(),
            "benchmarkId": str(benchmark_id).strip(),
            "reportingCurrency": str(reporting_currency).strip().upper(),
            "periodStart": period_start.astimezone(timezone.utc).isoformat(),
            "periodEnd": period_end.astimezone(timezone.utc).isoformat(),
            "asOf": as_of.astimezone(timezone.utc).isoformat(),
        }
        actual = {
            "instrumentId": str(artifact["instrumentId"]),
            "benchmarkId": str(artifact["benchmarkId"]),
            "reportingCurrency": str(currency["reportingCurrency"]),
            "periodStart": str(artifact["periodStart"]),
            "periodEnd": str(artifact["periodEnd"]),
            "asOf": str(artifact["asOf"]),
        }
        for field, value in expected.items():
            if actual[field] != value:
                raise ValueError(f"Performance Attribution persistida no coincide en {field}.")
        return record

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro de Performance Attribution carece de artifact válido.")
        validated = self._validate_artifact(artifact)
        serialized = self._serialize(validated)
        expected_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        if str(record.get("artifact_hash")) != expected_hash:
            raise ValueError("Performance Attribution fue modificada tras persistirse.")
        currency = validated["currency"]
        assert isinstance(currency, dict)
        expected_columns = {
            "attribution_key": validated["attributionKey"],
            "instrument_id": validated["instrumentId"],
            "benchmark_id": validated["benchmarkId"],
            "reporting_currency": currency["reportingCurrency"],
            "period_start": validated["periodStart"],
            "period_end": validated["periodEnd"],
            "as_of": validated["asOf"],
        }
        for field, value in expected_columns.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con Performance Attribution.")
        return record

    def _validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("Performance Attribution debe ser un objeto.")
        if artifact.get("module") != "performance_attribution":
            raise ValueError("Performance Attribution perdió module.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Performance Attribution perdió no_advice.")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("Performance Attribution intentó habilitar producción/weighting.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("Performance Attribution perdió policy.")
        if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
            raise ValueError("Performance Attribution intentó automatización.")
        if policy.get("identityBinding") != "numeric_values_plus_pit_provenance_plus_period_and_instrument":
            raise ValueError("Performance Attribution perdió identidad content-bound.")

        currency = artifact.get("currency")
        evidence = artifact.get("evidence")
        factors = artifact.get("factorContributions")
        if not isinstance(currency, dict) or not isinstance(evidence, dict) or not isinstance(factors, dict):
            raise ValueError("Performance Attribution perdió currency/evidence/factors.")

        def aware(value: object, field: str) -> datetime:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} debe ser datetime ISO con zona horaria.")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{field} no es datetime ISO válido.") from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError(f"{field} debe incluir zona horaria.")
            return parsed.astimezone(timezone.utc)

        def meta(name: str) -> dict[str, Any]:
            value = evidence.get(name)
            if not isinstance(value, dict):
                raise ValueError(f"Performance Attribution perdió evidence.{name}.")
            return value

        def attribution_evidence(name: str, numeric_field: str) -> AttributionEvidence:
            item = meta(name)
            return AttributionEvidence(
                value=artifact.get(numeric_field),
                available_at=aware(item.get("availableAt"), f"evidence.{name}.availableAt"),
                source=str(item.get("source") or ""),
                source_ref=str(item.get("sourceRef") or ""),
            )

        factor_meta = evidence.get("factorContributions")
        if not isinstance(factor_meta, dict) or set(factor_meta) != set(factors):
            raise ValueError("Performance Attribution tiene factor values/provenance inconsistentes.")
        factor_inputs: list[FactorContributionEvidence] = []
        for name in sorted(factors):
            item = factor_meta.get(name)
            if not isinstance(item, dict):
                raise ValueError("Performance Attribution perdió provenance factorial.")
            factor_inputs.append(
                FactorContributionEvidence(
                    factor=str(name),
                    contribution=factors[name],
                    available_at=aware(item.get("availableAt"), f"factor[{name}].availableAt"),
                    source=str(item.get("source") or ""),
                    source_ref=str(item.get("sourceRef") or ""),
                )
            )

        rebuilt = self._service.evaluate(
            as_of=aware(artifact.get("asOf"), "asOf"),
            item=RecommendationPerformanceAttributionInput(
                instrument_id=str(artifact.get("instrumentId") or ""),
                symbol=str(artifact.get("symbol") or ""),
                instrument_currency=str(currency.get("instrumentCurrency") or ""),
                reporting_currency=str(currency.get("reportingCurrency") or ""),
                fx_pair=str(currency.get("fxPair") or ""),
                benchmark_id=str(artifact.get("benchmarkId") or ""),
                period_start=aware(artifact.get("periodStart"), "periodStart"),
                period_end=aware(artifact.get("periodEnd"), "periodEnd"),
                total_return=attribution_evidence("totalReturn", "totalReturn"),
                market_contribution=attribution_evidence("marketContribution", "marketContribution"),
                fx_contribution=attribution_evidence("fxContribution", "fxContribution"),
                factor_contributions=tuple(factor_inputs),
            ),
        ).to_api_dict()
        if self._serialize(rebuilt) != self._serialize(artifact):
            raise ValueError("Performance Attribution persistida no coincide con su reconstrucción canónica.")
        return artifact

    @staticmethod
    def _serialize(value: dict[str, Any]) -> str:
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Performance Attribution contiene datos no serializables/no finitos.") from exc

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de Performance Attribution no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "attribution_key": str(row["attribution_key"]),
            "instrument_id": str(row["instrument_id"]),
            "benchmark_id": str(row["benchmark_id"]),
            "reporting_currency": str(row["reporting_currency"]),
            "period_start": str(row["period_start"]),
            "period_end": str(row["period_end"]),
            "as_of": str(row["as_of"]),
            "artifact_hash": str(row["artifact_hash"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _sha256(value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if _SHA256_RE.fullmatch(text) is None:
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text
