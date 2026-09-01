from fastapi import APIRouter, HTTPException, Query

from app.services.sec_edgar_service import SecEdgarService


router = APIRouter(
    prefix="/api/v1/sec",
    tags=["sec"],
)


@router.get("/company-facts")
def get_company_facts(cik: str = Query(..., min_length=1)) -> dict[str, object]:
    service = SecEdgarService()
    try:
        return {"data": service.get_company_facts(cik)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudieron obtener datos de SEC EDGAR.") from exc
    finally:
        service.close()


@router.get("/filings")
def get_filings(
    cik: str = Query(..., min_length=1),
    forms: str | None = Query(None),
) -> dict[str, object]:
    selected_forms = None
    if forms:
        selected_forms = tuple(item.strip() for item in forms.split(",") if item.strip())

    service = SecEdgarService()
    try:
        return {"data": service.get_recent_filings(cik, selected_forms)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudieron obtener filings de SEC EDGAR.") from exc
    finally:
        service.close()


@router.get("/institutional-filings")
def get_institutional_filings(cik: str = Query(..., min_length=1)) -> dict[str, object]:
    service = SecEdgarService()
    try:
        return {"data": service.get_institutional_filings(cik)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudieron obtener filings 13F.") from exc
    finally:
        service.close()


@router.get("/insider-filings")
def get_insider_filings(cik: str = Query(..., min_length=1)) -> dict[str, object]:
    service = SecEdgarService()
    try:
        return {"data": service.get_insider_filings(cik)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudieron obtener filings de insiders.") from exc
    finally:
        service.close()
