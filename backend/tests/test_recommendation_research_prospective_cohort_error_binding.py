"""Synthetic binding tests; never productive evidence."""
from app.services.recommendation_research_prospective_cohort_error_binding_service import RecommendationResearchProspectiveCohortErrorBindingService


def test_binding_rejects_foreign_error_and_keeps_missing_denominator():
    service = RecommendationResearchProspectiveCohortErrorBindingService()
    cohort = {"artifactVersion":"research-prospective-cohort-v1","specificationHashes":["a"*64,"b"*64],"productionEligible":False,"productionLearningEligible":False,"automaticTrading":False,"cohortHash":"c"*64}
    result = service.bind(cohort=cohort, error_records=[])
    assert result["missingSpecificationHashes"] == ["a"*64,"b"*64]
    assert result["outcomeEvidenceVerified"] is False
