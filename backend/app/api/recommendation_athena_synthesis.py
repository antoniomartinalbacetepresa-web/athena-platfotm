from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.recommendation_investors_synthesis import _provenance as _investors_provenance
from app.repositories.recommendation_athena_synthesis_repository import RecommendationAthenaSynthesisRepository
from app.repositories.recommendation_investors_synthesis_repository import RecommendationInvestorsSynthesisRepository
from app.repositories.recommendation_news_synthesis_repository import RecommendationNewsSynthesisRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository
from app.services.athena_canonical_model_input_service import canonical_athena_model_input
from app.services.recommendation_athena_synthesis_service import RecommendationAthenaSynthesisService

router = APIRouter(prefix="/api/v1/recommendations/professional-research", tags=["recommendations-athena-synthesis"])
cycle_repository = RecommendationProfessionalResearchCycleRepository(); news_repository = RecommendationNewsSynthesisRepository(); investors_repository = RecommendationInvestorsSynthesisRepository(); athena_repository = RecommendationAthenaSynthesisRepository(); athena_service = RecommendationAthenaSynthesisService()
class AthenaSynthesisRequest(BaseModel):
    modelProvider: str = Field(min_length=1); modelName: str = Field(min_length=1); modelVersion: str = Field(min_length=1); inputFingerprint: str = Field(min_length=64, max_length=64); generatedAt: datetime; summary: str = Field(min_length=1, max_length=6000); rationale: str = Field(min_length=1, max_length=12000); uncertainties: list[str] = Field(min_length=1, max_length=50); evidenceIds: list[str] = Field(min_length=1, max_length=1000)
def _aware_iso(value, field):
    text=str(value or '').strip()
    if not text: raise ValueError(f'{field} es obligatorio.')
    try: parsed=datetime.fromisoformat(text.replace('Z','+00:00'))
    except ValueError as exc: raise ValueError(f'{field} debe ser ISO-8601 válido.') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError(f'{field} debe incluir zona horaria.')
    return parsed.astimezone(timezone.utc)
def _aware_datetime(value, field):
    if value.tzinfo is None or value.utcoffset() is None: raise ValueError(f'{field} debe incluir zona horaria.')
    return value.astimezone(timezone.utc)
def _canonical_hash(payload): return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def _cycle_evidence_contract(r):
    p=r.get('package'); c=p.get('cycle') if isinstance(p,dict) else None; radar=p.get('radar') if isinstance(p,dict) else None
    if not isinstance(c,dict) or not isinstance(radar,dict): raise ValueError('El Research Cycle persistido carece de cycle/radar válidos.')
    asof=_aware_iso(c.get('asOf'),'cycle.asOf')
    if asof != _aware_iso(radar.get('asOf'),'radar.asOf'): raise ValueError('Research Cycle y Radar deben compartir asOf.')
    ids=set(); cats=set(); candidates=radar.get('candidates')
    if not isinstance(candidates,list) or not candidates: raise ValueError('El Radar persistido no contiene candidatos.')
    for candidate in candidates:
        ev=candidate.get('evidence') if isinstance(candidate,dict) else None
        if not isinstance(ev,list) or not ev: raise ValueError('Cada candidato Radar debe conservar evidencia.')
        for item in ev:
            eid=str(item.get('evidenceId') or '').strip(); cat=str(item.get('category') or '').strip().lower()
            if not eid or not cat: raise ValueError('Toda evidencia Radar debe conservar evidenceId y category.')
            if eid in ids: raise ValueError('evidenceId no puede repetirse en el Radar.')
            ids.add(eid); cats.add(cat)
    return {'inputAsOf':asof,'evidenceIds':tuple(sorted(ids)),'coveredCategories':tuple(sorted(cats)),'hasNews':'news' in cats,'hasInvestors':'investors' in cats}
def _dependencies(ch):
    c=cycle_repository.get_by_hash(cycle_hash=ch); ct=_cycle_evidence_contract(c); n=i=None
    if ct['hasNews']:
        n=news_repository.get_by_cycle_hash(cycle_hash=ch)
        if n['radar_hash'] != c['radar_hash']: raise ValueError('La síntesis News no coincide con el radarHash del Research Cycle.')
    if ct['hasInvestors']:
        i=investors_repository.get_by_cycle_hash(cycle_hash=ch)
        if i['radar_hash'] != c['radar_hash']: raise ValueError('Investors synthesis no coincide con el radarHash del Research Cycle.')
    return c,n,i,ct
def _base_input_fingerprint(c,n,ct): return athena_service.input_fingerprint(cycle_hash=c['cycle_hash'],radar_hash=c['radar_hash'],news_synthesis_hash=(n['synthesis_hash'] if n else None),input_as_of=ct['inputAsOf'],evidence_ids=ct['evidenceIds'],covered_categories=ct['coveredCategories'])
def _news_provenance_binding(n):
    if n is None: return None
    p=n.get('package'); s=p.get('synthesis') if isinstance(p,dict) else None; aa=s.get('assessments') if isinstance(s,dict) else None
    if not isinstance(aa,list) or not aa: raise ValueError('La síntesis News canónica carece de assessments trazables.')
    out=[]; seen=set()
    for a in aa:
        eid=str(a.get('evidenceId') or '').strip(); fp=str(a.get('assessmentFingerprint') or '').strip().lower(); ref=str(a.get('sourceRef') or '').strip()
        if not eid or len(fp)!=64 or any(ch not in '0123456789abcdef' for ch in fp) or not ref.startswith('https://'): raise ValueError('La provenance News canónica está incompleta.')
        if eid in seen: raise ValueError('La provenance News canónica contiene evidenceId duplicado.')
        seen.add(eid); out.append({'evidenceId':eid,'assessmentFingerprint':fp,'sourceRef':ref})
    out.sort(key=lambda x:x['evidenceId']); return {'artifactHash':n['synthesis_hash'],'artifactType':'canonical_news_synthesis','assessmentBindings':out,'userFacingTraceability':True,'recommendationInfluence':False,'automaticTrading':False}
def _investors_provenance_binding(i): return None if i is None else _investors_provenance(i)
def _input_contract(c,n,i,ct):
    nh=n['synthesis_hash'] if n else None; ih=i['synthesis_hash'] if i else None; nb=_news_provenance_binding(n); ib=_investors_provenance_binding(i); base=_base_input_fingerprint(c,n,ct); fp=_canonical_hash({'baseAthenaInputFingerprint':base,'investorsSynthesisHash':ih,'newsProvenance':nb,'investorsProvenance':ib})
    return {'cycleHash':c['cycle_hash'],'radarHash':c['radar_hash'],**({'newsSynthesisHash':nh} if nh else {}),**({'investorsSynthesisHash':ih} if ih else {}),**({'newsProvenance':nb} if nb else {}),**({'investorsProvenance':ib} if ib else {}),'inputAsOf':ct['inputAsOf'].isoformat(),'evidenceIds':list(ct['evidenceIds']),'coveredCategories':list(ct['coveredCategories']),'inputFingerprint':fp,'requiredCoverage':'all_cycle_radar_evidence','canonicalCategorySynthesesRequired':[x for x,p in (('news',ct['hasNews']),('investors',ct['hasInvestors'])) if p],'advisoryStatus':'no_advice','recommendationInfluence':False,'automaticTrading':False}
def _response_provenance(ic,fp): return {**({'news':ic['newsProvenance']} if 'newsProvenance' in ic else {}),**({'investors':ic['investorsProvenance']} if 'investorsProvenance' in ic else {}),'inputFingerprint':fp}
@router.get('/research-cycle/{cycle_hash}/athena-synthesis/input-contract')
def get_athena_synthesis_input_contract(cycle_hash):
    try: c,n,i,ct=_dependencies(cycle_hash); return {'data':_input_contract(c,n,i,ct)}
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
@router.post('/research-cycle/{cycle_hash}/athena-synthesis')
def post_athena_synthesis(cycle_hash,request:AthenaSynthesisRequest):
    try:
        c,n,i,ct=_dependencies(cycle_hash); ic=_input_contract(c,n,i,ct); supplied=request.inputFingerprint.strip().lower()
        if supplied != ic['inputFingerprint']: raise ValueError('input_fingerprint/inputFingerprint no coincide con News/Investors/ciclo canónicos.')
        mo=canonical_athena_model_input(canonical_input_fingerprint=supplied,model_provider=request.modelProvider,model_name=request.modelName,model_version=request.modelVersion,generated_at=_aware_datetime(request.generatedAt,'generatedAt'),summary=request.summary,rationale=request.rationale,uncertainties=tuple(request.uncertainties),evidence_ids=tuple(request.evidenceIds))
        result=athena_service.build(cycle_record=c,news_synthesis_record=n,model_output=mo,canonical_input_fingerprint=supplied); payload=result.to_api_dict(); ih=i['synthesis_hash'] if i else None
        if ih: payload['investorsSynthesisHash']=ih
        payload['outputFingerprint']=_canonical_hash({'inputFingerprint':supplied,'modelProvider':payload['modelProvider'],'modelName':payload['modelName'],'modelVersion':payload['modelVersion'],'generatedAt':payload['generatedAt'],'summary':payload['summary'],'rationale':payload['rationale'],'uncertainties':payload['uncertainties'],'evidenceIds':payload['evidenceIds'],'investorsSynthesisHash':ih})
        rec=athena_repository.append(cycle_hash=c['cycle_hash'],radar_hash=c['radar_hash'],news_synthesis_hash=(n['synthesis_hash'] if n else None),synthesis_payload=payload)
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc
    return {'data':{'artifactBindingVerified':True,'synthesis':payload,'provenance':_response_provenance(ic,supplied),'persistence':{'appendOnly':True,'packageIntegrityVerified':True,'synthesisHash':rec['synthesis_hash'],'cycleHash':rec['cycle_hash'],'radarHash':rec['radar_hash'],'newsSynthesisHash':rec['news_synthesis_hash'],'investorsSynthesisHash':ih,'createdAt':rec['created_at'],'storageClaim':'single_canonical_athena_synthesis_per_cycle_append_only_not_worm_storage'}}}
@router.get('/research-cycle/{cycle_hash}/athena-synthesis')
def get_athena_synthesis(cycle_hash):
    try:
        c,n,i,ct=_dependencies(cycle_hash); rec=athena_repository.get_by_cycle_hash(cycle_hash=cycle_hash); expected_n=n['synthesis_hash'] if n else None; expected_i=i['synthesis_hash'] if i else None; stored=rec['package']['synthesis']
        if rec['radar_hash'] != c['radar_hash'] or rec['news_synthesis_hash'] != expected_n: raise ValueError('ATHENA synthesis no coincide con los artefactos canónicos actuales.')
        if stored.get('investorsSynthesisHash') != expected_i and not(expected_i is None and 'investorsSynthesisHash' not in stored): raise ValueError('ATHENA synthesis no coincide con Investors synthesis canónica.')
        ic=_input_contract(c,n,i,ct)
        if stored.get('inputFingerprint') != ic['inputFingerprint']: raise ValueError('ATHENA synthesis persistida no coincide con el input canónico actual.')
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    return {'data':{'artifactBindingVerified':True,'synthesis':stored,'provenance':_response_provenance(ic,ic['inputFingerprint']),'persistence':{'appendOnly':True,'packageIntegrityVerified':True,'synthesisHash':rec['synthesis_hash'],'cycleHash':rec['cycle_hash'],'radarHash':rec['radar_hash'],'newsSynthesisHash':rec['news_synthesis_hash'],'investorsSynthesisHash':expected_i,'createdAt':rec['created_at'],'storageClaim':'single_canonical_athena_synthesis_per_cycle_append_only_not_worm_storage'}}}
