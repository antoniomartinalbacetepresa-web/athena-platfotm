from __future__ import annotations

from contextlib import nullcontext
import json
import sqlite3
import re
from datetime import datetime
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_investment_journal_service import (
    InvestmentJournalReferenceInput,
    InvestmentJournalSnapshot,
    RecommendationInvestmentJournalService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationInvestmentJournalRepository:
    """Append-only persistence for PIT investment-journal revisions.

    The repository never updates or deletes journal revisions. Every revision
    after the first must point at the exact snapshot hash of the current head,
    which makes skipped, forked, or rewritten lineage fail closed.
    """

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._snapshot_service = RecommendationInvestmentJournalService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_investment_journal_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    prior_snapshot_hash TEXT,
                    snapshot_hash TEXT NOT NULL UNIQUE,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (journal_id, revision_id)
                );

                CREATE INDEX IF NOT EXISTS idx_investment_journal_head
                ON athena_investment_journal_snapshots(journal_id, id);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_investment_journal_single_root
                ON athena_investment_journal_snapshots(journal_id)
                WHERE prior_snapshot_hash IS NULL;

                CREATE UNIQUE INDEX IF NOT EXISTS idx_investment_journal_single_successor
                ON athena_investment_journal_snapshots(journal_id, prior_snapshot_hash)
                WHERE prior_snapshot_hash IS NOT NULL;
                """
            )

    def append(
        self, *, snapshot: InvestmentJournalSnapshot,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        # Validate the exact canonical snapshot BEFORE any schema or data write.
        # A forged dataclass must not poison an append-only journal.
        payload = self._validated_snapshot(snapshot)
        if connection is None:
            self.initialize()
        journal_id = str(payload["journalId"])
        revision_id = str(payload["revisionId"])
        symbol = str(payload["symbol"])
        recorded_at = str(payload["recordedAt"])
        as_of = str(payload["asOf"])
        prior_hash = payload.get("priorSnapshotHash")
        snapshot_hash = str(payload["snapshotHash"])
        created_at = datetime.now().astimezone().isoformat()

        owns_connection = connection is None
        with (self._database.connect() if owns_connection else nullcontext(connection)) as connection:
            # A caller may already hold the write transaction for a paired cycle.
            if owns_connection:
                connection.execute("BEGIN IMMEDIATE")
            chain_rows = connection.execute(
                """SELECT * FROM athena_investment_journal_snapshots
                   WHERE journal_id = ? ORDER BY id ASC""",
                (journal_id,),
            ).fetchall()
            existing_chain: list[dict[str, Any]] = []
            for chain_row in chain_rows:
                chain_record = self._row(chain_row)
                if chain_record is None:
                    raise ValueError("El lineage persistido contiene una revisión ilegible.")
                existing_chain.append(chain_record)
            self._validate_chain(existing_chain)

            existing_revision = connection.execute(
                """
                SELECT * FROM athena_investment_journal_snapshots
                WHERE journal_id = ? AND revision_id = ?
                """,
                (journal_id, revision_id),
            ).fetchone()
            if existing_revision is not None:
                existing = self._row(existing_revision)
                if existing is None:
                    raise RuntimeError("No se pudo recuperar la revisión existente del journal.")
                if existing["snapshot_hash"] != snapshot_hash:
                    raise ValueError("revision_id ya existe; las revisiones del journal son inmutables.")
                return self.validate_record(existing)

            duplicate_hash = connection.execute(
                """
                SELECT * FROM athena_investment_journal_snapshots
                WHERE snapshot_hash = ?
                """,
                (snapshot_hash,),
            ).fetchone()
            if duplicate_hash is not None:
                raise ValueError("snapshot_hash ya existe; no se puede reutilizar una revisión en otro journal.")

            head_row = connection.execute(
                """
                SELECT * FROM athena_investment_journal_snapshots
                WHERE journal_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (journal_id,),
            ).fetchone()
            head = self._row(head_row)
            if head is None:
                if prior_hash is not None:
                    raise ValueError("La primera revisión de un journal no puede declarar prior_snapshot_hash.")
            else:
                self.validate_record(head)
                if head["symbol"] != symbol:
                    raise ValueError("El símbolo no puede cambiar dentro del mismo journal.")
                if prior_hash != head["snapshot_hash"]:
                    raise ValueError("prior_snapshot_hash debe enlazar exactamente con el head persistido del journal.")
                if self._aware_iso(recorded_at, "recorded_at") < self._aware_iso(
                    head["recorded_at"], "head.recorded_at"
                ):
                    raise ValueError("recorded_at no puede retroceder respecto de la revisión anterior.")

            serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            connection.execute(
                """
                INSERT INTO athena_investment_journal_snapshots (
                    journal_id, revision_id, symbol, recorded_at, as_of,
                    prior_snapshot_hash, snapshot_hash, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    journal_id,
                    revision_id,
                    symbol,
                    recorded_at,
                    as_of,
                    prior_hash,
                    snapshot_hash,
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM athena_investment_journal_snapshots
                WHERE journal_id = ? AND revision_id = ?
                """,
                (journal_id, revision_id),
            ).fetchone()

        record = self._row(row)
        if record is None:
            raise RuntimeError("No se pudo recuperar la revisión persistida del journal.")
        return self.validate_record(record)

    def get_journal(
        self, *, journal_id: str, connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        if connection is None:
            self.initialize()
        normalized = self._required_text(journal_id, "journal_id")
        with (self._database.connect() if connection is None else nullcontext(connection)) as connection:
            rows = connection.execute(
                """
                SELECT * FROM athena_investment_journal_snapshots
                WHERE journal_id = ?
                ORDER BY id ASC
                """,
                (normalized,),
            ).fetchall()
        return [self.validate_record(record) for row in rows if (record := self._row(row)) is not None]

    def verify_lineage(
        self, *, journal_id: str, connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        records = self.get_journal(journal_id=journal_id, connection=connection)
        if not records:
            raise ValueError("No existe un journal persistido con ese journal_id.")

        self._validate_chain(records)
        previous_hash = records[-1]["snapshot_hash"]
        symbol = records[0]["symbol"]

        return {
            "status": "lineage_verified",
            "journalId": journal_id,
            "symbol": symbol,
            "revisionCount": len(records),
            "headSnapshotHash": previous_hash,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "appendOnly": True,
                "lineage": "every_revision_links_to_exact_previous_persisted_snapshot_hash",
                "hindsight": "persisted_revisions_are_never_updated_or_deleted_by_repository",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }

    def _validate_chain(self, records: list[dict[str, Any]]) -> None:
        previous_hash: str | None = None
        previous_recorded_at: datetime | None = None
        symbol = records[0]["symbol"] if records else None
        seen_revisions: set[str] = set()
        seen_hashes: set[str] = set()
        for index, record in enumerate(records):
            self.validate_record(record)
            revision_id = record["revision_id"]
            snapshot_hash = record["snapshot_hash"]
            if revision_id in seen_revisions or snapshot_hash in seen_hashes:
                raise ValueError("El lineage contiene identidades o hashes duplicados.")
            seen_revisions.add(revision_id)
            seen_hashes.add(snapshot_hash)
            if record["symbol"] != symbol:
                raise ValueError("El lineage cambió de símbolo.")
            if record["prior_snapshot_hash"] != previous_hash:
                raise ValueError("El lineage persistido está roto o contiene una bifurcación.")
            recorded_at = self._aware_iso(record["recorded_at"], "recorded_at")
            if previous_recorded_at is not None and recorded_at < previous_recorded_at:
                raise ValueError("El lineage retrocede temporalmente.")
            previous_recorded_at = recorded_at
            previous_hash = snapshot_hash
            if index == 0 and record["prior_snapshot_hash"] is not None:
                raise ValueError("La primera revisión no puede tener prior_snapshot_hash.")

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro persistido del journal debe ser un objeto.")
        journal_id = self._required_text(record.get("journal_id"), "journal_id")
        revision_id = self._required_text(record.get("revision_id"), "revision_id")
        symbol = self._required_text(record.get("symbol"), "symbol").upper()
        recorded_at = self._aware_iso(record.get("recorded_at"), "recorded_at")
        as_of = self._aware_iso(record.get("as_of"), "as_of")
        if recorded_at > as_of:
            raise ValueError("recorded_at no puede ser posterior a as_of.")
        prior = record.get("prior_snapshot_hash")
        if prior is not None:
            prior = self._sha256(prior, "prior_snapshot_hash")
        supplied_hash = self._sha256(record.get("snapshot_hash"), "snapshot_hash")
        snapshot = record.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("El registro persistido carece de snapshot válido.")
        if snapshot.get("journalId") != journal_id or snapshot.get("revisionId") != revision_id:
            raise ValueError("La identidad del snapshot persistido fue modificada.")
        if snapshot.get("symbol") != symbol:
            raise ValueError("El símbolo del snapshot persistido fue modificado.")
        if snapshot.get("priorSnapshotHash") != prior or snapshot.get("snapshotHash") != supplied_hash:
            raise ValueError("El fingerprint o lineage del snapshot persistido fue modificado.")
        if snapshot.get("advisoryStatus") != "no_advice":
            raise ValueError("El journal persistido debe mantener advisoryStatus=no_advice.")
        if snapshot.get("productionEligible") is not False or snapshot.get("isWeightingReady") is not False:
            raise ValueError("El journal persistido no puede habilitar producción ni ponderación.")
        policy = snapshot.get("policy")
        if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
            raise ValueError("El journal persistido no puede habilitar trading automático.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("El journal persistido no puede promover producción automáticamente.")

        references_raw = snapshot.get("references")
        if not isinstance(references_raw, list) or not references_raw:
            raise ValueError("El snapshot persistido perdió sus referencias PIT.")
        references: list[InvestmentJournalReferenceInput] = []
        for item in references_raw:
            if not isinstance(item, dict):
                raise ValueError("Una referencia persistida no es válida.")
            references.append(
                InvestmentJournalReferenceInput(
                    reference_id=self._required_text(item.get("referenceId"), "referenceId"),
                    kind=self._required_text(item.get("kind"), "kind"),
                    available_at=self._aware_iso(item.get("availableAt"), "availableAt"),
                    source=self._required_text(item.get("source"), "source"),
                    source_ref=self._required_text(item.get("sourceRef"), "sourceRef"),
                )
            )
        rebuilt = self._snapshot_service.freeze_snapshot(
            journal_id=journal_id,
            revision_id=revision_id,
            symbol=symbol,
            recorded_at=recorded_at,
            as_of=as_of,
            thesis=self._required_text(snapshot.get("thesis"), "thesis"),
            references=tuple(references),
            prior_snapshot_hash=prior,
        )
        if rebuilt.snapshot_hash != supplied_hash:
            raise ValueError("El contenido persistido no coincide con su snapshot_hash canónico.")
        if snapshot != rebuilt.to_api_dict():
            raise ValueError("El snapshot persistido no coincide con el contrato canónico completo.")
        return record

    def _validated_snapshot(self, snapshot: InvestmentJournalSnapshot) -> dict[str, Any]:
        if not isinstance(snapshot, InvestmentJournalSnapshot):
            raise ValueError("snapshot debe ser InvestmentJournalSnapshot.")
        payload = snapshot.to_api_dict()
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("Investment Journal debe mantener advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False or payload.get("isWeightingReady") is not False:
            raise ValueError("Investment Journal no puede habilitar producción ni ponderación.")
        # A SHA-shaped value is not proof of integrity. Rebuild from the
        # immutable fields and reject altered thesis, references or hash.
        rebuilt = self._snapshot_service.freeze_snapshot(
            journal_id=snapshot.journal_id,
            revision_id=snapshot.revision_id,
            symbol=snapshot.symbol,
            recorded_at=self._aware_iso(snapshot.recorded_at, "recorded_at"),
            as_of=self._aware_iso(snapshot.as_of, "as_of"),
            thesis=snapshot.thesis,
            references=snapshot.references,
            prior_snapshot_hash=snapshot.prior_snapshot_hash,
        )
        if rebuilt.snapshot_hash != snapshot.snapshot_hash:
            raise ValueError("El snapshot recibido no coincide con su snapshot_hash canónico.")
        if payload != rebuilt.to_api_dict():
            raise ValueError("El snapshot recibido no coincide con el contrato canónico completo.")
        return payload

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            snapshot = json.loads(str(row["snapshot_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("snapshot_json persistido no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "journal_id": str(row["journal_id"]),
            "revision_id": str(row["revision_id"]),
            "symbol": str(row["symbol"]),
            "recorded_at": str(row["recorded_at"]),
            "as_of": str(row["as_of"]),
            "prior_snapshot_hash": row["prior_snapshot_hash"],
            "snapshot_hash": str(row["snapshot_hash"]),
            "snapshot": snapshot,
            "created_at": str(row["created_at"]),
        }

    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal válido.")
        return text

    def _aware_iso(self, value: object, field: str) -> datetime:
        text = self._required_text(value, field)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser un datetime ISO válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed
