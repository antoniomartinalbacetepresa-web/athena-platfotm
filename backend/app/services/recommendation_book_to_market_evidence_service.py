from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Mapping

from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.sec_fundamental_evidence_resolver import SecFundamentalEvidenceResolver
from app.services.sec_instrument_cik_resolver import SecInstrumentCikResolver


class RecommendationBookToMarketEvidenceService:
    """Build issuer-bound PIT book-to-market evidence without pretending it is a factor score."""

    _VALUE_TOLERANCE = 1e-12

    def __init__(
        self,
        *,
        cik_resolver: SecInstrumentCikResolver | None = None,
        fundamental_resolver: SecFundamentalEvidenceResolver | None = None,
        market_repository: MarketObservationRepository | None = None,
    ) -> None:
        self._cik_resolver = cik_resolver or SecInstrumentCikResolver()
        self._fundamental_resolver = fundamental_resolver or SecFundamentalEvidenceResolver()
        self._market_repository = market_repository or MarketObservationRepository()

    def evaluate(self, *, instrument_id: int, as_of: datetime) -> dict[str, object]:
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        as_of_utc = self._aware_utc(as_of, "as_of")

        identity = self._cik_resolver.resolve(instrument_id=instrument_id)
        identity_payload = identity.to_api_dict()
        equity = self._fundamental_resolver.resolve(
            cik=identity.cik,
            canonical_concept="stockholders_equity",
            as_of=as_of_utc,
        )
        if equity.get("status") != "resolved":
            return self._missing(
                instrument_id=instrument_id,
                as_of=as_of_utc,
                identity=identity_payload,
                reason="stockholders_equity_missing",
            )
        selected_fact = equity.get("selectedFact")
        if not isinstance(selected_fact, Mapping):
            raise ValueError("Equity PIT resuelto carece de selectedFact.")
        book_equity = self._finite(selected_fact.get("value"), "stockholders_equity.value")
        if book_equity <= 0.0:
            return self._missing(
                instrument_id=instrument_id,
                as_of=as_of_utc,
                identity=identity_payload,
                reason="stockholders_equity_non_positive",
                fundamental_evidence=equity,
            )

        market_cap_evidence = self._resolve_market_cap(instrument_id=instrument_id, as_of=as_of_utc)
        if market_cap_evidence is None:
            return self._missing(
                instrument_id=instrument_id,
                as_of=as_of_utc,
                identity=identity_payload,
                reason="market_cap_usd_missing",
                fundamental_evidence=equity,
            )
        market_cap = self._finite(market_cap_evidence["marketCapUsd"], "marketCapUsd")
        if market_cap <= 0.0:
            raise ValueError("marketCapUsd PIT debe ser positivo.")

        ratio = book_equity / market_cap
        if not math.isfinite(ratio) or ratio <= 0.0:
            raise ValueError("bookToMarket PIT debe ser positivo y finito.")

        identity_key = str(identity_payload.get("identityKey") or "")
        fundamental_key = str(equity.get("evidenceKey") or "")
        if not self._sha256(identity_key) or not self._sha256(fundamental_key):
            raise ValueError("Identidad/fundamental evidenceKey inválida.")
        canonical = {
            "instrumentId": instrument_id,
            "asOf": as_of_utc.isoformat(),
            "identityKey": identity_key,
            "cik": identity.cik,
            "fundamentalEvidenceKey": fundamental_key,
            "bookEquityUsd": format(book_equity, ".17g"),
            "marketCapUsd": format(market_cap, ".17g"),
            "marketObservedAt": market_cap_evidence["observedAt"],
            "marketRetrievedAt": market_cap_evidence["retrievedAt"],
            "marketSources": market_cap_evidence["sources"],
            "bookToMarket": format(ratio, ".17g"),
        }
        evidence_key = hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "module": "book_to_market_pit_evidence",
            "status": "resolved",
            "evidenceKey": evidence_key,
            "instrumentId": instrument_id,
            "asOf": as_of_utc.isoformat(),
            "bookEquityUsd": book_equity,
            "marketCapUsd": market_cap,
            "bookToMarket": ratio,
            "identityEvidence": identity_payload,
            "fundamentalEvidence": equity,
            "marketCapEvidence": market_cap_evidence,
            "factorReady": False,
            "factorExposure": None,
            "policy": self._policy(),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        }

    def validate_artifact(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        data = dict(artifact)
        if data.get("module") != "book_to_market_pit_evidence" or data.get("status") != "resolved":
            raise ValueError("Artifact book-to-market resuelto inválido.")
        if data.get("advisoryStatus") != "no_advice":
            raise ValueError("Book-to-market violó no_advice.")
        if data.get("productionEligible") is not False or data.get("isWeightingReady") is not False:
            raise ValueError("Book-to-market intentó habilitar producción/weighting.")
        if data.get("factorReady") is not False or data.get("factorExposure") is not None:
            raise ValueError("Book-to-market bruto no puede presentarse como exposición factorial.")
        evidence_key = str(data.get("evidenceKey") or "")
        if not self._sha256(evidence_key):
            raise ValueError("evidenceKey book-to-market inválida.")
        instrument_id = data.get("instrumentId")
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("instrumentId book-to-market inválido.")
        as_of = self._parse_datetime(data.get("asOf"), "asOf")
        book_equity = self._finite(data.get("bookEquityUsd"), "bookEquityUsd")
        market_cap = self._finite(data.get("marketCapUsd"), "marketCapUsd")
        ratio = self._finite(data.get("bookToMarket"), "bookToMarket")
        if book_equity <= 0.0 or market_cap <= 0.0 or ratio <= 0.0:
            raise ValueError("Book-to-market exige equity, market cap y ratio positivos.")
        if not math.isclose(ratio, book_equity / market_cap, rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("bookToMarket no reconcilia con equity/market cap.")
        identity = data.get("identityEvidence")
        fundamental = data.get("fundamentalEvidence")
        market = data.get("marketCapEvidence")
        if not isinstance(identity, Mapping) or not isinstance(fundamental, Mapping) or not isinstance(market, Mapping):
            raise ValueError("Book-to-market perdió evidencia/provenance.")
        if identity.get("instrumentId") != instrument_id:
            raise ValueError("Book-to-market perdió binding de instrumento.")
        identity_key = str(identity.get("identityKey") or "")
        fundamental_key = str(fundamental.get("evidenceKey") or "")
        if not self._sha256(identity_key) or not self._sha256(fundamental_key):
            raise ValueError("Book-to-market perdió hashes upstream.")
        selected = fundamental.get("selectedFact")
        if not isinstance(selected, Mapping) or selected.get("value") != book_equity:
            raise ValueError("Book-to-market perdió binding con equity fundamental.")
        market_observed = self._parse_datetime(market.get("observedAt"), "marketCapEvidence.observedAt")
        market_retrieved = self._parse_datetime(market.get("retrievedAt"), "marketCapEvidence.retrievedAt")
        if market_observed > market_retrieved or market_retrieved > as_of:
            raise ValueError("Book-to-market violó PIT de market cap.")
        if self._finite(market.get("marketCapUsd"), "marketCapEvidence.marketCapUsd") != market_cap:
            raise ValueError("Book-to-market perdió binding con market cap.")
        sources = market.get("sources")
        if not isinstance(sources, list) or not sources or any(not isinstance(item, Mapping) for item in sources):
            raise ValueError("Book-to-market perdió provenance de market cap.")
        canonical = {
            "instrumentId": instrument_id,
            "asOf": as_of.isoformat(),
            "identityKey": identity_key,
            "cik": identity.get("cik"),
            "fundamentalEvidenceKey": fundamental_key,
            "bookEquityUsd": format(book_equity, ".17g"),
            "marketCapUsd": format(market_cap, ".17g"),
            "marketObservedAt": market_observed.isoformat(),
            "marketRetrievedAt": market_retrieved.isoformat(),
            "marketSources": sources,
            "bookToMarket": format(ratio, ".17g"),
        }
        expected = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        ).hexdigest()
        if expected != evidence_key:
            raise ValueError("Book-to-market artifact fue manipulado.")
        policy = data.get("policy")
        if not isinstance(policy, Mapping) or policy.get("automaticTrading") is not False:
            raise ValueError("Book-to-market perdió política de seguridad.")
        return data

    def _resolve_market_cap(self, *, instrument_id: int, as_of: datetime) -> dict[str, object] | None:
        rows = self._market_repository.list_for_instrument(
            instrument_id,
            knowledge_cutoff=as_of,
        )
        eligible: list[dict[str, Any]] = []
        for row in rows:
            raw = row.get("market_cap_usd")
            if raw is None:
                continue
            value = self._finite(raw, "market_cap_usd")
            if value <= 0.0:
                raise ValueError("market_cap_usd PIT debe ser positivo.")
            observed = self._parse_datetime(row.get("observed_at"), "observed_at")
            retrieved = self._parse_datetime(row.get("retrieved_at"), "retrieved_at")
            if observed > retrieved or retrieved > as_of:
                raise ValueError("Una observación market cap violó PIT.")
            eligible.append({**row, "_value": value, "_observed": observed, "_retrieved": retrieved})
        if not eligible:
            return None
        latest_observed = max(item["_observed"] for item in eligible)
        same_observed = [item for item in eligible if item["_observed"] == latest_observed]
        latest_retrieved = max(item["_retrieved"] for item in same_observed)
        latest = [item for item in same_observed if item["_retrieved"] == latest_retrieved]
        first = float(latest[0]["_value"])
        if any(
            not math.isclose(float(item["_value"]), first, rel_tol=self._VALUE_TOLERANCE, abs_tol=1e-6)
            for item in latest[1:]
        ):
            raise ValueError("Market cap PIT es ambiguo entre fuentes en el mismo punto temporal.")
        sources = sorted(
            [
                {
                    "provider": str(item.get("source_provider") or "").strip(),
                    "sourceTimestamp": item.get("source_timestamp"),
                }
                for item in latest
            ],
            key=lambda item: (str(item["provider"]), str(item["sourceTimestamp"])),
        )
        if any(not item["provider"] for item in sources):
            raise ValueError("Market cap PIT carece de source_provider.")
        return {
            "marketCapUsd": first,
            "observedAt": latest_observed.isoformat(),
            "retrievedAt": latest_retrieved.isoformat(),
            "sources": sources,
        }

    @staticmethod
    def _policy() -> dict[str, object]:
        return {
            "metric": "book_to_market_stockholders_equity_usd_over_market_cap_usd",
            "issuerBinding": "canonical_instrument_to_unique_sec_cik_required",
            "fundamentalSelection": "canonical_pit_equity_resolver",
            "marketSelection": "latest_observed_then_latest_retrieved_all_sources_conflicts_fail_closed",
            "negativeOrZeroEquity": "missing_not_scored",
            "normalization": "not_yet_cross_sectionally_ranked",
            "factorReady": False,
            "thresholds": "not_calibrated",
            "automaticTrading": False,
            "automaticProductionPromotion": False,
        }

    def _missing(
        self,
        *,
        instrument_id: int,
        as_of: datetime,
        identity: Mapping[str, Any],
        reason: str,
        fundamental_evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        return {
            "module": "book_to_market_pit_evidence",
            "status": "missing",
            "evidenceKey": None,
            "instrumentId": instrument_id,
            "asOf": as_of.isoformat(),
            "missingReason": reason,
            "identityEvidence": dict(identity),
            "fundamentalEvidence": dict(fundamental_evidence) if fundamental_evidence is not None else None,
            "marketCapEvidence": None,
            "bookToMarket": None,
            "factorReady": False,
            "factorExposure": None,
            "policy": self._policy(),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        }

    @staticmethod
    def _finite(raw: object, field: str) -> float:
        if isinstance(raw, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(value):
            raise ValueError(f"{field} debe ser finito.")
        return value

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _parse_datetime(cls, raw: object, field: str) -> datetime:
        if isinstance(raw, datetime):
            return cls._aware_utc(raw, field)
        text = str(raw or "").strip().replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} debe ser timestamp ISO válido.") from exc
        return cls._aware_utc(value, field)
