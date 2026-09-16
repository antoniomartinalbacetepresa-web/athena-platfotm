from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.repositories.sec_fundamental_pit_repository import SecFundamentalPitRepository
from app.services.sec_edgar_service import SecEdgarService
from app.services.sec_fundamental_pit_service import SecFundamentalPitService


router = APIRouter(prefix="/api/v1/sec", tags=["sec"])


@router.post("/fundamentals/pit-import")
def import_fundamental_pit(
    cik: str = Query(..., min_length=1),
    asOf: datetime = Query(...),
) -> dict[str, object]:
    if asOf.tzinfo is None or asOf.utcoffset() is None:
        raise HTTPException(status_code=400, detail="asOf debe incluir zona horaria.")
    as_of = asOf.astimezone(timezone.utc)
    edgar = SecEdgarService()
    try:
        company_facts = edgar.get_company_facts(cik)
        submissions = edgar.get_submissions(cik)
        facts = SecFundamentalPitService().normalize(
            cik=cik,
            company_facts=company_facts,
            submissions=submissions,
            as_of=as_of,
        )
        repository = SecFundamentalPitRepository()
        for fact in facts:
            repository.append(fact)
        return {
            "data": {
                "cik": SecEdgarService.normalize_cik(cik),
                "asOf": as_of.isoformat(),
                "imported": len(facts),
                "factKeys": [fact.fact_key for fact in facts],
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "isWeightingReady": False,
                "policy": {
                    "automaticTrading": False,
                    "automaticProductionPromotion": False,
                    "lookahead": "forbidden",
                    "source": "sec_edgar_companyfacts_plus_submissions",
                    "revisionHandling": "accession_bound_vintages_preserved",
                    "secrets": "none_required",
                },
            }
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudieron importar fundamentales SEC PIT.") from exc
    finally:
        edgar.close()
