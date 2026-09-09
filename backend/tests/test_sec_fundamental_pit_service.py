from datetime import datetime, timezone
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.sec_fundamental_pit_repository import SecFundamentalPitRepository
from app.services.sec_fundamental_pit_service import SecFundamentalPitService


UTC = timezone.utc
AS_OF = datetime(2026, 3, 1, tzinfo=UTC)
CIK = "320193"
ACC_OLD = "0000320193-25-000079"
ACC_NEW = "0000320193-26-000001"


def company_facts() -> dict[str, object]:
    return {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2025-09-27",
                                "val": 359241000000,
                                "accn": ACC_OLD,
                                "fy": 2025,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-10-31",
                            },
                            {
                                "end": "2025-09-27",
                                "val": 360000000000,
                                "accn": ACC_NEW,
                                "fy": 2025,
                                "fp": "FY",
                                "form": "10-K/A",
                                "filed": "2026-04-01",
                            },
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2024-09-29",
                                "end": "2025-09-27",
                                "val": 416161000000,
                                "accn": ACC_OLD,
                                "fy": 2025,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-10-31",
                            }
                        ]
                    }
                },
            }
        },
    }


def submissions() -> dict[str, object]:
    return {
        "filings": {
            "recent": {
                "accessionNumber": [ACC_OLD, ACC_NEW],
                "acceptanceDateTime": [
                    "2025-10-31T17:00:00Z",
                    "2026-04-01T18:00:00Z",
                ],
            }
        }
    }


def test_normalize_uses_acceptance_time_and_excludes_future_revision() -> None:
    facts = SecFundamentalPitService().normalize(
        cik=CIK,
        company_facts=company_facts(),
        submissions=submissions(),
        as_of=AS_OF,
    )

    assert len(facts) == 2
    assets = next(item for item in facts if item.concept == "Assets")
    assert assets.value == 359241000000.0
    assert assets.available_at == datetime(2025, 10, 31, 17, tzinfo=UTC)
    assert assets.accession_number == ACC_OLD
    payload = assets.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["lookahead"] == "forbidden"
    assert len(assets.fact_key) == 64


def test_normalize_preserves_revision_as_new_vintage_after_it_is_known() -> None:
    facts = SecFundamentalPitService().normalize(
        cik=CIK,
        company_facts=company_facts(),
        submissions=submissions(),
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    assets = [item for item in facts if item.concept == "Assets"]
    assert len(assets) == 2
    assert {item.accession_number for item in assets} == {ACC_OLD, ACC_NEW}
    assert len({item.fact_key for item in assets}) == 2


def test_normalize_rejects_nonfinite_and_temporally_impossible_facts() -> None:
    payload = company_facts()
    payload["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = float("nan")  # type: ignore[index]
    with pytest.raises(ValueError, match="finito"):
        SecFundamentalPitService().normalize(
            cik=CIK,
            company_facts=payload,
            submissions=submissions(),
            as_of=AS_OF,
        )

    payload = company_facts()
    payload["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["end"] = "2025-11-01"  # type: ignore[index]
    with pytest.raises(ValueError, match="después de su filing date"):
        SecFundamentalPitService().normalize(
            cik=CIK,
            company_facts=payload,
            submissions=submissions(),
            as_of=AS_OF,
        )


def test_repository_is_idempotent_filters_by_asof_and_detects_tampering(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = SecFundamentalPitRepository(database)
    fact = SecFundamentalPitService().normalize(
        cik=CIK,
        company_facts=company_facts(),
        submissions=submissions(),
        as_of=AS_OF,
    )[0]

    first = repository.append(fact)
    second = repository.append(fact)
    assert first["id"] == second["id"]
    assert repository.get_known_at_or_before(
        cik=CIK,
        as_of=datetime(2025, 10, 31, 16, tzinfo=UTC),
    ) == []
    known = repository.get_known_at_or_before(cik=CIK, as_of=AS_OF)
    assert len(known) == 1

    with database.connect() as connection:
        artifact = dict(known[0]["artifact"])
        artifact["cik"] = "0000000001"
        connection.execute(
            "UPDATE sec_fundamental_pit_facts SET artifact_json = ? WHERE fact_key = ?",
            (json.dumps(artifact), fact.fact_key),
        )
    with pytest.raises(ValueError, match="manipulado"):
        repository.get_known_at_or_before(cik=CIK, as_of=AS_OF)
