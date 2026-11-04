from fastapi.testclient import TestClient

import app.api.sec_fundamental_pit as api_module
from app.main import app


client = TestClient(app)


class FakeEdgar:
    @staticmethod
    def normalize_cik(cik: str | int) -> str:
        digits = "".join(character for character in str(cik) if character.isdigit())
        if not digits or len(digits) > 10:
            raise ValueError("CIK inválido.")
        return digits.zfill(10)

    def get_company_facts(self, cik: str) -> dict[str, object]:
        return {
            "cik": 320193,
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {
                                    "end": "2025-09-27",
                                    "val": 100.0,
                                    "accn": "0000320193-25-000079",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2025-10-31",
                                }
                            ]
                        }
                    }
                }
            },
        }

    def get_submissions(self, cik: str) -> dict[str, object]:
        return {
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-25-000079"],
                    "acceptanceDateTime": ["2025-10-31T17:00:00Z"],
                }
            }
        }

    def close(self) -> None:
        return None


class FakeRepository:
    appended: list[object] = []

    def append(self, fact: object) -> dict[str, object]:
        self.appended.append(fact)
        return {"id": len(self.appended)}


def test_sec_fundamental_pit_import_is_passive_and_pit(monkeypatch) -> None:
    FakeRepository.appended = []
    monkeypatch.setattr(api_module, "SecEdgarService", FakeEdgar)
    monkeypatch.setattr(api_module, "SecFundamentalPitRepository", FakeRepository)

    response = client.post(
        "/api/v1/sec/fundamentals/pit-import",
        params={"cik": "320193", "asOf": "2026-03-01T00:00:00Z"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["imported"] == 1
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["lookahead"] == "forbidden"
    assert data["policy"]["secrets"] == "none_required"
    assert len(data["factKeys"][0]) == 64
    assert len(FakeRepository.appended) == 1


def test_sec_fundamental_pit_import_rejects_naive_asof_before_fetch(monkeypatch) -> None:
    calls = []

    class ShouldNotFetch(FakeEdgar):
        def get_company_facts(self, cik: str) -> dict[str, object]:
            calls.append(cik)
            return super().get_company_facts(cik)

    monkeypatch.setattr(api_module, "SecEdgarService", ShouldNotFetch)
    response = client.post(
        "/api/v1/sec/fundamentals/pit-import",
        params={"cik": "320193", "asOf": "2026-03-01T00:00:00"},
    )
    assert response.status_code == 400
    assert calls == []
