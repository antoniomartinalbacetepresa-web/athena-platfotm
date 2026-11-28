"""Append-only owner-bound server-fixture research artifacts; no market ledger."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3

from app.database.athena_database import AthenaDatabase


FIXTURE_ID = "synthetic-rebound25-demo-v1"
ARTIFACT_SCHEMA = "athena.server-synthetic-rebound25-artifact.v1"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def artifact_hash(*, owner_id: int, fixture_id: str, request: dict,
                  result: dict, created_at: str) -> str:
    # Bind first creation time as well as owner/content. A Journal reference
    # cannot be backdated while retaining the original content-addressed ID.
    body = {"schema": ARTIFACT_SCHEMA, "ownerId": owner_id, "fixtureId": fixture_id,
            "request": request, "result": result, "createdAt": created_at}
    return hashlib.sha256(canonical_json(body).encode()).hexdigest()


class Rebound25ArtifactRepository:
    def __init__(self, database: AthenaDatabase | None = None):
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS athena_rebound25_synthetic_artifacts (
                owner_id INTEGER NOT NULL CHECK(owner_id > 0),
                artifact_hash TEXT NOT NULL,
                fixture_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (owner_id, artifact_hash),
                UNIQUE (owner_id, fixture_id, request_json)
            )""")

    @staticmethod
    def _owner(owner_id: int) -> None:
        if type(owner_id) is not int or owner_id <= 0:
            raise ValueError("Invalid artifact owner.")

    @staticmethod
    def _read(row: sqlite3.Row, *, owner_id: int) -> dict:
        request, result = json.loads(row["request_json"]), json.loads(row["result_json"])
        created = datetime.fromisoformat(row["created_at"])
        if (row["owner_id"] != owner_id or not isinstance(request, dict)
                or not isinstance(result, dict) or created.utcoffset() is None
                or created.astimezone(timezone.utc).isoformat() != row["created_at"]
                or created > datetime.now(timezone.utc)
                or canonical_json(request) != row["request_json"]
                or canonical_json(result) != row["result_json"]
                or artifact_hash(owner_id=owner_id, fixture_id=row["fixture_id"], request=request,
                                 result=result, created_at=row["created_at"]) != row["artifact_hash"]):
            raise ValueError("Persisted synthetic artifact lost its integrity.")
        return {"artifactHash": row["artifact_hash"], "fixtureId": row["fixture_id"],
                "createdAt": row["created_at"], "request": request, "result": result}

    def append(self, *, owner_id: int, fixture_id: str, request: dict, result: dict,
               connection: sqlite3.Connection | None = None) -> dict:
        self._owner(owner_id)
        if fixture_id != FIXTURE_ID or not isinstance(request, dict) or not isinstance(result, dict):
            raise ValueError("Invalid server fixture artifact.")
        request_json, result_json = canonical_json(request), canonical_json(result)
        if connection is None:
            self.initialize()
            with self._database.connect() as own:
                own.execute("BEGIN IMMEDIATE")
                return self.append(owner_id=owner_id, fixture_id=fixture_id,
                                   request=request, result=result, connection=own)
        existing = connection.execute("""SELECT * FROM athena_rebound25_synthetic_artifacts
            WHERE owner_id = ? AND fixture_id = ? AND request_json = ?""",
            (owner_id, fixture_id, request_json)).fetchone()
        if existing is not None:
            record = self._read(existing, owner_id=owner_id)
            if canonical_json(record["result"]) != result_json:
                raise ValueError("Existing artifact does not match the reproducible result.")
            return record
        created = datetime.now(timezone.utc).isoformat()
        digest = artifact_hash(owner_id=owner_id, fixture_id=fixture_id, request=request,
                               result=result, created_at=created)
        connection.execute("""INSERT INTO athena_rebound25_synthetic_artifacts
            (owner_id, artifact_hash, fixture_id, request_json, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (owner_id, digest, fixture_id, request_json, result_json, created))
        row = connection.execute("""SELECT * FROM athena_rebound25_synthetic_artifacts
            WHERE owner_id = ? AND artifact_hash = ?""", (owner_id, digest)).fetchone()
        return self._read(row, owner_id=owner_id)

    def get(self, artifact_hash: str, *, owner_id: int,
            connection: sqlite3.Connection | None = None) -> dict:
        self._owner(owner_id)
        if not isinstance(artifact_hash, str) or re.fullmatch(r"[a-f0-9]{64}", artifact_hash) is None:
            raise LookupError("Synthetic artifact not found.")
        if connection is None:
            self.initialize()
            with self._database.connect() as own:
                own.execute("BEGIN")
                return self.get(artifact_hash, owner_id=owner_id, connection=own)
        row = connection.execute("""SELECT * FROM athena_rebound25_synthetic_artifacts
            WHERE owner_id = ? AND artifact_hash = ?""", (owner_id, artifact_hash)).fetchone()
        if row is None:
            raise LookupError("Synthetic artifact not found.")
        return self._read(row, owner_id=owner_id)

    def list(self, *, owner_id: int, limit: int = 20) -> tuple[list[dict], bool]:
        self._owner(owner_id)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Artifact limit must be between 1 and 50.")
        self.initialize()
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            rows = connection.execute("""SELECT * FROM athena_rebound25_synthetic_artifacts
                WHERE owner_id = ? ORDER BY created_at DESC, artifact_hash ASC LIMIT ?""",
                (owner_id, limit + 1)).fetchall()
            records = [self._read(row, owner_id=owner_id) for row in rows[:limit]]
        return records, len(rows) > limit
