"""Authenticated synthetic-only daily rebound research; no state or providers."""
from datetime import date, datetime
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator

from app.api.auth import current_account
from app.services.rebound25_synthetic_backtest_service import (
    Rebound25Parameters, SyntheticReboundBar, run_rebound25_synthetic_backtest,
)


router = APIRouter(
    prefix="/api/v1/research/strategies/rebound25", tags=["synthetic-strategy-research"],
    dependencies=[Depends(current_account)],
)
_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or _INSTANT.fullmatch(value) is None:
        raise ValueError("use an explicit offset-aware ASCII ISO timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _session(value: object) -> date:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("use an ASCII ISO session date")
    return date.fromisoformat(value)


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SyntheticReboundBarRequest(_StrictRequest):
    session: date
    open_at: datetime = Field(alias="openAt")
    observed_at: datetime = Field(alias="observedAt")
    available_at: datetime = Field(alias="availableAt")
    open: StrictFloat = Field(gt=0)
    high: StrictFloat = Field(gt=0)
    low: StrictFloat = Field(gt=0)
    close: StrictFloat = Field(gt=0)
    volume: StrictFloat = Field(ge=0)

    @field_validator("open_at", "observed_at", "available_at", mode="before")
    @classmethod
    def parse_instant(cls, value: object) -> datetime:
        return _instant(value)

    @field_validator("session", mode="before")
    @classmethod
    def parse_session(cls, value: object) -> date:
        return _session(value)


class Rebound25ParametersRequest(_StrictRequest):
    take_profit_pct: StrictFloat = Field(alias="takeProfitPct", gt=0)
    stop_loss_pct: StrictFloat = Field(alias="stopLossPct", gt=0, lt=100)
    max_holding_sessions: StrictInt = Field(alias="maxHoldingSessions", ge=1, le=252)
    commission_bps: StrictFloat = Field(alias="commissionBps", ge=0)
    spread_bps: StrictFloat = Field(alias="spreadBps", ge=0)
    slippage_bps: StrictFloat = Field(alias="slippageBps", ge=0)
    order_units: StrictFloat = Field(alias="orderUnits", gt=0)
    min_average_volume: StrictFloat = Field(alias="minAverageVolume", gt=0)
    max_volume_participation: StrictFloat = Field(alias="maxVolumeParticipation", gt=0, le=1)
    min_relative_volume: StrictFloat = Field(alias="minRelativeVolume", ge=0)
    lookback_sessions: StrictInt = Field(default=25, alias="lookbackSessions", ge=1, le=252)
    min_rebound_pct: StrictFloat = Field(default=1, alias="minReboundPct", ge=0)
    max_confirmation_sessions: StrictInt = Field(default=3, alias="maxConfirmationSessions", ge=1, le=252)
    version: Literal["rebound25-synthetic-v1"] = "rebound25-synthetic-v1"


class SyntheticReboundBacktestRequest(_StrictRequest):
    evidence_kind: Literal["synthetic_fixture"] = Field(alias="evidenceKind")
    instrument_id: str = Field(alias="instrumentId", min_length=1, max_length=160)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    as_of: datetime = Field(alias="asOf")
    precommitted_at: datetime = Field(alias="precommittedAt")
    expected_sessions: list[date] = Field(alias="expectedSessions", min_length=2, max_length=5000)
    bars: list[SyntheticReboundBarRequest] = Field(min_length=2, max_length=5000)
    parameters: Rebound25ParametersRequest

    @field_validator("as_of", "precommitted_at", mode="before")
    @classmethod
    def parse_instant(cls, value: object) -> datetime:
        return _instant(value)

    @field_validator("expected_sessions", mode="before")
    @classmethod
    def parse_sessions(cls, value: object) -> list[date]:
        if not isinstance(value, list) or not 2 <= len(value) <= 5000:
            raise ValueError("provide between 2 and 5000 explicit session dates")
        return [_session(item) for item in value]


@router.post("/synthetic-backtest")
def synthetic_backtest(payload: SyntheticReboundBacktestRequest) -> dict:
    try:
        result = run_rebound25_synthetic_backtest(
            [SyntheticReboundBar(**bar.model_dump()) for bar in payload.bars],
            parameters=Rebound25Parameters(**payload.parameters.model_dump()),
            expected_sessions=payload.expected_sessions, as_of=payload.as_of,
            precommitted_at=payload.precommitted_at, instrument_id=payload.instrument_id,
            currency=payload.currency, evidence_kind=payload.evidence_kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Synthetic strategy research unavailable.") from exc
    return {"data": result}
