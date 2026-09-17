from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.recommendation_investors_synthesis import _provenance as _investors_provenance
from app.repositories.recommendation_athena_synthesis_repository import (
    RecommendationAthenaSynthesisRepository,
)
from app.repositories.recommendation_investors_synthesis_repository import (
    RecommendationInvestorsSynthesisRepository,
)
from app.repositories.recommendation_news_synthesis_repository import (
    RecommendationNewsSynthesisRepository,
)
from app.repositories.recommendation_professional_research_cycle_repository import (
    RecommendationProfessionalResearchCycleRepository,
)
from app.services.recommendation_athena_synthesis_service import (
    AthenaSynthesisModelInput,
    RecommendationAthenaSynthesisService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-athena-synthesis"],
)

cycle_repository = RecommendationProfessionalResearchCycleRepository()
news_repository = RecommendationNewsSynthesisRepository()
investors_repository = RecommendationInvestorsSynthesisRepository()
athena_repository = RecommendationAthenaSynthesisRepository()
athena_service = RecommendationAthenaSynthesisService()


class AthenaSynthesisRequest(BaseModel):
    modelProvider: str = Field(min_length=1)
    modelName: str = Field(min_length=1)
    modelVersion: str = Field(min_length=1)
    inputFingerprint: str = Field(min_length=64, max_length=64)
    generatedAt: datetime
    summary: str = Field(min_length=1, max_length=6000)
    rationale: str = Field(min_length=1, max_length=12000)
    uncertainties: list[str] = Field(min_length=1, max_length=50)
    evidenceIds: list[str] = Field(min_length=1, max_length=1000)


def _aware_iso(value: object, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} es obligatorio.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} debe incluir zona horaria.")
    return parsed.astimezone(timezone.utc)


def _aware_datetime(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cycle_evidence_contract(cycle_record: dict[str, Any]) -> dict[str, Any]:
    package = cycle_record.get("package")
    if not isinstance(package, dict):
        raise ValueError("El Research Cycle persistido carece de package.")
    cycle = package.get("cycle")
    radar = package.get("radar")
    if not isinstance(cycle, dict) or not isinstance(radar, dict):
        raise ValueError("El Research Cycle persistido carece de cycle/radar válidos.")
    input_as_of = _aware_iso(cycle.get("asOf"), "cycle.asOf")
    if input_as_of != _aware_iso(radar.get("asOf"), "radar.asOf"):
        raise ValueError("Research Cycle y Radar deben compartir asOf.")
    candidates = radar.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("El Radar persistido no contiene candidatos.")
    evidence_ids: set[str] = set()
    categories: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("Cada candidato Radar debe ser un objeto.")
        evidence = candidate.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Cada candidato Radar debe conservar evidencia.")
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError("Cada evidencia Radar debe ser un objeto.")
            evidence_id = str(item.get("evidenceId") or "").strip()
            category = str(item.get("category") or "").strip().lower()
            if not evidence_id or not category:
                raise ValueError("Toda evidencia Radar debe conservar evidenceId y category.")
            if evidence_id in evidence_ids:
                raise ValueError("evidenceId no puede repetirse en el Radar.")
            evidence_ids.add(evidence_id)
            categories.add(category)
    return {
        "inputAsOf": input_as_of,
        "evidenceIds": tuple(sorted(evidence_ids)),
        "coveredCategories": tuple(sorted(categories)),
        "hasNews": "news" in categories,
        "hasInvestors": "investors" in categories,
    }


def _dependencies(
    cycle_hash: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    cycle_record = cycle_repository.get_by_hash(cycle_hash=cycle_hash)
    contract = _cycle_evidence_contract(cycle_record)
    news_record: dict[str, Any] | None = None
    investors_record: dict[str, Any] | None = None
    if contract["hasNews"]:
        news_record = news_repository.get_by_cycle_hash(cycle_hash=cycle_hash)
        if news_record["radar_hash"] != cycle_record["radar_hash"]:
            raise ValueError("La síntesis News no coincide con el radarHash del Research Cycle.")
    if contract["hasInvestors"]:
        investors_record = investors_repository.get_by_cycle_hash(cycle_hash=cycle_hash)
        if investors_record["radar_hash"] != cycle_record["radar_hash"]:
            raise ValueError("Investors synthesis no coincide con el radarHash del Research Cycle.")
    return cycle_record, news_record, investors_record, contract


def _base_input_fingerprint(
    cycle_record: dict[str, Any],
    news_record: dict[str, Any] | None,
    contract: dict[str, Any],
) -> str:
    return athena_service.input_fingerprint(
        cycle_hash=cycle_record["cycle_hash"],
        radar_hash=cycle_record["radar_hash"],
        news_synthesis_hash=(news_record["synthesis_hash"] if news_record is not None else None),
        input_as_of=contract["inputAsOf"],
        evidence_ids=contract["evidenceIds"],
        covered_categories=contract["coveredCategories"],
    )


def _news_provenance_binding(news_record: dict[str, Any] | None) -> dict[str, Any] | None:
    if news_record is None:
        return None
    package = news_record.get("package")
    synthesis = package.get("synthesis") if isinstance(package, dict) else None
    assessments = synthesis.get("assessments") if isinstance(synthesis, dict) else None
    if not isinstance(assessments, list) or not assessments:
        raise ValueError("La síntesis News canónica carece de assessments trazables.")
    bindings: list[dict[str, str]] = []
    seen: set[str] = set()
    for assessment in assessments:
        if not isinstance(assessment, dict):
            raise ValueError("Cada assessment News canónico debe ser un objeto.")
        evidence_id = str(assessment.get("evidenceId") or "").strip()
        fingerprint = str(assessment.get("assessmentFingerprint") or "").strip().lower()
        source_ref = str(assessment.get("sourceRef") or "").strip()
        if (
            not evidence_id
            or len(fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in fingerprint)
            or not source_ref.startswith("https://")
        ):
            raise ValueError("La provenance News canónica está incompleta.")
        if evidence_id in seen:
            raise ValueError("La provenance News canónica contiene evidenceId duplicado.")
        seen.add(evidence_id)
        bindings.append(
            {
                "evidenceId": evidence_id,
                "assessmentFingerprint": fingerprint,
                "sourceRef": source_ref,
            }
        )
    bindings.sort(key=lambda item: item["evidenceId"])
    return {
        "artifactHash": news_record["synthesis_hash"],
        "artifactType": "canonical_news_synthesis",
        "assessmentBindings": bindings,
        "userFacingTraceability": True,
        "recommendationInfluence": False,
        "automaticTrading": False,
    }


def _investors_provenance_binding(investors_record: dict[str, Any] | None) -> dict[str, Any] | None:
    if investors_record is None:
        return None
    return _investors_provenance(investors_record)


def _input_contract(
    cycle_record: dict[str, Any],
    news_record: dict[str, Any] | None,
    investors_record: dict[str, Any] | None,
    contract: dict[str, Any],
) -> dict[str, Any]:
    news_hash = news_record["synthesis_hash"] if news_record is not None else None
    investors_hash = investors_record["synthesis_hash"] if investors_record is not None else None
    base_fingerprint = _base_input_fingerprint(cycle_record, news_record, contract)
    news_binding = _news_provenance_binding(news_record)
    investors_binding = _investors_provenance_binding(investors_record)
    fingerprint = _canonical_hash(
        {
            "baseAthenaInputFingerprint": base_fingerprint,
            "investorsSynthesisHash": investors_hash,
            "newsProvenance": news_binding,
            "investorsProvenance": investors_binding,
        }
    )
    return {
        "cycleHash": cycle_record["cycle_hash"],
        "radarHash": cycle_record["radar_hash"],
        **({"newsSynthesisHash": news_hash} if news_hash is not None else {}),
        **({"investorsSynthesisHash": investors_hash} if investors_hash is not None else {}),
        **({"newsProvenance": news_binding} if news_binding is not None else {}),
        **({"investorsProvenance": investors_binding} if investors_binding is not None else {}),
        "inputAsOf": contract["inputAsOf"].isoformat(),
        "evidenceIds": list(contract["evidenceIds"]),
        "coveredCategories": list(contract["coveredCategories"]),
        "inputFingerprint": fingerprint,
        "requiredCoverage": "all_cycle_radar_evidence",
        "canonicalCategorySynthesesRequired": [
            category
            for category, present in (
                ("news", contract["hasNews"]),
                ("investors", contract["hasInvestors"]),
            )
            if present
        ],
        "advisoryStatus": "no_advice",
        "recommendationInfluence": False,
        "automaticTrading": False,
    }


def _response_provenance(input_contract: dict[str, Any], input_fingerprint: str) -> dict[str, Any]:
    return {
        **({"news": input_contract["newsProvenance"]} if "newsProvenance" in input_contract else {}),
        **({"investors": input_contract["investorsProvenance"]} if "investorsProvenance" in input_contract else {}),
        "inputFingerprint": input_fingerprint,
    }


@router.get("/research-cycle/{cycle_hash}/athena-synthesis/input-contract")
def get_athena_synthesis_input_contract(cycle_hash: str) -> dict[str, Any]:
    try:
        cycle_record, news_record, investors_record, contract = _dependencies(cycle_hash)
        return {"data": _input_contract(cycle_record, news_record, investors_record, contract)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo construir el contrato de ATHENA synthesis.") from exc


@router.post("/research-cycle/{cycle_hash}/athena-synthesis")
def post_athena_synthesis(cycle_hash: str, request: AthenaSynthesisRequest) -> dict[str, Any]:
    try:
        cycle_record, news_record, investors_record, contract = _dependencies(cycle_hash)
        input_contract = _input_contract(cycle_record, news_record, investors_record, contract)
        supplied = request.inputFingerprint.strip().lower()
        if supplied != input_contract["inputFingerprint"]:
            raise ValueError(
                "input_fingerprint/inputFingerprint no coincide con News/Investors/ciclo canónicos."
            )
        base_fingerprint = _base_input_fingerprint(cycle_record, news_record, contract)
        result = athena_service.build(
            cycle_record=cycle_record,
            news_synthesis_record=news_record,
            model_output=AthenaSynthesisModelInput(
                model_provider=request.modelProvider,
                model_name=request.modelName,
                model_version=request.modelVersion,
                input_fingerprint=base_fingerprint,
                generated_at=_aware_datetime(request.generatedAt, "generatedAt"),
                summary=request.summary,
                rationale=request.rationale,
                uncertainties=tuple(request.uncertainties),
                evidence_ids=tuple(request.evidenceIds),
            ),
        )
        payload = result.to_api_dict()
        payload["inputFingerprint"] = supplied
        investors_hash = investors_record["synthesis_hash"] if investors_record is not None else None
        if investors_hash is not None:
            payload["investorsSynthesisHash"] = investors_hash
        payload["outputFingerprint"] = _canonical_hash(
            {
                "inputFingerprint": supplied,
                "modelProvider": payload["modelProvider"],
                "modelName": payload["modelName"],
                "modelVersion": payload["modelVersion"],
                "generatedAt": payload["generatedAt"],
                "summary": payload["summary"],
                "rationale": payload["rationale"],
                "uncertainties": payload["uncertainties"],
                "evidenceIds": payload["evidenceIds"],
                "investorsSynthesisHash": investors_hash,
            }
        )
        record = athena_repository.append(
            cycle_hash=cycle_record["cycle_hash"],
            radar_hash=cycle_record["radar_hash"],
            news_synthesis_hash=(news_record["synthesis_hash"] if news_record is not None else None),
            synthesis_payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo validar y persistir ATHENA synthesis.") from exc
    return {
        "data": {
            "artifactBindingVerified": True,
            "synthesis": payload,
            "provenance": _response_provenance(input_contract, supplied),
            "persistence": {
                "appendOnly": True,
                "packageIntegrityVerified": True,
                "synthesisHash": record["synthesis_hash"],
                "cycleHash": record["cycle_hash"],
                "radarHash": record["radar_hash"],
                "newsSynthesisHash": record["news_synthesis_hash"],
                "investorsSynthesisHash": investors_hash,
                "createdAt": record["created_at"],
                "storageClaim": "single_canonical_athena_synthesis_per_cycle_append_only_not_worm_storage",
            },
        }
    }


@router.get("/research-cycle/{cycle_hash}/athena-synthesis")
def get_athena_synthesis(cycle_hash: str) -> dict[str, Any]:
    try:
        cycle_record, news_record, investors_record, contract = _dependencies(cycle_hash)
        record = athena_repository.get_by_cycle_hash(cycle_hash=cycle_hash)
        if record["radar_hash"] != cycle_record["radar_hash"]:
            raise ValueError("ATHENA synthesis no coincide con el Radar actual del ciclo.")
        expected_news_hash = news_record["synthesis_hash"] if news_record is not None else None
        if record["news_synthesis_hash"] != expected_news_hash:
            raise ValueError("ATHENA synthesis no coincide con la síntesis News canónica.")
        expected_investors_hash = investors_record["synthesis_hash"] if investors_record is not None else None
        stored_synthesis = record["package"]["synthesis"]
        if stored_synthesis.get("investorsSynthesisHash") != expected_investors_hash:
            if not (expected_investors_hash is None and "investorsSynthesisHash" not in stored_synthesis):
                raise ValueError("ATHENA synthesis no coincide con Investors synthesis canónica.")
        input_contract = _input_contract(cycle_record, news_record, investors_record, contract)
        if stored_synthesis.get("inputFingerprint") != input_contract["inputFingerprint"]:
            raise ValueError("ATHENA synthesis persistida no coincide con el input canónico actual.")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar ATHENA synthesis persistida.") from exc
    return {
        "data": {
            "artifactBindingVerified": True,
            "synthesis": record["package"]["synthesis"],
            "provenance": _response_provenance(input_contract, input_contract["inputFingerprint"]),
            "persistence": {
                "appendOnly": True,
                "packageIntegrityVerified": True,
                "synthesisHash": record["synthesis_hash"],
                "cycleHash": record["cycle_hash"],
                "radarHash": record["radar_hash"],
                "newsSynthesisHash": record["news_synthesis_hash"],
                "investorsSynthesisHash": expected_investors_hash,
                "createdAt": record["created_at"],
                "storageClaim": "single_canonical_athena_synthesis_per_cycle_append_only_not_worm_storage",
            },
        }
    }
