from pathlib import Path

from app.security.portfolio_owner_storage import owner_scoped_ledger_path, purge_owner_scoped_ledger


def test_purge_owner_scoped_ledger_removes_only_target_owner(tmp_path: Path) -> None:
    base = tmp_path / "portfolio_event_ledger.jsonl"
    target = owner_scoped_ledger_path(base, owner_user_id=41)
    other = owner_scoped_ledger_path(base, owner_user_id=42)
    target.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    target.write_text("target\n", encoding="utf-8")
    other.write_text("other\n", encoding="utf-8")

    assert purge_owner_scoped_ledger(base, owner_user_id=41) is True
    assert not target.exists()
    assert other.exists()
    assert purge_owner_scoped_ledger(base, owner_user_id=41) is False
