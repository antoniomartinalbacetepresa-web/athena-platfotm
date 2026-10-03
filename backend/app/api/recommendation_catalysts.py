from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.recommendation_catalyst_service import (
    RecommendationCatalystInput,
    RecommendationCatalystService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

catalyst_service = RecommendationCatalystService()


class CatalystRequest(BaseModel):
    catalystId: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    expectedStart: datetime
    expectedEnd: datetime
    definedAt: datetime
    definitionSource: str = Field(min_length=1)
    definitionSourceRef: str = Field(min_length=1)
    occurredAt: datetime | None = None
    occurrenceAvailableAt: datetime | None = None
    occurrenceSource: str | None = None
    occurrenceSourceRef: str | None = None


class CatalystResearchRequest(BaseModel):
    symbol: str = Field(min_length=1)
    asOf: datetime
    catalysts: list[CatalystRequest] = Field(min_length=1, max_length=50)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _optional_aware_utc(value: datetime | None, field: str) -> datetime | None:
    if value is None:
        return None
    return _aware_utc(value, field)


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Catalysts violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Catalysts intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Catalysts intentó habilitar ponderación.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Catalysts devolvió una política inválida.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Catalysts intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Catalysts intentó promover producción automáticamente.")
    if policy.get("missedCatalystAutomaticallyInvalidatesThesis") is not False:
        raise HTTPException(
            status_code=500,
            detail="Catalysts intentó convertir un catalizador perdido en invalidación automática.",
        )

    catalysts = payload.get("catalysts")
    if not isinstance(catalysts, list) or not catalysts:
        raise HTTPException(status_code=500, detail="Catalysts devolvió evidencia inválida.")

    required_definition = (
        "catalystId",
        "name",
        "kind",
        "state",
        "timeliness",
        "expectedStart",
        "expectedEnd",
        "definedAt",
        "definitionSource",
        "definitionSourceRef",
    )
    seen_ids: set[str] = set()
    allowed_states = {"pending", "occurred", "missed"}
    allowed_timeliness = {
        "early",
        "on_time",
        "late",
        "not_yet_determined",
        "not_observed_by_expected_end",
    }
    for catalyst in catalysts:
        if not isinstance(catalyst, dict) or any(
            catalyst.get(field) in (None, "") for field in required_definition
        ):
            raise HTTPException(status_code=500, detail="Catalysts devolvió evidencia PIT incompleta.")
        catalyst_id = str(catalyst.get("catalystId") or "").strip().lower()
        if catalyst_id in seen_ids:
            raise HTTPException(status_code=500, detail="Catalysts devolvió identidades duplicadas.")
        seen_ids.add(catalyst_id)
        if catalyst.get("state") not in allowed_states or catalyst.get("timeliness") not in allowed_timeliness:
            raise HTTPException(status_code=500, detail="Catalysts devolvió un estado inválido.")

        occurrence_fields = (
            catalyst.get("occurredAt"),
            catalyst.get("occurrenceAvailableAt"),
            catalyst.get("occurrenceSource"),
            catalyst.get("occurrenceSourceRef"),
        )
        if catalyst.get("state") == "occurred":
            if any(value in (None, "") for value in occurrence_fields):
                raise HTTPException(
                    status_code=500,
                    detail="Catalysts devolvió ocurrencia sin provenance PIT completo.",
                )
        elif any(value not in (None, "") for value in occurrence_fields):
            raise HTTPException(
                status_code=500,
                detail="Catalysts devolvió evidencia de ocurrencia incompatible con su estado.",
            )

    counts = (
        payload.get("occurredCount"),
        payload.get("pendingCount"),
        payload.get("missedCount"),
        payload.get("delayedCount"),
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
        raise HTTPException(status_code=500, detail="Catalysts devolvió conteos inválidos.")
    if sum(counts[:3]) != len(catalysts):
        raise HTTPException(status_code=500, detail="Catalysts devolvió conteos inconsistentes.")
    if counts[3] > counts[0]:
        raise HTTPException(status_code=500, detail="Catalysts devolvió retrasos inconsistentes.")


@router.post("/catalysts")
def post_catalysts(request: CatalystResearchRequest) -> dict[str, object]:
    """Classify explicit provenance-bound PIT catalysts without investment advice."""

    as_of = _aware_utc(request.asOf, "asOf")
    inputs: list[RecommendationCatalystInput] = []
    for item in request.catalysts:
        inputs.append(
            RecommendationCatalystInput(
                catalyst_id=item.catalystId,
                name=item.name,
                kind=item.kind,
                expected_start=_aware_utc(item.expectedStart, "catalysts.expectedStart"),
                expected_end=_aware_utc(item.expectedEnd, "catalysts.expectedEnd"),
                defined_at=_aware_utc(item.definedAt, "catalysts.definedAt"),
                definition_source=item.definitionSource,
                definition_source_ref=item.definitionSourceRef,
                occurred_at=_optional_aware_utc(item.occurredAt, "catalysts.occurredAt"),
                occurrence_available_at=_optional_aware_utc(
                    item.occurrenceAvailableAt,
                    "catalysts.occurrenceAvailableAt",
                ),
                occurrence_source=item.occurrenceSource,
                occurrence_source_ref=item.occurrenceSourceRef,
            )
        )

    try:
        result = catalyst_service.evaluate(
            symbol=request.symbol,
            as_of=as_of,
            catalysts=tuple(inputs),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo evaluar Catalysts PIT de ATHENA.",
        ) from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Catalysts devolvió un contrato inválido.")
    _assert_contract(payload)
    return {"data": payload}
