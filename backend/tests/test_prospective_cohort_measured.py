"""Synthetic regressions only: no operational OOS claim."""
from datetime import timedelta
import json

import pytest

from app.repositories.recommendation_research_forecast_error_repository import (
    RecommendationResearchForecastErrorRepository,
)
from scripts.prospective_cohort import build_parser, run
from test_recommendation_research_prospective_cohort import setup_cohort


def test_measured_reports_matured_missing_without_supplied_hashes(context, tmp_path):
    service, ref, _ = setup_cohort(context, tmp_path)
    cohort = service.register(cohort_id="measured-empty", specification_hashes=[ref])
    spec = service._specifications.get_by_hash(specification_hash=ref)["artifact"]
    cutoff = service._time(spec["periodEnd"]) + timedelta(days=1)
    report = service.measured_coverage(cohort_id="measured-empty", as_of=cutoff)
    assert report["cohortHash"] == cohort["cohortHash"]
    assert report["selectedCount"] == report["maturedCount"] == 1
    assert report["measuredErrorCount"] == 0
    assert report["missingMaturedSpecificationHashes"] == [ref]
    assert report["errorStorePresent"] is False
    assert report["outcomeEvidenceVerified"] is False
    assert report["productionEligible"] is False
    assert report["automaticTrading"] is False


def test_measured_rejects_tampered_persisted_error(context, tmp_path):
    service, ref, _ = setup_cohort(context, tmp_path)
    service.register(cohort_id="measured-corrupt", specification_hashes=[ref])
    spec = service._specifications.get_by_hash(specification_hash=ref)["artifact"]
    cutoff = service._time(spec["periodEnd"]) + timedelta(days=1)
    RecommendationResearchForecastErrorRepository(service._database).initialize()
    with service._database.connect() as connection:
        connection.execute(
            """INSERT INTO athena_research_forecast_errors
            (error_hash, specification_hash, outcome_hash, cycle_hash,
             instrument_id, symbol, horizon_seconds, artifact_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("a" * 64, ref, "b" * 64, spec["cycleHash"],
             spec["instrumentId"], spec["symbol"], spec["horizonSeconds"],
             json.dumps({}), cutoff.isoformat()),
        )
    with pytest.raises(ValueError):
        service.measured_coverage(cohort_id="measured-corrupt", as_of=cutoff)


def test_measured_does_not_count_unmatured_period(context, tmp_path):
    service, ref, _ = setup_cohort(context, tmp_path)
    cohort = service.register(cohort_id="measured-pending", specification_hashes=[ref])
    report = service.measured_coverage(
        cohort_id="measured-pending", as_of=service._time(cohort["sealedAt"])
    )
    assert report["maturedCount"] == 0
    assert report["notYetDueCount"] == 1
    assert report["membershipComplete"] is False


def test_measured_cli_requires_timezone_and_checks_pin():
    class Ledger:
        def get(self, **kwargs):
            return {"cohortHash": "a" * 64}
        def measured_coverage(self, **kwargs):
            return {"cohortHash": "a" * 64, "asOf": kwargs["as_of"].isoformat()}
    args = build_parser().parse_args([
        "measured", "--cohort-id", "c", "--as-of", "2026-10-29T20:00:00Z",
        "--expected-cohort-hash", "a" * 64,
    ])
    assert run(args, service=Ledger())["asOf"] == "2026-10-29T20:00:00+00:00"
    args.expected_cohort_hash = "b" * 64
    with pytest.raises(ValueError):
        run(args, service=Ledger())
    args.expected_cohort_hash = "a" * 64
    args.as_of = "2026-10-29T20:00:00"
    with pytest.raises(ValueError, match="zona horaria"):
        run(args, service=Ledger())
