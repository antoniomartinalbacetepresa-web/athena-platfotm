"""Owned synthetic calculation -> private Journal: availability is creation time."""
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app.api import rebound25_artifacts as artifacts, rebound25_artifacts_journal as bridge
from app.api import recommendation_professional_research_cycle as cycles
from app.api import recommendation_investment_journal as public_journal
from app.api.rebound25_synthetic import Rebound25ParametersRequest
from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_investment_journal_repository import RecommendationInvestmentJournalRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository
from app.services.rebound25_artifact_service import Rebound25ArtifactService

BASE = '/api/v1/research/strategies/rebound25/artifacts/'
CYCLES = '/api/v1/recommendations/professional-research/research-cycle/'

@pytest.fixture
def setup(tmp_path, monkeypatch):
    db = AthenaDatabase(tmp_path/'synthetic-review.db')
    service = Rebound25ArtifactService(db)
    artifact = service.create(owner_id=17, fixture_id='synthetic-rebound25-demo-v1', parameters=Rebound25ParametersRequest(
        takeProfitPct=2, stopLossPct=1, maxHoldingSessions=5, commissionBps=1, spreadBps=10,
        slippageBps=5, orderUnits=1, minAverageVolume=1, maxVolumeParticipation=.01, minRelativeVolume=0))
    monkeypatch.setattr(artifacts, 'artifact_service', service)
    monkeypatch.setattr(cycles, 'cycle_repository', RecommendationProfessionalResearchCycleRepository(db))
    journal = RecommendationInvestmentJournalRepository(db)
    monkeypatch.setattr(cycles, 'journal_repository', journal)
    monkeypatch.setattr(public_journal, 'investment_journal_repository', journal)
    app = FastAPI()
    for router in (bridge.router, cycles.router, public_journal.router): app.include_router(router)
    app.dependency_overrides[bridge.current_account] = lambda: {'id':17}
    now = datetime.now(timezone.utc).isoformat()
    payload = dict(journalId='synthetic-review',revisionId='r1',recordedAt=now,asOf=now,thesis='Human review of artificial data',
      journalReferences=[dict(referenceId='human',kind='assumption',availableAt=now,source='human_research',sourceRef='urn:human:question')],
      contradictoryEvidence=[dict(evidenceId='objection',kind='alternative_explanation',claim='Synthetic data cannot validate market performance',strength='material',availableAt=now,source='human_research',sourceRef='urn:human:objection')])
    return db,service,artifact,payload,app,TestClient(app)

def counts(db):
    with db.connect() as c:
        return [c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] if c.execute("SELECT name FROM sqlite_master WHERE name=?",(t,)).fetchone() else 0
                for t in ('athena_investment_journal_snapshots','athena_professional_research_cycles')]

def test_private_idempotent_review_binds_creation_not_series_time(setup):
    db,_,artifact,payload,_,client=setup
    url=BASE+artifact['artifactHash']+'/research-cycle'
    response=client.post(url,json=payload);assert response.status_code==200,response.text
    assert client.post(url,json=payload).json()==response.json()
    data=response.json()['data'];ref=data['syntheticBacktestReference']
    assert ref['availableAt']==artifact['createdAt']
    assert datetime.fromisoformat(ref['availableAt'])>datetime.fromisoformat(ref['seriesAsOf'])
    assert ref['listingIdentityVerified'] is False
    assert data['instrumentId']=='SYNTHETIC-LAB-25' and data['symbol']=='SYNTH'
    digest=data['integrity']['cycleHash']
    assert client.get(CYCLES+digest).status_code==404
    private=client.get(CYCLES+'private/'+digest);assert private.status_code==200,private.text
    package=private.json()['data']['package']
    for rows in (package['journal']['references'],package['radar']['candidates'][0]['evidence']):
        matching=[r for r in rows if r['sourceRef']==ref['sourceRef']]
        assert len(matching)==1 and matching[0]['availableAt']==artifact['createdAt']
    assert counts(db)==[1,1]

def test_auth_and_other_owner_fail_without_writes(setup,monkeypatch):
    db,service,artifact,payload,app,client=setup;url=BASE+artifact['artifactHash']+'/research-cycle'
    app.dependency_overrides.clear();original=service.get
    monkeypatch.setattr(service,'get',lambda **_:pytest.fail('anonymous reached artifact'))
    assert client.post(url,json=payload).status_code==401
    monkeypatch.setattr(service,'get',original)
    app.dependency_overrides[bridge.current_account]=lambda:{'id':18}
    assert client.post(url,json=payload).status_code==404
    assert counts(db)==[0,0]

@pytest.mark.parametrize('defect',['series-cutoff','future','symbol','bars','ownerId'])
def test_backdating_or_client_authority_rejected(setup,defect):
    db,_,artifact,payload,_,client=setup
    if defect=='series-cutoff':
        payload['recordedAt']=payload['asOf']=artifact['result']['asOf']
        for refs in (payload['journalReferences'],payload['contradictoryEvidence']):refs[0]['availableAt']=payload['asOf']
    elif defect=='future':payload['asOf']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    else:payload[defect]='forged'
    assert client.post(BASE+artifact['artifactHash']+'/research-cycle',json=payload).status_code in (400,422)
    assert counts(db)==[0,0]

@pytest.mark.parametrize('ref',['urn:athena:synthetic-backtest:fake','%75rn%3Aathena%3Asynthetic-backtest%3Afake','URN:ATHENA:SYNTHETIC-BACKTEST:FAKE','urn&#58;athena&#58;synthetic-backtest&#58;fake'])
def test_reserved_namespace_cannot_be_forged(setup,ref):
    db,_,artifact,payload,_,client=setup;payload['journalReferences'][0]['sourceRef']=ref
    assert client.post(BASE+artifact['artifactHash']+'/research-cycle',json=payload).status_code==400
    public={k:payload[k] for k in ('journalId','revisionId','recordedAt','asOf','thesis')}
    public.update(symbol='SYNTH',references=payload['journalReferences'])
    assert client.post('/api/v1/recommendations/professional-research/investment-journal/snapshot',json=public).status_code==400
    assert counts(db)==[0,0]

def test_capture_write_race_rolls_back(setup,monkeypatch):
    db,_,artifact,payload,_,client=setup;original=cycles._persist_professional_research_cycle
    def corrupt(*args,**kwargs):
        with db.connect() as c:c.execute("UPDATE athena_rebound25_synthetic_artifacts SET result_json='{}'")
        return original(*args,**kwargs)
    monkeypatch.setattr(cycles,'_persist_professional_research_cycle',corrupt)
    assert client.post(BASE+artifact['artifactHash']+'/research-cycle',json=payload).status_code==400
    assert counts(db)==[0,0]

def test_private_cycle_revalidates_artifact(setup):
    db,_,artifact,payload,_,client=setup
    response=client.post(BASE+artifact['artifactHash']+'/research-cycle',json=payload);assert response.status_code==200,response.text
    digest=response.json()['data']['integrity']['cycleHash']
    with db.connect() as c:c.execute("UPDATE athena_rebound25_synthetic_artifacts SET result_json='{}'")
    assert client.get(CYCLES+'private/'+digest).status_code==500
