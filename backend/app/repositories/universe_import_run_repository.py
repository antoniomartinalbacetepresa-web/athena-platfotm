from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class UniverseImportRunRepository:
    def __init__(
        self,
        database: AthenaDatabase | None = None,
    ) -> None:
        self._database = (
            database
            if database is not None
            else AthenaDatabase()
        )

    def start_run(
        self,
        source_id: str,
        started_at: str | None = None,
    ) -> int:
        normalized_source_id = (
            self._required_text(
                source_id,
                "source_id",
            ).lower()
        )

        effective_started_at = (
            self._optional_text(
                started_at
            )
            or self._now()
        )

        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO universe_import_runs (
                    source_id,
                    status,
                    received,
                    accepted,
                    rejected,
                    created_or_updated,
                    inserted,
                    updated,
                    unchanged,
                    deactivated,
                    reconciliation_applied,
                    started_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    normalized_source_id,
                    "running",
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    effective_started_at,
                ),
            )

            run_id = cursor.lastrowid

        if run_id is None:
            raise RuntimeError(
                "No se pudo crear la ejecución de importación."
            )

        return int(run_id)

    def mark_succeeded(
        self,
        run_id: int,
        *,
        received: int,
        accepted: int,
        rejected: int,
        created_or_updated: int | None = None,
        inserted: int | None = None,
        updated: int | None = None,
        unchanged: int | None = None,
        deactivated: int = 0,
        reconciliation_applied: bool = False,
        completed_at: str | None = None,
    ) -> None:
        normalized_run_id = self._positive_int(
            run_id,
            "run_id",
        )

        normalized_received = self._non_negative_int(
            received,
            "received",
        )

        normalized_accepted = self._non_negative_int(
            accepted,
            "accepted",
        )

        normalized_rejected = self._non_negative_int(
            rejected,
            "rejected",
        )

        if (
            normalized_accepted
            + normalized_rejected
            > normalized_received
        ):
            raise ValueError(
                "accepted + rejected no puede superar received."
            )

        (
            normalized_created_or_updated,
            normalized_inserted,
            normalized_updated,
            normalized_unchanged,
        ) = self._normalize_change_statistics(
            accepted=normalized_accepted,
            created_or_updated=created_or_updated,
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
        )

        normalized_deactivated = (
            self._non_negative_int(
                deactivated,
                "deactivated",
            )
        )

        normalized_reconciliation_applied = (
            self._boolean_flag(
                reconciliation_applied,
                "reconciliation_applied",
            )
        )

        if (
            normalized_deactivated > 0
            and not normalized_reconciliation_applied
        ):
            raise ValueError(
                "deactivated debe ser cero cuando "
                "reconciliation_applied es False."
            )

        effective_completed_at = (
            self._optional_text(
                completed_at
            )
            or self._now()
        )

        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE universe_import_runs
                SET
                    status = 'succeeded',
                    received = ?,
                    accepted = ?,
                    rejected = ?,
                    created_or_updated = ?,
                    inserted = ?,
                    updated = ?,
                    unchanged = ?,
                    deactivated = ?,
                    reconciliation_applied = ?,
                    completed_at = ?,
                    error_message = NULL
                WHERE id = ?
                  AND status = 'running'
                """,
                (
                    normalized_received,
                    normalized_accepted,
                    normalized_rejected,
                    normalized_created_or_updated,
                    normalized_inserted,
                    normalized_updated,
                    normalized_unchanged,
                    normalized_deactivated,
                    (
                        1
                        if normalized_reconciliation_applied
                        else 0
                    ),
                    effective_completed_at,
                    normalized_run_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "La ejecución no existe o ya está finalizada."
                )

    def mark_failed(
        self,
        run_id: int,
        *,
        error_message: str,
        received: int = 0,
        accepted: int = 0,
        rejected: int = 0,
        created_or_updated: int = 0,
        completed_at: str | None = None,
    ) -> None:
        normalized_run_id = self._positive_int(
            run_id,
            "run_id",
        )

        normalized_error_message = (
            self._required_text(
                error_message,
                "error_message",
            )
        )

        normalized_received = self._non_negative_int(
            received,
            "received",
        )

        normalized_accepted = self._non_negative_int(
            accepted,
            "accepted",
        )

        normalized_rejected = self._non_negative_int(
            rejected,
            "rejected",
        )

        normalized_created_or_updated = (
            self._non_negative_int(
                created_or_updated,
                "created_or_updated",
            )
        )

        if (
            normalized_accepted
            + normalized_rejected
            > normalized_received
        ):
            raise ValueError(
                "accepted + rejected no puede superar received."
            )

        if (
            normalized_created_or_updated
            > normalized_accepted
        ):
            raise ValueError(
                "created_or_updated no puede superar accepted."
            )

        effective_completed_at = (
            self._optional_text(
                completed_at
            )
            or self._now()
        )

        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE universe_import_runs
                SET
                    status = 'failed',
                    received = ?,
                    accepted = ?,
                    rejected = ?,
                    created_or_updated = ?,
                    inserted = NULL,
                    updated = NULL,
                    unchanged = NULL,
                    deactivated = NULL,
                    reconciliation_applied = NULL,
                    completed_at = ?,
                    error_message = ?
                WHERE id = ?
                  AND status = 'running'
                """,
                (
                    normalized_received,
                    normalized_accepted,
                    normalized_rejected,
                    normalized_created_or_updated,
                    effective_completed_at,
                    normalized_error_message,
                    normalized_run_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "La ejecución no existe o ya está finalizada."
                )

    def get_by_id(
        self,
        run_id: int,
    ) -> dict[str, Any] | None:
        normalized_run_id = self._positive_int(
            run_id,
            "run_id",
        )

        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    source_id,
                    status,
                    received,
                    accepted,
                    rejected,
                    created_or_updated,
                    inserted,
                    updated,
                    unchanged,
                    deactivated,
                    reconciliation_applied,
                    started_at,
                    completed_at,
                    error_message,
                    created_at
                FROM universe_import_runs
                WHERE id = ?
                """,
                (
                    normalized_run_id,
                ),
            ).fetchone()

        if row is None:
            return None

        return {
            key: row[key]
            for key in row.keys()
        }

    def latest_for_source(
        self,
        source_id: str,
    ) -> dict[str, Any] | None:
        normalized_source_id = (
            self._required_text(
                source_id,
                "source_id",
            ).lower()
        )

        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    source_id,
                    status,
                    received,
                    accepted,
                    rejected,
                    created_or_updated,
                    inserted,
                    updated,
                    unchanged,
                    deactivated,
                    reconciliation_applied,
                    started_at,
                    completed_at,
                    error_message,
                    created_at
                FROM universe_import_runs
                WHERE source_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    normalized_source_id,
                ),
            ).fetchone()

        if row is None:
            return None

        return {
            key: row[key]
            for key in row.keys()
        }

    def _normalize_change_statistics(
        self,
        *,
        accepted: int,
        created_or_updated: int | None,
        inserted: int | None,
        updated: int | None,
        unchanged: int | None,
    ) -> tuple[
        int,
        int | None,
        int | None,
        int | None,
    ]:
        detailed_values = (
            inserted,
            updated,
            unchanged,
        )

        has_any_detailed_value = any(
            value is not None
            for value in detailed_values
        )

        has_all_detailed_values = all(
            value is not None
            for value in detailed_values
        )

        if (
            has_any_detailed_value
            and not has_all_detailed_values
        ):
            raise ValueError(
                "inserted, updated y unchanged "
                "deben proporcionarse juntos."
            )

        if has_all_detailed_values:
            normalized_inserted = (
                self._non_negative_int(
                    inserted,
                    "inserted",
                )
            )

            normalized_updated = (
                self._non_negative_int(
                    updated,
                    "updated",
                )
            )

            normalized_unchanged = (
                self._non_negative_int(
                    unchanged,
                    "unchanged",
                )
            )

            if (
                normalized_inserted
                + normalized_updated
                + normalized_unchanged
                != accepted
            ):
                raise ValueError(
                    "inserted + updated + unchanged "
                    "debe ser igual a accepted."
                )

            calculated_created_or_updated = (
                normalized_inserted
                + normalized_updated
            )

            if created_or_updated is not None:
                normalized_explicit_total = (
                    self._non_negative_int(
                        created_or_updated,
                        "created_or_updated",
                    )
                )

                if (
                    normalized_explicit_total
                    != calculated_created_or_updated
                ):
                    raise ValueError(
                        "created_or_updated debe ser igual "
                        "a inserted + updated."
                    )

            return (
                calculated_created_or_updated,
                normalized_inserted,
                normalized_updated,
                normalized_unchanged,
            )

        normalized_created_or_updated = (
            self._non_negative_int(
                (
                    0
                    if created_or_updated is None
                    else created_or_updated
                ),
                "created_or_updated",
            )
        )

        if (
            normalized_created_or_updated
            > accepted
        ):
            raise ValueError(
                "created_or_updated no puede superar accepted."
            )

        return (
            normalized_created_or_updated,
            None,
            None,
            None,
        )

    def _required_text(
        self,
        value: Any,
        field_name: str,
    ) -> str:
        if value is None:
            raise ValueError(
                f"{field_name} es obligatorio."
            )

        normalized = str(
            value
        ).strip()

        if not normalized:
            raise ValueError(
                f"{field_name} es obligatorio."
            )

        return normalized

    def _optional_text(
        self,
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        normalized = str(
            value
        ).strip()

        if not normalized:
            return None

        return normalized

    def _positive_int(
        self,
        value: Any,
        field_name: str,
    ) -> int:
        normalized = int(
            value
        )

        if normalized <= 0:
            raise ValueError(
                f"{field_name} debe ser mayor que cero."
            )

        return normalized

    def _non_negative_int(
        self,
        value: Any,
        field_name: str,
    ) -> int:
        normalized = int(
            value
        )

        if normalized < 0:
            raise ValueError(
                f"{field_name} no puede ser negativo."
            )

        return normalized

    def _boolean_flag(
        self,
        value: Any,
        field_name: str,
    ) -> bool:
        if isinstance(
            value,
            bool,
        ):
            return value

        if isinstance(
            value,
            int,
        ) and value in (
            0,
            1,
        ):
            return bool(
                value
            )

        raise ValueError(
            f"{field_name} debe ser booleano."
        )

    def _now(self) -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()
