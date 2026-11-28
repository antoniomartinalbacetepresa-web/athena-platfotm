from datetime import datetime, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.longitudinal_oos_policy_repository import (
    LongitudinalOosPolicyRepository,
)
from app.services.recommendation_learning_status_service import (
    RecommendationLearningStatusService,
)


def _criteria() -> dict[str, object]:
    # Test-only governance criteria. These values are not production policy.
    return {
        "minimumEvaluationSpanDays": 30,
        "minimumDistinctEvaluationPeriods": 2,
        "minimumEligibleOutcomes": 10,
        "minimumDistinctResolvedIssuers": 5,
        "requiredHorizonSeconds": [30 * 86400],
        "dependencyHandling": "test_only_no_independence_claim",
    }


def test_canonical_learning_status_consumes_persisted_policy_and_human_approval(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = LongitudinalOosPolicyRepository(database=database)
    policy = repository.register_policy(
        policy_id="test-longitudinal-policy",
        version=1,
        criteria=_criteria(),
        precommitted_by="test-human",
        evidence_ref="test://precommit",
    )

    service = RecommendationLearningStatusService(database=database)
    before_approval = service.get_status(as_of=datetime.now(timezone.utc))
    sufficiency = before_approval["researchForecastErrorOos"][
        "longitudinalSufficiency"
    ]
    assert sufficiency["status"] == "policy_approval_required"
    assert sufficiency["policyApproved"] is False
    assert sufficiency["productionSufficiencyClaimed"] is False

    repository.approve_policy(
        policy_fingerprint=policy["artifact"]["policyFingerprint"],
        approved_by="test-human-reviewer",
        evidence_ref="test://approval",
        human_review_confirmed=True,
    )

    after_approval = service.get_status(as_of=datetime.now(timezone.utc))
    governed = after_approval["researchForecastErrorOos"]
    sufficiency = governed["longitudinalSufficiency"]
    assert sufficiency["status"] == "precommitted_policy_not_satisfied"
    assert sufficiency["policyApproved"] is True
    assert sufficiency["acceptanceEvidenceVerified"] is False
    assert sufficiency["productionSufficiencyClaimed"] is False
    assert governed["productionLearningEligible"] is False
    assert governed["productionEligible"] is False
    assert governed["recommendationCandidateReady"] is False
    assert governed["policy"]["automaticModelMutation"] is False
    assert governed["policy"]["automaticProductionPromotion"] is False
    assert governed["policy"]["automaticTrading"] is False


def test_canonical_learning_status_fails_closed_without_precommitted_policy(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    status = RecommendationLearningStatusService(database=database).get_status(
        as_of=datetime.now(timezone.utc)
    )

    sufficiency = status["researchForecastErrorOos"]["longitudinalSufficiency"]
    assert sufficiency["status"] == "policy_not_precommitted"
    assert sufficiency["policyApproved"] is False
    assert sufficiency["acceptanceEvidenceVerified"] is False
    assert sufficiency["productionSufficiencyClaimed"] is False
