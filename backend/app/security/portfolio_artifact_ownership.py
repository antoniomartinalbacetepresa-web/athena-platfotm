from __future__ import annotations

from datetime import datetime, timezone
import re

from app.database.athena_database import AthenaDatabase
from app.security.portfolio_owner_context import current_portfolio_owner_id


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_KINDS = frozenset({"state_reconciliation", "reconciled_weight"})
_TABLE = "athena_portfolio_artifact_ownership_v2"


class PortfolioArtifactOwnershipRegistry:
    """Fail-closed owner links for immutable keyed portfolio artifacts.

    Artifact bytes may legitimately deduplicate across accounts. Ownership is
    therefore a many-to-many relation: a user gains a link only after an
    authenticated workflow independently creates or validates that exact
    artifact. Merely knowing another user's key never creates a link.
    """

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    owner_user_id INTEGER NOT NULL,
                    artifact_kind TEXT NOT NULL,
                    artifact_key TEXT NOT NULL,
                    linked_at TEXT NOT NULL,
                    PRIMARY KEY (owner_user_id, artifact_kind, artifact_key)
                );

                CREATE INDEX IF NOT EXISTS idx_portfolio_artifact_owner_kind_v2
                ON {_TABLE}(owner_user_id, artifact_kind);

                CREATE INDEX IF NOT EXISTS idx_portfolio_artifact_key_kind_v2
                ON {_TABLE}(artifact_kind, artifact_key, owner_user_id);
                """
            )

    def link_current_owner(self, *, artifact_kind: str, artifact_key: str) -> None:
        self.initialize()
        owner_id = current_portfolio_owner_id()
        kind = self._kind(artifact_kind)
        key = self._key(artifact_key)
        with self._database.connect() as connection:
            connection.execute(
                f"""
                INSERT OR IGNORE INTO {_TABLE} (
                    owner_user_id, artifact_kind, artifact_key, linked_at
                ) VALUES (?, ?, ?, ?)
                """,
                (owner_id, kind, key, datetime.now(timezone.utc).isoformat()),
            )

    def require_current_owner(self, *, artifact_kind: str, artifact_key: str) -> None:
        self.initialize()
        owner_id = current_portfolio_owner_id()
        kind = self._kind(artifact_kind)
        key = self._key(artifact_key)
        with self._database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT 1
                FROM {_TABLE}
                WHERE owner_user_id = ? AND artifact_kind = ? AND artifact_key = ?
                """,
                (owner_id, kind, key),
            ).fetchone()
        if row is None:
            raise ValueError("portfolio artifact is not available for the authenticated owner")

    @staticmethod
    def _kind(value: object) -> str:
        kind = str(value or "").strip()
        if kind not in _ALLOWED_KINDS:
            raise ValueError("unsupported portfolio artifact ownership kind")
        return kind

    @staticmethod
    def _key(value: object) -> str:
        key = str(value or "").strip().lower()
        if _SHA256_RE.fullmatch(key) is None:
            raise ValueError("portfolio artifact key must be a SHA-256 fingerprint")
        return key
