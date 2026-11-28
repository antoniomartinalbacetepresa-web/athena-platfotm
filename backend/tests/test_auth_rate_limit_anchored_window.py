from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.repositories.auth_security_repository import AuthSecurityRepository


def test_login_limit_survives_utc_bucket_rollover_and_process_recreation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "auth-rate.db"))
    repository = AuthSecurityRepository()
    # Start immediately before a UTC 5-minute boundary. Eight attempts
    # crossing that boundary must not grant eight more attempts.
    started = datetime(2026, 10, 25, 12, 4, 59, 900000, tzinfo=timezone.utc)
    for attempt in range(8):
        result = repository.consume_login_attempt(
            key="auth-login:one-owner",
            window_started_at=started + timedelta(milliseconds=50 * attempt),
            window_seconds=300,
            limit=8,
        )
        assert result["allowed"] is True
        assert result["attempts"] == attempt + 1
        assert result["windowStartedAt"] == started.isoformat()

    # A second repository instance must observe the persisted limit.
    another_process = AuthSecurityRepository()
    blocked = another_process.consume_login_attempt(
        key="auth-login:one-owner",
        window_started_at=started + timedelta(seconds=2),
        window_seconds=300,
        limit=8,
    )
    assert blocked["allowed"] is False
    assert blocked["attempts"] == 9
    assert blocked["remaining"] == 0
    assert blocked["windowStartedAt"] == started.isoformat()

    # Other identities are isolated and a full window really expires.
    unrelated = another_process.consume_login_attempt(
        key="auth-login:other-owner",
        window_started_at=started + timedelta(seconds=2),
        window_seconds=300,
        limit=8,
    )
    assert unrelated["allowed"] is True

    renewed = another_process.consume_login_attempt(
        key="auth-login:one-owner",
        window_started_at=started + timedelta(seconds=300),
        window_seconds=300,
        limit=8,
    )
    assert renewed["allowed"] is True
    assert renewed["attempts"] == 1
    assert renewed["windowStartedAt"] == (started + timedelta(seconds=300)).isoformat()


def test_successful_auth_reset_clears_anchored_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "auth-rate.db"))
    repository = AuthSecurityRepository()
    start = datetime(2026, 10, 25, 12, 4, 59, tzinfo=timezone.utc)
    for attempt in range(2):
        result = repository.consume_login_attempt(
            key="auth-login:owner",
            window_started_at=start + timedelta(seconds=attempt),
            window_seconds=300,
            limit=2,
        )
        assert result["allowed"] is True

    assert repository.consume_login_attempt(
        key="auth-login:owner",
        window_started_at=start + timedelta(seconds=2),
        window_seconds=300,
        limit=2,
    )["allowed"] is False

    repository.clear_login_attempts(key="auth-login:owner")
    cleared = repository.consume_login_attempt(
        key="auth-login:owner",
        window_started_at=start + timedelta(seconds=3),
        window_seconds=300,
        limit=2,
    )
    assert cleared["allowed"] is True
    assert cleared["attempts"] == 1

    with pytest.raises(ValueError):
        repository.consume_login_attempt(
            key="auth-login:owner",
            window_started_at=start,
            window_seconds=0,
            limit=2,
        )
