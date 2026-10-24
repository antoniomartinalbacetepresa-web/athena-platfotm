from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path

from app.repositories.recommendation_allocation_policy_repository import (
    RecommendationAllocationPolicyRepository,
)


router = APIRouter(
    prefix="/api/v1/portfolio/allocation-policies",
    tags=["portfolio"],
)


def _safe_policy_record(
    repository: RecommendationAllocationPolicyRepository,
    record: dict[str, Any],
) -> dict[str, Any]:
    if repository.validate_record(record) is not record:
        raise RuntimeError("El repositorio sustituyó la política persistida.")
    policy = record.get("policy")
    if not isinstance(policy, dict):
        raise RuntimeError("La política persistida carece de payload válido.")
    controls = policy.get("policy")
    if not isinstance(controls, dict):
        raise RuntimeError("La política persistida carece de controles verificables.")
    for field in (
        "codeDefaultTargetWeight",
        "codeDefaultCorrelationThreshold",
        "codeDefaultStalenessThreshold",
        "automaticTrading",
    ):
        if controls.get(field) is not False:
            raise RuntimeError(f"La política violó {field}=False.")
    return {
        "policy": policy,
        "persistence": {
            "persisted": True,
            "registeredAt": record.get("registered_at"),
            "policyFingerprint": record.get("policy_fingerprint"),
        },
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
        "policySelectionPerformed": False,
        "defaultPolicyExists": False,
    }


@router.get("")
def list_portfolio_allocation_policies() -> dict[str, object]:
    """List immutable allocation policies without choosing one for the caller."""
    repository = RecommendationAllocationPolicyRepository()
    try:
        records = repository.list_all()
        return {
            "data": [
                _safe_policy_record(repository, record)
                for record in records
            ],
            "selection": {
                "explicitSelectionRequired": True,
                "policySelectionPerformed": False,
                "defaultPolicyExists": False,
                "automaticTrading": False,
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudieron recuperar políticas de asignación verificables.",
        ) from exc


@router.get("/{policy_id}")
def get_portfolio_allocation_policy(
    policy_id: str = Path(..., min_length=1),
) -> dict[str, object]:
    """Resolve one exact persisted policy by its explicit immutable ID."""
    repository = RecommendationAllocationPolicyRepository()
    try:
        record = repository.get(policy_id=policy_id)
        if record is None:
            raise ValueError("La política de asignación solicitada no está registrada.")
        return {"data": _safe_policy_record(repository, record)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo recuperar la política de asignación solicitada.",
        ) from exc


@router.post("")
def post_portfolio_allocation_policy(
    payload: dict[str, Any] = Body(...),
) -> dict[str, object]:
    """Persist caller-owned limits exactly; never inject ATHENA defaults."""
    repository = RecommendationAllocationPolicyRepository()
    try:
        record = repository.register(policy_draft=payload)
        return {"data": _safe_policy_record(repository, record)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo registrar una política de asignación verificable.",
        ) from exc
