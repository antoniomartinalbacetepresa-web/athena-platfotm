from datetime import datetime, timezone
import pytest
from app.services.recommendation_athena_radar_service import AthenaRadarCandidateInput, AthenaRadarEvidenceInput, RecommendationAthenaRadarService
from app.services.recommendation_investor_evidence_service import InvestorDocumentInput, RecommendationInvestorEvidenceService

def _document(**overrides):
    values = {"issuer_id":"issuer-1","document_type":"sec_filing","title":"Issuer 10-Q filing","provider":"sec_edgar","primary_source":"sec.gov","document_url":"https://www.sec.gov/Archives/example.htm","published_at":datetime(2026,9,12,14,0,tzinfo=timezone.utc),"retrieved_at":datetime(2026,9,12,14,5,tzinfo=timezone.utc)}; values.update(overrides); return InvestorDocumentInput(**values)

def test_build_preserves_primary_document_provenance_and_pit_availability():
    evidence=RecommendationInvestorEvidenceService().build(document=_document()); assert evidence.category=="investors"; assert evidence.source=="sec.gov"; assert evidence.provider=="sec_edgar"; assert evidence.publisher=="sec.gov"; assert evidence.available_at.isoformat()=="2026-09-12T14:05:00+00:00"; assert evidence.published_at.isoformat()=="2026-09-12T14:00:00+00:00"; assert len(evidence.evidence_id)==64
    result=RecommendationAthenaRadarService().build(as_of=datetime(2026,9,12,14,6,tzinfo=timezone.utc),candidates=(AthenaRadarCandidateInput(instrument_id="issuer-1",symbol="ABC",evidence=(evidence,)),)); assert result.candidates[0].evidence[0].source_ref.startswith("https://www.sec.gov/")

def test_rejects_non_https_document():
    with pytest.raises(ValueError,match="HTTPS"): RecommendationInvestorEvidenceService().build(document=_document(document_url="http://www.sec.gov/file"))

def test_rejects_publication_after_observation():
    with pytest.raises(ValueError,match="published_at"): RecommendationInvestorEvidenceService().build(document=_document(published_at=datetime(2026,9,12,15,0,tzinfo=timezone.utc)))

def test_rejects_fmp_provenance():
    with pytest.raises(ValueError,match="FMP"): RecommendationInvestorEvidenceService().build(document=_document(provider="fmp"))

def test_policy_does_not_claim_truth_corroboration_or_automatic_actions():
    policy=RecommendationInvestorEvidenceService().policy(); assert policy["productionTruthClaimed"] is False; assert policy["independentCorroborationClaimed"] is False; assert policy["recommendationInfluence"] is False; assert policy["automaticScoring"] is False; assert policy["automaticTrading"] is False

def test_radar_rejects_direct_investors_bypass_without_structured_provenance():
    evidence=AthenaRadarEvidenceInput(evidence_id="e1",category="investors",urgency="routine",summary="filing",available_at=datetime(2026,9,12,14,5,tzinfo=timezone.utc),source="sec.gov",source_ref="https://www.sec.gov/file")
    with pytest.raises(ValueError,match="investors requiere provider"): RecommendationAthenaRadarService().build(as_of=datetime(2026,9,12,14,6,tzinfo=timezone.utc),candidates=(AthenaRadarCandidateInput(instrument_id="issuer-1",symbol="ABC",evidence=(evidence,)),))
