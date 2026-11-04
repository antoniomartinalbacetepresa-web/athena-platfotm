from __future__ import annotations

from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_portfolio_correlation_evidence_repository import (
    RecommendationPortfolioCorrelationEvidenceRepository,
)
from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
)


class OwnerScopedPortfolioValuationEvidenceRepository:
    """Bind valuation evidence operations to one authenticated account."""

    def __init__(
        self,
        *,
        owner_user_id: int,
        repository: RecommendationPortfolioValuationEvidenceRepository | None = None,
    ) -> None:
        self._owner_user_id = self._positive_owner(owner_user_id)
        self._repository = repository or RecommendationPortfolioValuationEvidenceRepository()

    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        return self._repository.seal(
            owner_user_id=self._owner_user_id,
            artifact=artifact,
        )

    def get(self, *, valuation_fingerprint: str) -> dict[str, Any] | None:
        return self._repository.get(
            owner_user_id=self._owner_user_id,
            valuation_fingerprint=valuation_fingerprint,
        )

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._repository.validate_record(record)

    @staticmethod
    def _positive_owner(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("owner_user_id debe ser un entero positivo.")
        return value


class OwnerScopedPortfolioCorrelationEvidenceRepository:
    """Owner-aware facade over immutable globally deduplicated correlation evidence.

    The evidence artifact stays content-addressed and globally deduplicated, while an
    independent many-to-many ownership table controls which authenticated accounts may
    resolve a fingerprint. Existing legacy evidence is not implicitly assigned to any
    account; an account gains the link only by sealing the exact verified artifact in
    its own authenticated flow.
    """

    def __init__(
        self,
        *,
        owner_user_id: int,
        database: AthenaDatabase | None = None,
        repository: RecommendationPortfolioCorrelationEvidenceRepository | None = None,
    ) -> None:
        self._owner_user_id = self._positive_owner(owner_user_id)
        self._database = database if database is not None else AthenaDatabase()
        self._repository = repository or RecommendationPortfolioCorrelationEvidenceRepository(
            database=self._database
        )

    def initialize(self) -> None:
        self._repository.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_portfolio_correlation_evidence_owners (
                    owner_user_id INTEGER NOT NULL,
                    evidence_fingerprint TEXT NOT NULL,
                    linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (owner_user_id, evidence_fingerprint),
                    FOREIGN KEY (evidence_fingerprint)
                        REFERENCES athena_recommendation_portfolio_correlation_evidence(evidence_fingerprint)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_portfolio_correlation_evidence_owner_fingerprint
                ON athena_recommendation_portfolio_correlation_evidence_owners(
                    evidence_fingerprint,
                    owner_user_id
                );
                """
            )

    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        record = self._repository.seal(artifact=artifact)
        fingerprint = self._fingerprint_from_record(record)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO athena_recommendation_portfolio_correlation_evidence_owners (
                    owner_user_id,
                    evidence_fingerprint
                ) VALUES (?, ?)
                """,
                (self._owner_user_id, fingerprint),
            )
        owned = self.get(evidence_fingerprint=fingerprint)
        if owned is None:
            raise RuntimeError("No se pudo vincular la evidencia de correlación al propietario.")
        return owned

    def get(self, *, evidence_fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        fingerprint = self._sha256(evidence_fingerprint)
        with self._database.connect() as connection:
            ownership = connection.execute(
                """
                SELECT 1
                FROM athena_recommendation_portfolio_correlation_evidence_owners
                WHERE owner_user_id = ? AND evidence_fingerprint = ?
                """,
                (self._owner_user_id, fingerprint),
            ).fetchone()
        if ownership is None:
            return None
        return self._repository.get(evidence_fingerprint=fingerprint)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._repository.validate_record(record)

    @staticmethod
    def _positive_owner(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("owner_user_id debe ser un entero positivo.")
        return value

    @staticmethod
    def _sha256(value: object) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError("evidence_fingerprint debe ser SHA-256 hexadecimal.")
        return result

    def _fingerprint_from_record(self, record: object) -> str:
        if not isinstance(record, dict):
            raise ValueError("El repositorio no devolvió un registro de correlación válido.")
        return self._sha256(record.get("evidence_fingerprint"))
