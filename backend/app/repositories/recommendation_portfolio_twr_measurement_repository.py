from __future__ import annotations

import re
from typing import Any

from app.repositories.recommendation_portfolio_nlv_snapshot_repository import (
    RecommendationPortfolioNlvSnapshotRepository,
)
from app.repositories.recommendation_portfolio_twr_measurement_repository_core import (
    RecommendationPortfolioTwrMeasurementRepository as _CoreRepository,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationPortfolioTwrMeasurementRepository(_CoreRepository):
    """Owner-gated TWR store backed by owner-scoped NLV evidence.

    The persisted TWR artifact remains content-addressed and owner-neutral. Access
    is authorized transitively: every referenced NLV snapshot must belong to the
    current authenticated portfolio owner. Legacy TWR artifacts whose NLV
    snapshots have no owner-scoped v2 rows therefore fail closed.
    """

    def _require_owned_nlv_evidence(self, artifact: dict[str, Any]) -> None:
        nlv = artifact.get("nlvEvidence")
        if not isinstance(nlv, dict):
            raise ValueError("TWR measurement has no sealed NLV ownership evidence")
        keys = nlv.get("snapshotKeys")
        if not isinstance(keys, list) or len(keys) < 2:
            raise ValueError("TWR measurement has no valid NLV snapshot ownership set")
        repository = RecommendationPortfolioNlvSnapshotRepository(database=self._database)
        seen: set[str] = set()
        for raw_key in keys:
            key = str(raw_key or "").strip().lower()
            if _SHA256_RE.fullmatch(key) is None or key in seen:
                raise ValueError("TWR measurement contains invalid or duplicate NLV snapshotKey")
            seen.add(key)
            repository.get_by_key(snapshot_key=key)

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self._require_owned_nlv_evidence(artifact)
        return super().append(artifact=artifact)

    def get_by_key(self, *, measurement_key: str) -> dict[str, Any]:
        record = super().get_by_key(measurement_key=measurement_key)
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("persisted TWR record has no valid artifact")
        self._require_owned_nlv_evidence(artifact)
        return record
