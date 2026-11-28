"""Persist only a versioned server-generated synthetic lab fixture and parameters."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

from app.api.rebound25_synthetic import Rebound25ParametersRequest, SyntheticReboundBacktestRequest
from app.database.athena_database import AthenaDatabase
from app.repositories.rebound25_artifact_repository import (
    FIXTURE_ID, Rebound25ArtifactRepository, canonical_json,
)
from app.services.rebound25_synthetic_backtest_service import (
    Rebound25Parameters, SyntheticReboundBar, run_rebound25_synthetic_backtest,
)


def build_server_rebound25_fixture(parameters: Rebound25ParametersRequest) -> dict:
    """Versioned arithmetic fixture identical to the artificial Flutter Lab.

    Consecutive calendar dates are deliberately NOT a real exchange calendar.
    No client prices, source-name classifications or provider rights enter here.
    """
    # Pydantic defaults may retain an integer spelling for a StrictFloat field
    # (for example the default minReboundPct=1). Revalidate the complete model
    # once so omitted and explicit defaults produce one canonical request and
    # one idempotent artifact rather than 1 versus 1.0 variants.
    normalized_parameters = Rebound25ParametersRequest.model_validate(
        parameters.model_dump(by_alias=True)
    ).model_dump(by_alias=True)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    for index in range(40):
        day = start + timedelta(days=index)
        bars.append({
            "session": day.date().isoformat(),
            "openAt": (day + timedelta(hours=9)).isoformat(),
            "observedAt": (day + timedelta(hours=17)).isoformat(),
            "availableAt": (day + timedelta(hours=18)).isoformat(),
            "open": 98.0 if index == 25 else 95.0 if index == 26 else 97.0 if index == 27 else 100.0,
            "high": 99.0 if index == 25 else 98.0 if index == 26 else 100.0 if index == 27 else 102.0,
            "low": 94.0 if index in (25, 26) else 96.0 if index == 27 else 99.0,
            "close": 95.0 if index == 25 else 97.0 if index == 26 else 99.0 if index == 27 else 100.0,
            "volume": 2000.0 if index in (25, 26) else 1000.0,
        })
    return {"evidenceKind": "synthetic_fixture", "instrumentId": "SYNTHETIC-LAB-25",
            "currency": "USD", "asOf": bars[-1]["availableAt"],
            "precommittedAt": (start + timedelta(days=25, hours=8)).isoformat(),
            "expectedSessions": [bar["session"] for bar in bars], "bars": bars,
            "parameters": normalized_parameters}


class Rebound25ArtifactService:
    def __init__(self, database: AthenaDatabase | None = None):
        self.repository = Rebound25ArtifactRepository(database)

    def initialize(self) -> None:
        self.repository.initialize()

    @staticmethod
    def _calculate(request: dict) -> dict:
        payload = SyntheticReboundBacktestRequest.model_validate(request)
        return run_rebound25_synthetic_backtest(
            [SyntheticReboundBar(**bar.model_dump()) for bar in payload.bars],
            parameters=Rebound25Parameters(**payload.parameters.model_dump()),
            expected_sessions=payload.expected_sessions, as_of=payload.as_of,
            precommitted_at=payload.precommitted_at, instrument_id=payload.instrument_id,
            currency=payload.currency, evidence_kind=payload.evidence_kind,
        )

    def _validate(self, record: dict) -> dict:
        if record["fixtureId"] != FIXTURE_ID:
            raise ValueError("Unsupported persisted server fixture.")
        parameters = Rebound25ParametersRequest.model_validate(record["request"]["parameters"])
        regenerated = build_server_rebound25_fixture(parameters)
        if (canonical_json(regenerated) != canonical_json(record["request"])
                or canonical_json(self._calculate(regenerated)) != canonical_json(record["result"])):
            raise ValueError("Artifact no longer matches the server fixture and calculation.")
        if datetime.fromisoformat(record["createdAt"]) < datetime.fromisoformat(regenerated["asOf"]):
            raise ValueError("Artifact creation cannot precede the simulated series cutoff.")
        return {**record, **self._flags(), "serverFixtureGenerated": True}

    @staticmethod
    def _flags() -> dict:
        return {"ownerBindingVerified": True, "evidenceKind": "synthetic_fixture",
                "automaticTrading": False, "ordersEnabled": False,
                "productionEligible": False, "licenseVerified": False,
                "outOfSampleValidated": False}

    def create(self, *, owner_id: int, fixture_id: str,
               parameters: Rebound25ParametersRequest) -> dict:
        if fixture_id != FIXTURE_ID:
            raise ValueError("Unsupported server fixture.")
        request = build_server_rebound25_fixture(parameters)
        result = self._calculate(request)
        # Validation is part of the write transaction. A failed recomputation
        # must not leave an artifact that the same service refuses to read.
        self.repository._owner(owner_id)
        self.initialize()
        with self.repository._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = self.repository.append(owner_id=owner_id, fixture_id=fixture_id,
                                            request=request, result=result, connection=connection)
            return self._validate(record)

    def get(self, *, owner_id: int, artifact_hash: str,
            connection: sqlite3.Connection | None = None) -> dict:
        return self._validate(self.repository.get(artifact_hash, owner_id=owner_id, connection=connection))

    def list(self, *, owner_id: int, limit: int = 20) -> dict:
        records, has_more = self.repository.list(owner_id=owner_id, limit=limit)
        details = [self._validate(record) for record in records]
        return {"items": [{key: detail[key] for key in ("artifactHash", "fixtureId", "createdAt")}
                          for detail in details], "returnedCount": len(details), "limit": limit,
                "hasMore": has_more, "metadataOnly": True, "readOnly": True, **self._flags()}
