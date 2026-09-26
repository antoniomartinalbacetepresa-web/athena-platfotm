from __future__ import annotations

import base64
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.user_account_repository import UserAccountRepository
from app.repositories.user_portfolio_repository import UserPortfolioRepository


def _key(fill: bytes) -> str:
    return base64.urlsafe_b64encode(fill * 32).decode("ascii")


def _configure_key(monkeypatch: pytest.MonkeyPatch, *, version: int, key: str, previous=None) -> None:
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY_VERSION", str(version))
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", key)
    if previous:
        monkeypatch.setenv(
            "ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS",
            json.dumps({str(k): v for k, v in previous.items()}),
        )
    else:
        monkeypatch.delenv("ATHENA_PROFILE_ENCRYPTION_PREVIOUS_KEYS", raising=False)


def _owner(database: AthenaDatabase, email: str = "portfolio-rotation@example.com") -> int:
    account = UserAccountRepository(database).create(
        email=email,
        password_hash="test-hash-not-a-secret",
        display_name="Portfolio Rotation",
    )
    return int(account["id"])


def _stored_versions(database: AthenaDatabase, owner_id: int) -> list[int | None]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT average_purchase_price_key_version
            FROM athena_user_portfolio_positions
            WHERE owner_user_id = ?
            ORDER BY symbol, exchange, id
            """,
            (owner_id,),
        ).fetchall()
    return [
        None if row["average_purchase_price_key_version"] is None
        else int(row["average_purchase_price_key_version"])
        for row in rows
    ]


def test_cost_basis_rotation_allows_historical_key_retirement(tmp_path, monkeypatch) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    old_key = _key(b"a")
    new_key = _key(b"b")

    _configure_key(monkeypatch, version=1, key=old_key)
    owner_id = _owner(database)
    legacy = UserPortfolioRepository(database)
    legacy.upsert(
        owner_user_id=owner_id,
        symbol="AAPL",
        exchange="NASDAQ",
        quantity=3,
        average_purchase_price=171.25,
    )
    legacy.upsert(
        owner_user_id=owner_id,
        symbol="MSFT",
        exchange="NASDAQ",
        quantity=2,
        average_purchase_price=402.5,
    )
    legacy.upsert(
        owner_user_id=owner_id,
        symbol="BRK.B",
        exchange="NYSE",
        quantity=1,
        average_purchase_price=None,
    )
    assert _stored_versions(database, owner_id) == [1, None, 1]

    _configure_key(monkeypatch, version=2, key=new_key, previous={1: old_key})
    rotating = UserPortfolioRepository(database)
    assert rotating.reencrypt_all_average_purchase_prices_to_current_key() == 2
    assert rotating.reencrypt_all_average_purchase_prices_to_current_key() == 0
    assert _stored_versions(database, owner_id) == [2, None, 2]

    # The old key can now be removed without losing the encrypted cost basis.
    _configure_key(monkeypatch, version=2, key=new_key)
    reloaded = UserPortfolioRepository(database).list_for_owner(owner_id)
    by_symbol = {item["symbol"]: item for item in reloaded}
    assert by_symbol["AAPL"]["averagePurchasePrice"] == pytest.approx(171.25)
    assert by_symbol["MSFT"]["averagePurchasePrice"] == pytest.approx(402.5)
    assert by_symbol["BRK.B"]["averagePurchasePrice"] is None


def test_cost_basis_rotation_rolls_back_entire_batch_on_mid_migration_failure(
    tmp_path, monkeypatch
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    old_key = _key(b"c")
    new_key = _key(b"d")

    _configure_key(monkeypatch, version=1, key=old_key)
    owner_id = _owner(database, email="portfolio-rollback@example.com")
    legacy = UserPortfolioRepository(database)
    for symbol, price in (("AAPL", 150.0), ("MSFT", 350.0)):
        legacy.upsert(
            owner_user_id=owner_id,
            symbol=symbol,
            exchange="NASDAQ",
            quantity=1,
            average_purchase_price=price,
        )
    assert _stored_versions(database, owner_id) == [1, 1]

    _configure_key(monkeypatch, version=2, key=new_key, previous={1: old_key})
    rotating = UserPortfolioRepository(database)
    original_encrypt = rotating._encrypt_average_purchase_price
    calls = 0

    def fail_on_second_encrypt(**kwargs):
        nonlocal calls
        calls += 1
        encrypted = original_encrypt(**kwargs)
        if calls == 2:
            raise RuntimeError("injected rotation failure")
        return encrypted

    monkeypatch.setattr(rotating, "_encrypt_average_purchase_price", fail_on_second_encrypt)

    with pytest.raises(RuntimeError, match="injected rotation failure"):
        rotating.reencrypt_all_average_purchase_prices_to_current_key()

    # The first UPDATE happened before the injected failure; both rows remaining
    # at v1 proves the transaction rolled the partial migration back.
    assert calls == 2
    assert _stored_versions(database, owner_id) == [1, 1]

    # Legacy data is still readable with the historical key after rollback.
    rows = UserPortfolioRepository(database).list_for_owner(owner_id)
    by_symbol = {item["symbol"]: item["averagePurchasePrice"] for item in rows}
    assert by_symbol == {"AAPL": pytest.approx(150.0), "MSFT": pytest.approx(350.0)}


def test_cost_basis_rotation_fails_closed_when_historical_key_is_missing(
    tmp_path, monkeypatch
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    old_key = _key(b"e")
    new_key = _key(b"f")

    _configure_key(monkeypatch, version=1, key=old_key)
    owner_id = _owner(database, email="portfolio-missing-key@example.com")
    UserPortfolioRepository(database).upsert(
        owner_user_id=owner_id,
        symbol="AAPL",
        exchange="NASDAQ",
        quantity=1,
        average_purchase_price=199.0,
    )

    _configure_key(monkeypatch, version=2, key=new_key)
    with pytest.raises(RuntimeError, match="versión 1 no está disponible"):
        UserPortfolioRepository(database).reencrypt_all_average_purchase_prices_to_current_key()

    assert _stored_versions(database, owner_id) == [1]
