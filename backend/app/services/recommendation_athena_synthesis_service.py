from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_PROVIDER_TOKENS = ("financialmodelingprep", "fmp")


@dataclass(frozen=True)
class AthenaSynthesisModelInput:
    model_provider: str
    model_name: str
    model_version: str
    input_fingerprint: str
    generated_at: datetime
    summary: str
    rationale: str
    uncertainties: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AthenaSynthesisResult:
    cycle_hash: str
    radar_hash: str
    news_synthesis_hash: str | None
    input_as_of: str
    generated_at: str
    model_provider: str
    model_name: str
    model_version: str
    input_fingerprint: str
    output_fingerprint: str
    summary: str
    rationale: str
    uncertainties: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    covered_categories: tuple[str, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "validated_external_athena_synthesis",
            "mode": "research_explanation_only",
            "cycleHash": self.cycle_hash,
            "radarHash": self.radar_hash,
            **({"newsSynthesisHash": self.news_synthesis_hash} if self.news_synthesis_hash is not None else {}),
            "inputAsOf": self.input_as_of,
            "generatedAt": self.generated_at,
            "modelProvider": self.model_provider,
            "modelName": self.model_name,
            "modelVersion": self.model_version,
            "inputFingerprint": self.input_fingerprint,
            "outputFingerprint": self.output_fingerprint,
            "summary": self.summary,
            "rationale": self.rationale,
            "uncertainties": list(self.uncertainties),
            "evidenceIds": list(self.evidence_ids),
            "coveredCategories": list(self.covered_categories),
            "coverageInterpretation": "all_cycle_radar_evidence_must_be_referenced_no_silent_omission",
            "modelExecutionVerified": False,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "recommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
            "automaticProductionPromotion": False,
        }


class RecommendationAthenaSynthesisService:
    """Validate an external explanatory synthesis against immutable research artifacts."""

    def build(self, *, cycle_record: dict[str, Any], news_synthesis_record: dict[str, Any] | None, model_output: AthenaSynthesisModelInput) -> AthenaSynthesisResult:
        if not isinstance(cycle_record, dict):
            raise ValueError("cycle_record debe ser un registro validado.")
        if not isinstance(model_output, AthenaSynthesisModelInput):
            raise ValueError("model_output debe ser AthenaSynthesisModelInput.")
        package = self._dict(cycle_record.get("package"), "cycle_record.package")
        cycle = self._dict(package.get("cycle"), "cycle_record.package.cycle")
        radar = self._dict(package.get("radar"), "cycle_record.package.radar")
        integrity = self._dict(cycle.get("integrity"), "cycle.integrity")
        cycle_hash = self._sha256(cycle_record.get("cycle_hash"), "cycle_record.cycle_hash")
        radar_hash = self._sha256(cycle_record.get("radar_hash"), "cycle_record.radar_hash")
        if self._sha256(integrity.get("cycleHash"), "cycle.integrity.cycleHash") != cycle_hash:
            raise ValueError("cycleHash del package no coincide con el registro persistido.")
        if self._sha256(integrity.get("radarHash"), "cycle.integrity.radarHash") != radar_hash:
            raise ValueError("radarHash del package no coincide con el registro persistido.")
        input_as_of = self._aware_iso(cycle.get("asOf"), "cycle.asOf")
        radar_as_of = self._aware_iso(radar.get("asOf"), "radar.asOf")
        if input_as_of != radar_as_of:
            raise ValueError("Research Cycle y Radar deben compartir el mismo inputAsOf.")
        evidence_ids: set[str] = set()
        categories: set[str] = set()
        has_news = False
        candidates = radar.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("El Radar persistido debe contener candidatos.")
        for candidate_index, candidate_raw in enumerate(candidates):
            candidate = self._dict(candidate_raw, f"radar.candidates[{candidate_index}]")
            evidence = candidate.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError("Cada candidato Radar debe conservar evidencia explícita.")
            for item_index, item_raw in enumerate(evidence):
                item = self._dict(item_raw, f"radar.candidates[{candidate_index}].evidence[{item_index}]")
                evidence_id = self._text(item.get("evidenceId"), "evidence.evidenceId")
                if evidence_id in evidence_ids:
                    raise ValueError("evidenceId no puede repetirse en el Radar persistido.")
                evidence_ids.add(evidence_id)
                category = self._text(item.get("category"), "evidence.category").lower()
                categories.add(category)
                has_news = has_news or category == "news"
        news_hash: str | None = None
        if has_news:
            if not isinstance(news_synthesis_record, dict):
                raise ValueError("Un ciclo con evidencia News requiere su síntesis News canónica antes de ATHENA synthesis.")
            news_hash = self._sha256(news_synthesis_record.get("synthesis_hash"), "news_synthesis_record.synthesis_hash")
            if self._sha256(news_synthesis_record.get("cycle_hash"), "news_synthesis_record.cycle_hash") != cycle_hash:
                raise ValueError("La síntesis News no pertenece al Research Cycle exacto.")
            if self._sha256(news_synthesis_record.get("radar_hash"), "news_synthesis_record.radar_hash") != radar_hash:
                raise ValueError("La síntesis News no pertenece al Radar exacto del ciclo.")
        elif news_synthesis_record is not None:
            raise ValueError("No debe adjuntarse síntesis News a un ciclo sin evidencia News.")
        expected_input_fingerprint = self.input_fingerprint(cycle_hash=cycle_hash, radar_hash=radar_hash, news_synthesis_hash=news_hash, input_as_of=input_as_of, evidence_ids=tuple(sorted(evidence_ids)), covered_categories=tuple(sorted(categories)))
        supplied = self._sha256(model_output.input_fingerprint, "model_output.input_fingerprint")
        if supplied != expected_input_fingerprint:
            raise ValueError("model_output.input_fingerprint no coincide con los artefactos canónicos.")
        provider = self._text(model_output.model_provider, "model_output.model_provider")
        self._assert_provider_allowed(provider)
        model_name = self._text(model_output.model_name, "model_output.model_name")
        model_version = self._text(model_output.model_version, "model_output.model_version")
        generated_at = self._aware_datetime(model_output.generated_at, "model_output.generated_at")
        if generated_at < input_as_of:
            raise ValueError("model_output.generated_at no puede preceder el inputAsOf del ciclo congelado.")
        summary = self._bounded_text(model_output.summary, "model_output.summary", 6000)
        rationale = self._bounded_text(model_output.rationale, "model_output.rationale", 12000)
        uncertainties = self._unique_text_tuple(model_output.uncertainties, field="model_output.uncertainties", max_items=50, max_length=2000)
        if not uncertainties:
            raise ValueError("model_output.uncertainties debe declarar al menos una incertidumbre.")
        referenced = self._unique_text_tuple(model_output.evidence_ids, field="model_output.evidence_ids", max_items=1000, max_length=256)
        if set(referenced) != evidence_ids:
            raise ValueError("ATHENA synthesis debe referenciar exactamente toda la evidencia Radar del ciclo.")
        referenced = tuple(sorted(referenced))
        covered_categories = tuple(sorted(categories))
        output_fingerprint = self._canonical_hash({"inputFingerprint": expected_input_fingerprint, "modelProvider": provider, "modelName": model_name, "modelVersion": model_version, "generatedAt": generated_at.isoformat(), "summary": summary, "rationale": rationale, "uncertainties": list(uncertainties), "evidenceIds": list(referenced)})
        return AthenaSynthesisResult(cycle_hash=cycle_hash, radar_hash=radar_hash, news_synthesis_hash=news_hash, input_as_of=input_as_of.isoformat(), generated_at=generated_at.isoformat(), model_provider=provider, model_name=model_name, model_version=model_version, input_fingerprint=expected_input_fingerprint, output_fingerprint=output_fingerprint, summary=summary, rationale=rationale, uncertainties=uncertainties, evidence_ids=referenced, covered_categories=covered_categories)

    def input_fingerprint(self, *, cycle_hash: str, radar_hash: str, news_synthesis_hash: str | None, input_as_of: datetime, evidence_ids: tuple[str, ...], covered_categories: tuple[str, ...]) -> str:
        return self._canonical_hash({"cycleHash": self._sha256(cycle_hash, "cycle_hash"), "radarHash": self._sha256(radar_hash, "radar_hash"), "newsSynthesisHash": (self._sha256(news_synthesis_hash, "news_synthesis_hash") if news_synthesis_hash is not None else None), "inputAsOf": self._aware_datetime(input_as_of, "input_as_of").isoformat(), "evidenceIds": sorted(self._text(item, "evidence_id") for item in evidence_ids), "coveredCategories": sorted(self._text(item, "covered_category").lower() for item in covered_categories)})

    def _dict(self, value: object, field: str) -> dict[str, Any]:
        if not isinstance(value, dict): raise ValueError(f"{field} debe ser un objeto.")
        return value
    def _text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text: raise ValueError(f"{field} es obligatorio.")
        return text
    def _bounded_text(self, value: object, field: str, max_length: int) -> str:
        text = self._text(value, field)
        if len(text) > max_length: raise ValueError(f"{field} no puede superar {max_length} caracteres.")
        return text
    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text): raise ValueError(f"{field} debe ser un SHA-256 hexadecimal válido.")
        return text
    def _aware_datetime(self, value: object, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None: raise ValueError(f"{field} debe ser datetime con timezone.")
        return value.astimezone(timezone.utc)
    def _aware_iso(self, value: object, field: str) -> datetime:
        text = self._text(value, field)
        try: parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc: raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_datetime(parsed, field)
    def _unique_text_tuple(self, value: object, *, field: str, max_items: int, max_length: int) -> tuple[str, ...]:
        if not isinstance(value, tuple): raise ValueError(f"{field} debe ser una tupla.")
        if len(value) > max_items: raise ValueError(f"{field} no puede superar {max_items} elementos.")
        items = tuple(self._bounded_text(item, field, max_length) for item in value)
        if len(set(items)) != len(items): raise ValueError(f"{field} no puede contener duplicados.")
        return items
    def _canonical_hash(self, payload: object) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
    def _assert_provider_allowed(self, provider: str) -> None:
        compact = "".join(ch for ch in provider.casefold() if ch.isalnum())
        if any(token in compact for token in _FORBIDDEN_PROVIDER_TOKENS): raise ValueError("FMP/Financial Modeling Prep está prohibido en ATHENA synthesis.")