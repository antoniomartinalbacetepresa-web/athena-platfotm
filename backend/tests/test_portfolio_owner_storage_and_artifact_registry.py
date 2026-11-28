from __future__ import annotations

from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.security.portfolio_artifact_ownership import PortfolioArtifactOwnershipRegistry
from app.security.portfolio_owner_context import portfolio_owner_scope
from app.security.portfolio_owner_storage import owner_scoped_ledger_path


def test_owner_scoped_ledger_path_isolates_accounts_and_never_uses_legacy_global_file(tmp_path: Path) -> None:
    legacy = tmp_path / "portfolio_event_ledger.jsonl"

    with portfolio_owner_scope(101):
        owner_a = owner_scoped_ledger_path(legacy)
    with portfolio_owner_scope(202):
        owner_b = owner_scoped_ledger_path(legacy)

    assert owner_a == tmp_path / "owners" / "101" / "portfolio_event_ledger.jsonl"
    assert owner_b == tmp_path / "owners" / "202" / "portfolio_event_ledger.jsonl"
    assert owner_a != owner_b
    assert owner_a != legacy
    assert owner_b != legacy


def test_keyed_artifact_registry_requires_explicit_owner_link(tmp_path: Path) -> None:
    registry = PortfolioArtifactOwnershipRegistry(
        AthenaDatabase(tmp_path / "ownership.db")
    )
    key = "a" * 64

    with portfolio_owner_scope(101):
        registry.link_current_owner(
            artifact_kind="state_reconciliation",
            artifact_key=key,
        )
        registry.require_current_owner(
            artifact_kind="state_reconciliation",
            artifact_key=key,
        )

    with portfolio_owner_scope(202):
        with pytest.raises(ValueError, match="not available"):
            registry.require_current_owner(
                artifact_kind="state_reconciliation",
                artifact_key=key,
            )


def test_identical_immutable_artifact_can_be_independently_linked_by_two_accounts(tmp_path: Path) -> None:
    registry = PortfolioArtifactOwnershipRegistry(
        AthenaDatabase(tmp_path / "shared.db")
    )
    key = "b" * 64

    with portfolio_owner_scope(101):
        registry.link_current_owner(
            artifact_kind="reconciled_weight",
            artifact_key=key,
        )

    with portfolio_owner_scope(202):
        with pytest.raises(ValueError, match="not available"):
            registry.require_current_owner(
                artifact_kind="reconciled_weight",
                artifact_key=key,
            )
        registry.link_current_owner(
            artifact_kind="reconciled_weight",
            artifact_key=key,
        )
        registry.require_current_owner(
            artifact_kind="reconciled_weight",
            artifact_key=key,
        )

    with portfolio_owner_scope(101):
        registry.require_current_owner(
            artifact_kind="reconciled_weight",
            artifact_key=key,
        )
