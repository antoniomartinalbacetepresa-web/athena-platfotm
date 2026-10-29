from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


TEST_SECRET = "athena-test-secret-that-is-at-least-32-bytes-long"


def _configure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "ATHENA_DATABASE_PATH",
        str(tmp_path / "athena_user_portfolio.db"),
    )
    monkeypatch.setenv(
        "ATHENA_PORTFOLIO_EVENT_LEDGER_PATH",
        str(tmp_path / "portfolio_event_ledger.jsonl"),
    )
    monkeypatch.setenv("ATHENA_AUTH_SECRET", TEST_SECRET)


def _register_and_token(client: TestClient, *, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "displayName": email.split("@", 1)[0],
        },
    )
    assert response.status_code == 201, response.text

    response = client.post(
        "/api/v1/auth/token",
        data={
            "username": email,
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _append_trade(
    client: TestClient,
    *,
    token: str,
    portfolio_id: str,
    source_ref: str,
    occurred_at: str,
    available_at: str,
    as_of: str,
    instrument_id: str,
) -> dict:
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-event-ledger/events",
        headers=_headers(token),
        json={
            "portfolioId": portfolio_id,
            "eventType": "trade_execution",
            "occurredAt": occurred_at,
            "availableAt": available_at,
            "currency": "EUR",
            "amount": -1000.0,
            "instrumentId": instrument_id,
            "quantity": 10.0,
            "source": "user_declared_execution",
            "sourceRef": source_ref,
            "asOf": as_of,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["record"]


def test_personal_portfolio_requires_authentication(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/v1/user/portfolio")
    assert response.status_code == 401


def test_personal_portfolio_history_requires_authentication(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/user/portfolio/history",
            params={"portfolioId": "primary", "asOf": "2026-09-12T05:00:00Z"},
        )
    assert response.status_code == 401


def test_users_can_only_see_and_delete_their_own_positions(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="owner-a@example.com")
        token_b = _register_and_token(client, email="owner-b@example.com")

        created = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(token_a),
            json={"symbol": " aapl ", "exchange": " nasdaq ", "quantity": 12.5},
        )
        assert created.status_code == 200, created.text
        position = created.json()["data"]
        position_id = int(position["id"])
        assert position["symbol"] == "AAPL"
        assert position["exchange"] == "NASDAQ"
        assert position["quantity"] == 12.5
        assert "ownerUserId" not in position

        own = client.get("/api/v1/user/portfolio", headers=_headers(token_a))
        assert own.status_code == 200
        assert own.json()["data"]["positionCount"] == 1
        assert own.json()["data"]["positions"][0]["id"] == position_id
        assert own.json()["policy"]["ownerDerivedFromAuthenticatedToken"] is True
        assert own.json()["policy"]["productionEligible"] is False
        assert own.json()["policy"]["storageEncrypted"] is False

        foreign = client.get("/api/v1/user/portfolio", headers=_headers(token_b))
        assert foreign.status_code == 200
        assert foreign.json()["data"]["positions"] == []

        foreign_delete = client.delete(
            f"/api/v1/user/portfolio/positions/{position_id}",
            headers=_headers(token_b),
        )
        assert foreign_delete.status_code == 404

        still_owned = client.get("/api/v1/user/portfolio", headers=_headers(token_a))
        assert still_owned.json()["data"]["positionCount"] == 1

        own_delete = client.delete(
            f"/api/v1/user/portfolio/positions/{position_id}",
            headers=_headers(token_a),
        )
        assert own_delete.status_code == 204

        empty = client.get("/api/v1/user/portfolio", headers=_headers(token_a))
        assert empty.json()["data"]["positions"] == []


def test_personal_history_is_owner_scoped_and_point_in_time_filtered(
    monkeypatch,
    tmp_path,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="history-a@example.com")
        token_b = _register_and_token(client, email="history-b@example.com")

        a_early = _append_trade(
            client,
            token=token_a,
            portfolio_id="primary",
            source_ref="broker-a-early",
            occurred_at="2026-09-10T10:00:00Z",
            available_at="2026-09-10T10:01:00Z",
            as_of="2026-09-12T05:00:00Z",
            instrument_id="AAPL:XNAS",
        )
        a_late = _append_trade(
            client,
            token=token_a,
            portfolio_id="primary",
            source_ref="broker-a-late",
            occurred_at="2026-09-11T10:00:00Z",
            available_at="2026-09-11T10:01:00Z",
            as_of="2026-09-12T05:00:00Z",
            instrument_id="MSFT:XNAS",
        )
        b_record = _append_trade(
            client,
            token=token_b,
            portfolio_id="primary",
            source_ref="broker-b-private",
            occurred_at="2026-09-09T10:00:00Z",
            available_at="2026-09-09T10:01:00Z",
            as_of="2026-09-12T05:00:00Z",
            instrument_id="NVDA:XNAS",
        )

        history_a = client.get(
            "/api/v1/user/portfolio/history",
            headers=_headers(token_a),
            params={"portfolioId": "primary", "asOf": "2026-09-12T05:00:00Z"},
        )
        assert history_a.status_code == 200, history_a.text
        payload_a = history_a.json()
        events_a = payload_a["data"]["events"]
        assert payload_a["data"]["eventCount"] == 2
        assert [item["eventKey"] for item in events_a] == [
            a_late["event"]["eventKey"],
            a_early["event"]["eventKey"],
        ]
        assert b_record["event"]["eventKey"] not in {
            item["eventKey"] for item in events_a
        }
        assert payload_a["policy"]["ownerDerivedFromAuthenticatedToken"] is True
        assert payload_a["policy"]["clientSuppliedOwnerAccepted"] is False
        assert payload_a["policy"]["sourceOfTruth"] == (
            "owner_scoped_append_only_event_ledger"
        )
        assert payload_a["policy"]["automaticTrading"] is False
        assert payload_a["policy"]["orderPlacement"] == "forbidden"

        pit_history_a = client.get(
            "/api/v1/user/portfolio/history",
            headers=_headers(token_a),
            params={"portfolioId": "primary", "asOf": "2026-09-11T09:00:00Z"},
        )
        assert pit_history_a.status_code == 200, pit_history_a.text
        pit_events = pit_history_a.json()["data"]["events"]
        assert [item["eventKey"] for item in pit_events] == [
            a_early["event"]["eventKey"]
        ]

        history_b = client.get(
            "/api/v1/user/portfolio/history",
            headers=_headers(token_b),
            params={"portfolioId": "primary", "asOf": "2026-09-12T05:00:00Z"},
        )
        assert history_b.status_code == 200, history_b.text
        assert [item["eventKey"] for item in history_b.json()["data"]["events"]] == [
            b_record["event"]["eventKey"]
        ]


def test_client_cannot_supply_portfolio_owner(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _register_and_token(client, email="owner@example.com")
        response = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(token),
            json={
                "symbol": "MSFT",
                "exchange": "NASDAQ",
                "quantity": 3,
                "ownerUserId": 999999,
            },
        )
    assert response.status_code == 422


def test_upsert_updates_only_the_authenticated_owners_matching_position(
    monkeypatch,
    tmp_path,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="upsert-a@example.com")
        token_b = _register_and_token(client, email="upsert-b@example.com")

        for token, quantity in ((token_a, 1), (token_b, 9)):
            response = client.put(
                "/api/v1/user/portfolio/positions",
                headers=_headers(token),
                json={"symbol": "MSFT", "exchange": "NASDAQ", "quantity": quantity},
            )
            assert response.status_code == 200

        response = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(token_a),
            json={"symbol": "MSFT", "exchange": "NASDAQ", "quantity": 4},
        )
        assert response.status_code == 200

        portfolio_a = client.get("/api/v1/user/portfolio", headers=_headers(token_a)).json()
        portfolio_b = client.get("/api/v1/user/portfolio", headers=_headers(token_b)).json()
        assert portfolio_a["data"]["positions"][0]["quantity"] == 4.0
        assert portfolio_b["data"]["positions"][0]["quantity"] == 9.0


def test_personal_history_cursor_paginates_stable_owner_pit_snapshot(
    monkeypatch, tmp_path,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="cursor-a@example.com")
        token_b = _register_and_token(client, email="cursor-b@example.com")
        cutoff = "2026-09-15T00:00:00Z"
        recorded = {}
        # Append order deliberately differs from chronological order.
        for hour in (10, 13, 11, 12):
            recorded[hour] = _append_trade(
                client, token=token_a, portfolio_id="primary",
                source_ref=f"cursor-a-{hour}",
                occurred_at=f"2026-09-10T{hour:02d}:00:00Z",
                available_at=f"2026-09-10T{hour:02d}:01:00Z",
                as_of=cutoff, instrument_id="AAPL:XNAS",
            )
        _append_trade(
            client, token=token_b, portfolio_id="primary",
            source_ref="cursor-b-private",
            occurred_at="2026-09-10T09:00:00Z",
            available_at="2026-09-10T09:01:00Z",
            as_of=cutoff, instrument_id="MSFT:XNAS",
        )
        base = {"portfolioId": "primary", "asOf": cutoff, "limit": 2}
        first = client.get(
            "/api/v1/user/portfolio/history", headers=_headers(token_a), params=base
        )
        assert first.status_code == 200, first.text
        first_data = first.json()["data"]
        assert [e["sequence"] for e in first_data["events"]] == [
            recorded[13]["sequence"], recorded[12]["sequence"],
        ]
        assert first_data["hasMore"] is True
        cursor = first_data["nextCursor"]
        assert isinstance(cursor, str) and len(cursor) < 128

        # A later append with old economic dates cannot enter the frozen page set.
        late_append = _append_trade(
            client, token=token_a, portfolio_id="primary",
            source_ref="cursor-a-backdated",
            occurred_at="2026-09-10T09:30:00Z",
            available_at="2026-09-10T09:31:00Z",
            as_of=cutoff, instrument_id="NVDA:XNAS",
        )
        second = client.get(
            "/api/v1/user/portfolio/history", headers=_headers(token_a),
            params={**base, "cursor": cursor},
        )
        assert second.status_code == 200, second.text
        second_data = second.json()["data"]
        assert [e["sequence"] for e in second_data["events"]] == [
            recorded[11]["sequence"], recorded[10]["sequence"],
        ]
        assert late_append["sequence"] not in {
            e["sequence"] for e in second_data["events"]
        }
        assert second_data["hasMore"] is False
        assert second_data["nextCursor"] is None

        # A cursor cannot cross owner, portfolio or PIT-cutoff boundaries.
        for token, params in (
            (token_b, {**base, "cursor": cursor}),
            (token_a, {**base, "portfolioId": "other", "cursor": cursor}),
            (token_a, {**base, "asOf": "2026-09-16T00:00:00Z", "cursor": cursor}),
            (token_a, {**base, "cursor": "not-a-cursor"}),
        ):
            rejected = client.get(
                "/api/v1/user/portfolio/history",
                headers=_headers(token), params=params,
            )
            assert rejected.status_code == 400, rejected.text
