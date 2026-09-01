from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal


DataKind = Literal[
    "fact",
    "calculation",
    "estimate",
    "external_opinion",
]


@dataclass(frozen=True)
class DataProvenance:
    source_id: str
    retrieved_at: str
    effective_at: str | None = None
    published_at: str | None = None
    source_timestamp: str | None = None
    version: str | None = None
    raw_identifier: str | None = None
    normalized_identifier: str | None = None
    source_url: str | None = None

    @classmethod
    def now(
        cls,
        *,
        source_id: str,
        effective_at: str | None = None,
        published_at: str | None = None,
        source_timestamp: str | None = None,
        version: str | None = None,
        raw_identifier: str | None = None,
        normalized_identifier: str | None = None,
        source_url: str | None = None,
    ) -> "DataProvenance":
        return cls(
            source_id=source_id.strip(),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            effective_at=effective_at,
            published_at=published_at,
            source_timestamp=source_timestamp,
            version=version,
            raw_identifier=raw_identifier,
            normalized_identifier=normalized_identifier,
            source_url=source_url,
        )

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id is required.")
        if not self.retrieved_at.strip():
            raise ValueError("retrieved_at is required.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedDatum:
    metric: str
    value: float | int | str | bool | None
    data_kind: DataKind
    provenance: DataProvenance
    unit: str | None = None
    currency: str | None = None
    entity_id: str | None = None
    quality_score: float | None = None
    confidence_score: float | None = None

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValueError("metric is required.")
        for name, score in (
            ("quality_score", self.quality_score),
            ("confidence_score", self.confidence_score),
        ):
            if score is not None and not 0 <= score <= 100:
                raise ValueError(f"{name} must be between 0 and 100.")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data
