from __future__ import annotations

from pathlib import Path

from app.security.portfolio_owner_context import current_portfolio_owner_id


def owner_scoped_ledger_path(base_path: Path, *, owner_user_id: int | None = None) -> Path:
    """Resolve the physical event-ledger file for one authenticated owner.

    The public request path never accepts owner identity from payloads. Trusted
    callers may pass owner_user_id explicitly; otherwise the current authenticated
    portfolio owner context is mandatory. Legacy global ledger files are not read
    through this helper and therefore are never silently attributed to a user.
    """

    owner_id = current_portfolio_owner_id() if owner_user_id is None else owner_user_id
    if isinstance(owner_id, bool) or not isinstance(owner_id, int) or owner_id <= 0:
        raise ValueError("portfolio owner_user_id must be a positive integer")
    path = Path(base_path)
    filename = path.name
    if not filename:
        raise ValueError("portfolio event ledger path must include a filename")
    return path.parent / "owners" / str(owner_id) / filename


def purge_owner_scoped_ledger(base_path: Path, *, owner_user_id: int) -> bool:
    """Delete one closed owner's ledger without touching any other owner.

    Returns True when a ledger existed and was removed. Empty owner directories
    are removed best-effort; the shared owners directory is never removed here.
    """
    ledger_path = owner_scoped_ledger_path(base_path, owner_user_id=owner_user_id)
    try:
        ledger_path.unlink()
    except FileNotFoundError:
        return False
    try:
        ledger_path.parent.rmdir()
    except OSError:
        pass
    return True
