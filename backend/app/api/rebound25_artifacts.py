"""Private durable artificial Lab artifacts, generated entirely on the server."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.api.auth import current_account
from app.api.rebound25_synthetic import Rebound25ParametersRequest
from app.services.rebound25_artifact_service import Rebound25ArtifactService


router = APIRouter(prefix="/api/v1/research/strategies/rebound25/artifacts",
                   tags=["private-synthetic-strategy-artifacts"])
artifact_service = Rebound25ArtifactService()


class CreateSyntheticArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fixtureId: Literal["synthetic-rebound25-demo-v1"]
    parameters: Rebound25ParametersRequest


def _owner(account: dict) -> int:
    owner = account.get("id")
    if type(owner) is not int or owner <= 0:
        raise HTTPException(status_code=401, detail="Credenciales no válidas.")
    return owner


@router.post("")
def create_artifact(payload: CreateSyntheticArtifactRequest,
                    account: Annotated[dict, Depends(current_account)]) -> dict:
    owner = _owner(account)
    try:
        detail = artifact_service.create(owner_id=owner, fixture_id=payload.fixtureId,
                                         parameters=payload.parameters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Parámetros de simulación sintética inválidos.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="No se pudo guardar el artefacto sintético.") from exc
    return {"data": detail}


@router.get("")
def list_artifacts(account: Annotated[dict, Depends(current_account)],
                   limit: int = Query(20, ge=1, le=50)) -> dict:
    owner = _owner(account)
    try:
        return {"data": artifact_service.list(owner_id=owner, limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Índice de artefactos sintéticos no disponible.") from exc


@router.get("/{artifact_hash}")
def get_artifact(artifact_hash: str,
                 account: Annotated[dict, Depends(current_account)]) -> dict:
    owner = _owner(account)
    try:
        return {"data": artifact_service.get(owner_id=owner, artifact_hash=artifact_hash)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Artefacto sintético no encontrado.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Artefacto sintético no verificable.") from exc
