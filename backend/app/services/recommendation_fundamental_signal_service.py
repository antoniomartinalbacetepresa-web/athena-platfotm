from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class FundamentalFact:
    key: str
    metric: str
    value: float
    unit: str | None
    effective_at: str | None
    available_at: str
    quality_score: float | None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "effectiveAt": self.effective_at,
            "availableAt": self.available_at,
            "qualityScore": self.quality_score,
        }


@dataclass(frozen=True)
class RecommendationFundamentalSignal:
    status: str
    symbol: str
    instrument_id: int | None
    entity_id: str | None
    as_of: str
    facts: tuple[FundamentalFact, ...]
    revenue_growth: float | None
    net_margin: float | None
    liabilities_to_assets: float | None
    coverage_ratio: float
    mean_quality_score: float | None
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "instrumentId": self.instrument_id,
            "entityId": self.entity_id,
            "asOf": self.as_of,
            "facts": [fact.to_api_dict() for fact in self.facts],
            "revenueGrowth": self.revenue_growth,
            "netMargin": self.net_margin,
            "liabilitiesToAssets": self.liabilities_to_assets,
            "coverageRatio": self.coverage_ratio,
            "meanQualityScore": self.mean_quality_score,
            "productionEligible": self.production_eligible,
            "reason": self.reason,
            "policy": {
                "temporal": "explicit_available_at_not_after_as_of",
                "identity": "unique_active_symbol_and_unique_sec_cik",
                "comparability": "ratios_require_matching_effective_periods",
                "scoring": "facts_and_ratios_only_until_out_of_sample_calibrated",
            },
        }


class RecommendationFundamentalSignalService:
    """Build point-in-time SEC fundamental evidence without issuing advice."""

    _SOURCE_PROVIDER = "sec_edgar"
    _SOURCE_ID = "sec_edgar_xbrl"
    _FACT_PRIORITIES: dict[str, tuple[str, ...]] = {
        "revenue": (
            "fundamental.us-gaap.revenuefromcontractwithcustomerexcludingassessedtax",
            "fundamental.us-gaap.revenues",
            "fundamental.us-gaap.salesrevenuenet",
        ),
        "net_income": (
            "fundamental.us-gaap.netincomeloss",
            "fundamental.us-gaap.profitloss",
        ),
        "assets": (
            "fundamental.us-gaap.assets",
        ),
        "liabilities": (
            "fundamental.us-gaap.liabilities",
        ),
    }

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def evaluate(
        self,
        *,
        symbol: str,
        as_of: datetime,
    ) -> RecommendationFundamentalSignal:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        as_of_utc = self._aware_utc(as_of)
        self._database.initialize()

        instrument_ids = self._active_instrument_ids(normalized_symbol)
        if not instrument_ids:
            return self._empty(
                status="instrument_not_found",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                reason="No existe un instrumento activo con ese símbolo.",
            )
        if len(instrument_ids) != 1:
            return self._empty(
                status="instrument_ambiguous",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                reason="El símbolo corresponde a más de un instrumento activo.",
            )

        instrument_id = instrument_ids[0]
        ciks = self._sec_ciks(instrument_id)
        if not ciks:
            return self._empty(
                status="issuer_identity_missing",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                instrument_id=instrument_id,
                reason=(
                    "El instrumento aún no tiene una identidad de emisor enlazada "
                    "a un CIK SEC con evidencia suficiente."
                ),
            )
        if len(ciks) != 1:
            return self._empty(
                status="issuer_identity_ambiguous",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                instrument_id=instrument_id,
                reason="Existe más de un CIK SEC candidato para el emisor.",
            )

        cik = ciks[0]
        entity_id = f"sec-cik:{cik.zfill(10)}"
        rows_by_metric = self._point_in_time_rows(
            entity_id=entity_id,
            as_of=as_of_utc,
        )

        selected: list[FundamentalFact] = []
        selected_histories: dict[str, list[dict[str, Any]]] = {}
        for key, priorities in self._FACT_PRIORITIES.items():
            history = self._first_available_history(rows_by_metric, priorities)
            if not history:
                continue
            selected_histories[key] = history
            latest = history[0]
            value = self._numeric_value(latest.get("value_json"))
            if value is None:
                continue
            selected.append(
                FundamentalFact(
                    key=key,
                    metric=str(latest["metric"]),
                    value=value,
                    unit=self._optional_text(latest.get("unit")),
                    effective_at=self._optional_text(latest.get("effective_at")),
                    available_at=str(latest["available_at"]),
                    quality_score=self._optional_float(latest.get("quality_score")),
                )
            )

        facts = {fact.key: fact for fact in selected}
        revenue_growth = self._growth(selected_histories.get("revenue", []))
        net_margin = self._same_period_ratio(
            numerator=facts.get("net_income"),
            denominator=facts.get("revenue"),
        )
        liabilities_to_assets = self._same_period_ratio(
            numerator=facts.get("liabilities"),
            denominator=facts.get("assets"),
        )
        coverage = len(selected) / len(self._FACT_PRIORITIES)
        quality_scores = [
            fact.quality_score
            for fact in selected
            if fact.quality_score is not None
        ]
        mean_quality = mean(quality_scores) if quality_scores else None

        status = "diagnostic_ready" if coverage >= 0.75 else "partial_fundamentals"
        reason = (
            "Fundamentales SEC point-in-time disponibles con cobertura suficiente; "
            "los ratios siguen siendo evidencia diagnóstica, no una recomendación."
            if status == "diagnostic_ready"
            else (
                "La cobertura fundamental point-in-time es parcial; ATHENA no debe "
                "inferir métricas ausentes ni elevar esta evidencia a recomendación."
            )
        )

        return RecommendationFundamentalSignal(
            status=status,
            symbol=normalized_symbol,
            instrument_id=instrument_id,
            entity_id=entity_id,
            as_of=as_of_utc.isoformat(),
            facts=tuple(selected),
            revenue_growth=revenue_growth,
            net_margin=net_margin,
            liabilities_to_assets=liabilities_to_assets,
            coverage_ratio=coverage,
            mean_quality_score=mean_quality,
            production_eligible=False,
            reason=reason,
        )

    def _active_instrument_ids(self, symbol: str) -> tuple[int, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM instruments
                WHERE is_active = 1
                  AND UPPER(symbol) = ?
                ORDER BY id
                """,
                (symbol,),
            ).fetchall()
        return tuple(int(row["id"]) for row in rows)

    def _sec_ciks(self, instrument_id: int) -> tuple[str, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT iei.external_id
                FROM instrument_issuer_links iil
                JOIN issuer_external_ids iei
                  ON iei.issuer_id = iil.issuer_id
                WHERE iil.instrument_id = ?
                  AND iei.source_provider = ?
                ORDER BY iei.evidence_confidence DESC, iei.external_id ASC
                """,
                (instrument_id, self._SOURCE_PROVIDER),
            ).fetchall()
        result: list[str] = []
        for row in rows:
            digits = "".join(
                character
                for character in str(row["external_id"])
                if character.isdigit()
            )
            if digits and digits not in result:
                result.append(digits)
        return tuple(result)

    def _point_in_time_rows(
        self,
        *,
        entity_id: str,
        as_of: datetime,
    ) -> dict[str, list[dict[str, Any]]]:
        cutoff = as_of.astimezone(timezone.utc).isoformat()
        metrics = tuple(
            metric
            for priorities in self._FACT_PRIORITIES.values()
            for metric in priorities
        )
        placeholders = ",".join("?" for _ in metrics)
        with self._database.connect() as connection:
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(normalized_data_observations)"
                ).fetchall()
            }
            if "available_at" not in columns:
                return {}
            rows = connection.execute(
                f"""
                SELECT
                    id,
                    metric,
                    value_json,
                    unit,
                    quality_score,
                    effective_at,
                    available_at
                FROM normalized_data_observations
                WHERE entity_id = ?
                  AND source_id = ?
                  AND data_kind = 'fact'
                  AND available_at IS NOT NULL
                  AND available_at <= ?
                  AND metric IN ({placeholders})
                ORDER BY
                    metric ASC,
                    COALESCE(effective_at, '') DESC,
                    available_at DESC,
                    id DESC
                """,
                (entity_id, self._SOURCE_ID, cutoff, *metrics),
            ).fetchall()

        grouped: dict[str, list[dict[str, Any]]] = {}
        seen_periods: dict[str, set[str]] = {}
        for raw in rows:
            row = dict(raw)
            metric = str(row["metric"])
            period_key = str(row.get("effective_at") or row.get("available_at") or "")
            metric_seen = seen_periods.setdefault(metric, set())
            if period_key in metric_seen:
                continue
            metric_seen.add(period_key)
            grouped.setdefault(metric, []).append(row)
        return grouped

    def _first_available_history(
        self,
        rows_by_metric: dict[str, list[dict[str, Any]]],
        priorities: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        for metric in priorities:
            history = rows_by_metric.get(metric, [])
            if history:
                return history
        return []

    def _growth(self, history: list[dict[str, Any]]) -> float | None:
        if len(history) < 2:
            return None
        latest = self._numeric_value(history[0].get("value_json"))
        previous = self._numeric_value(history[1].get("value_json"))
        if latest is None or previous is None or previous == 0:
            return None
        return (latest / previous) - 1.0

    def _same_period_ratio(
        self,
        *,
        numerator: FundamentalFact | None,
        denominator: FundamentalFact | None,
    ) -> float | None:
        if numerator is None or denominator is None:
            return None
        if not numerator.effective_at or numerator.effective_at != denominator.effective_at:
            return None
        if numerator.unit != denominator.unit or denominator.value == 0:
            return None
        return numerator.value / denominator.value

    def _numeric_value(self, value_json: object) -> float | None:
        try:
            value = json.loads(str(value_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _optional_text(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _optional_float(self, value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _empty(
        self,
        *,
        status: str,
        symbol: str,
        as_of: datetime,
        reason: str,
        instrument_id: int | None = None,
    ) -> RecommendationFundamentalSignal:
        return RecommendationFundamentalSignal(
            status=status,
            symbol=symbol,
            instrument_id=instrument_id,
            entity_id=None,
            as_of=as_of.isoformat(),
            facts=(),
            revenue_growth=None,
            net_margin=None,
            liabilities_to_assets=None,
            coverage_ratio=0.0,
            mean_quality_score=None,
            production_eligible=False,
            reason=reason,
        )

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
