from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationAthenaSynthesisRepository:
    """Append-only persistence for one canonical ATHENA synthesis per research cycle."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_research_syntheses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cycle_hash TEXT NOT NULL UNIQUE,
                    radar_hash TEXT NOT NULL,
                    news_synthesis_hash TEXT,
                    synthesis_hash TEXT NOT NULL UNIQUE,
                    package_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_athena_research_synthesis_hash
                ON athena_research_syntheses(synthesis_hash);
                """
            )

    def append(
        self,
        *,
        cycle_hash: str,
        radar_hash: str,
        news_synthesis_hash: str | None,
        synthesis_payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        package = self.validate_package(
            cycle_hash=cycle_hash,
            radar_hash=radar_hash,
            news_synthesis_hash=news_synthesis_hash,
            synthesis_payload=synthesis_payload,
        )
        synthesis_hash = self._canonical_hash(package)
        serialized = json.dumps(
            package,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        created_at = datetime.now().astimezone().isoformat()

        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_research_syntheses WHERE cycle_hash = ?",
                (package["cycleHash"],),
            ).fetchone()
            if existing is not None:
                record = self.validate_record(self._row(existing))
                if record["synthesis_hash"] != synthesis_hash:
                    raise ValueError(
                        "El Research Cycle ya tiene una ATHENA synthesis distinta; "
                        "la selección retrospectiva de salidas está prohibida."
                    )
                return record

            connection.execute(
                """
                INSERT INTO athena_research_syntheses (
                    cycle_hash, radar_hash, news_synthesis_hash,
                    synthesis_hash, package_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    package["cycleHash"],
                    package["radarHash"],
                    package.get("newsSynthesisHash"),
                    synthesis_hash,
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_research_syntheses WHERE synthesis_hash = ?",
                (synthesis_hash,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_cycle_hash(self, *, cycle_hash: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(cycle_hash, "cycle_hash")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_research_syntheses WHERE cycle_hash = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("El Research Cycle no tiene ATHENA synthesis persistida.")
        return self.validate_record(self._row(row))

    def validate_package(
        self,
        *,
        cycle_hash: str,
        radar_hash: str,
        news_synthesis_hash: str | None,
        synthesis_payload: dict[str, Any],
    ) -> dict[str, Any]:
        cycle = self._sha256(cycle_hash, "cycle_hash")
        radar = self._sha256(radar_hash, "radar_hash")
        news = (
            self._sha256(news_synthesis_hash, "news_synthesis_hash")
            if news_synthesis_hash is not None
            else None
        )
        if not isinstance(synthesis_payload, dict):
            raise ValueError("synthesis_payload debe ser un objeto.")
        if synthesis_payload.get("status") != "validated_external_athena_synthesis":
            raise ValueError("ATHENA synthesis perdió su estado validado.")
        if synthesis_payload.get("mode") != "research_explanation_only":
            raise ValueError("ATHENA synthesis debe permanecer en modo research_explanation_only.")
        if synthesis_payload.get("cycleHash") != cycle:
            raise ValueError("ATHENA synthesis no coincide con cycleHash.")
        if synthesis_payload.get("radarHash") != radar:
            raise ValueError("ATHENA synthesis no coincide con radarHash.")
        if synthesis_payload.get("newsSynthesisHash") != news:
            if not (news is None and "newsSynthesisHash" not in synthesis_payload):
                raise ValueError("ATHENA synthesis no coincide con newsSynthesisHash.")
        for field in (
            "modelExecutionVerified",
            "productionEligible",
            "isWeightingReady",
            "recommendationInfluence",
            "automaticScoring",
            "automaticTrading",
            "automaticProductionPromotion",
        ):
            if synthesis_payload.get(field) is not False:
                raise ValueError(f"ATHENA synthesis debe mantener {field}=false.")
        if synthesis_payload.get("advisoryStatus") != "no_advice":
            raise ValueError("ATHENA synthesis debe mantener advisoryStatus=no_advice.")
        self._sha256(synthesis_payload.get("inputFingerprint"), "inputFingerprint")
        self._sha256(synthesis_payload.get("outputFingerprint"), "outputFingerprint")
        uncertainties = synthesis_payload.get("uncertainties")
        if not isinstance(uncertainties, list) or not uncertainties:
            raise ValueError("ATHENA synthesis debe conservar incertidumbres explícitas.")
        evidence_ids = synthesis_payload.get("evidenceIds")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise ValueError("ATHENA synthesis debe conservar evidenceIds explícitos.")
        if len(evidence_ids) != len(set(str(item) for item in evidence_ids)):
            raise ValueError("ATHENA synthesis no puede duplicar evidenceIds.")
        categories = synthesis_payload.get("coveredCategories")
        if not isinstance(categories, list) or not categories:
            raise ValueError("ATHENA synthesis debe conservar coveredCategories.")

        package = {
            "cycleHash": cycle,
            "radarHash": radar,
            **({"newsSynthesisHash": news} if news is not None else {}),
            "synthesis": synthesis_payload,
        }
        return package

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro ATHENA synthesis debe ser un objeto.")
        package = record.get("package")
        if not isinstance(package, dict):
            raise ValueError("ATHENA synthesis persistida carece de package válido.")
        validated = self.validate_package(
            cycle_hash=package.get("cycleHash"),
            radar_hash=package.get("radarHash"),
            news_synthesis_hash=package.get("newsSynthesisHash"),
            synthesis_payload=package.get("synthesis"),
        )
        expected_hash = self._canonical_hash(validated)
        if self._sha256(record.get("synthesis_hash"), "synthesis_hash") != expected_hash:
            raise ValueError("synthesis_hash no coincide con ATHENA synthesis persistida.")
        if record.get("cycle_hash") != validated["cycleHash"]:
            raise ValueError("cycle_hash persistido no coincide con ATHENA synthesis.")
        if record.get("radar_hash") != validated["radarHash"]:
            raise ValueError("radar_hash persistido no coincide con ATHENA synthesis.")
        if record.get("news_synthesis_hash") != validated.get("newsSynthesisHash"):
            raise ValueError("news_synthesis_hash persistido no coincide con ATHENA synthesis.")
        return record

    def _row(self, row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar ATHENA synthesis persistida.")
        try:
            package = json.loads(str(row["package_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("package_json de ATHENA synthesis no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "cycle_hash": str(row["cycle_hash"]),
            "radar_hash": str(row["radar_hash"]),
            "news_synthesis_hash": (
                str(row["news_synthesis_hash"])
                if row["news_synthesis_hash"] is not None
                else None
            ),
            "synthesis_hash": str(row["synthesis_hash"]),
            "package": package,
            "created_at": str(row["created_at"]),
        }

    def _canonical_hash(self, payload: object) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal válido.")
        return text
