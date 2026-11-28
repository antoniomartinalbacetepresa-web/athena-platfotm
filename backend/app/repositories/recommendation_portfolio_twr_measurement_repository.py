from __future__ import annotations

import re
from typing import Any

from app.repositories.recommendation_portfolio_nlv_snapshot_repository import (
    RecommendationPortfolioNlvSnapshotRepository,
)
from app.repositories.recommendation_portfolio_twr_measurement_repository_core import (
    RecommendationPortfolioTwrMeasurementRepository as _CoreRepository,
)
from app.security.portfolio_owner_context import current_portfolio_owner_id


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationPortfolioTwrMeasurementRepository(_CoreRepository):
    """Owner-gated TWR store backed by owner-scoped NLV evidence.

    API requests bind an authenticated portfolio owner. In that context, a TWR
    artifact must carry sealed ``nlvEvidence`` and every referenced NLV snapshot
    must belong to that owner. Low-level integrity tests and trusted internal
    code may still exercise the historical core repository contract outside an
    owner context; such ownerless access is never exposed by the authenticated
    routers.
    """

    @staticmethod
    def _owner_context_active() -> bool:
        try:
            current_portfolio_owner_id()
        except ValueError:
            return False
        return True

    def _require_owned_nlv_evidence(self, artifact: dict[str, Any]) -> None:
        nlv = artifact.get("nlvEvidence")
        if not isinstance(nlv, dict):
            if self._owner_context_active():
                raise ValueError("TWR measurement has no sealed NLV ownership evidence")
            return
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
