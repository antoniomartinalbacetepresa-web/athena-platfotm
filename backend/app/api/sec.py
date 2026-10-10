from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.sec_13f_filing_service import Sec13fFilingService
from app.services.sec_edgar_service import SecEdgarService


router = APIRouter(
    prefix="/api/v1/sec",
    tags=["sec"],
)


def _edgar_service() -> SecEdgarService:
    return SecEdgarService()


def _sec_13f_service() -> Sec13fFilingService:
    return Sec13fFilingService()


@router.get("/company-facts")
def get_company_facts(cik: str = Query(..., min_length=1)) -> dict[str, object]:
    service = _edgar_service()
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

    service = _edgar_service()
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
    service = _edgar_service()
    try:
        return {"data": service.get_institutional_filings(cik)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudieron obtener filings 13F.") from exc
    finally:
        service.close()


@router.get("/institutional-holdings/latest")
def get_latest_institutional_holdings(
    cik: str = Query(..., min_length=1),
) -> dict[str, object]:
    """Return the newest publicly known 13F information table for one filer.

    This endpoint is deliberately passive research evidence. It does not map
    CUSIPs to ATHENA instruments, does not affect recommendation scoring, and
    cannot make positions weighting-ready until canonical identity is resolved
    by a separate verified identity layer.
    """

    edgar_service = _edgar_service()
    filing_service = _sec_13f_service()
    try:
        filings = edgar_service.get_institutional_filings(cik)
        if not filings:
            raise HTTPException(
                status_code=404,
                detail="No hay filings 13F recientes disponibles para este CIK.",
            )

        selected = max(
            filings,
            key=lambda filing: (
                str(filing.get("acceptanceDateTime") or ""),
                str(filing.get("filingDate") or ""),
                str(filing.get("accessionNumber") or ""),
            ),
        )
        retrieved_at = datetime.now(timezone.utc)
        data = filing_service.fetch_and_parse(
            cik=cik,
            filing=selected,
            retrieved_at=retrieved_at,
        )
        _assert_passive_13f_payload(data)
        return {
            "data": data,
            "selectedFiling": {
                "form": selected.get("form"),
                "accessionNumber": selected.get("accessionNumber"),
                "reportDate": selected.get("reportDate"),
                "filingDate": selected.get("filingDate"),
                "acceptanceDateTime": selected.get("acceptanceDateTime"),
            },
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="No se pudieron obtener posiciones 13F verificables.",
        ) from exc
    finally:
        filing_service.close()
        edgar_service.close()


@router.get("/insider-filings")
def get_insider_filings(cik: str = Query(..., min_length=1)) -> dict[str, object]:
    service = _edgar_service()
    try:
        return {"data": service.get_insider_filings(cik)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudieron obtener filings de insiders.") from exc
    finally:
        service.close()


def _assert_passive_13f_payload(data: object) -> None:
    if not isinstance(data, dict):
        raise RuntimeError("El contrato 13F no es un objeto válido.")
    if data.get("advisoryStatus") != "no_advice":
        raise RuntimeError("El contrato 13F violó no_advice.")
    if data.get("productionEligible") is not False:
        raise RuntimeError("El contrato 13F intentó habilitar producción.")
    if data.get("athenaRecommendationInfluence") is not False:
        raise RuntimeError("El contrato 13F intentó influir en ATHENA.")
    if data.get("automaticScoring") is not False:
        raise RuntimeError("El contrato 13F intentó habilitar scoring automático.")
    if data.get("automaticTrading") is not False:
        raise RuntimeError("El contrato 13F intentó habilitar trading automático.")
    identity_policy = data.get("identityPolicy")
    if (
        not isinstance(identity_policy, dict)
        or identity_policy.get("isWeightingReady") is not False
    ):
        raise RuntimeError("El contrato 13F violó isWeightingReady=false.")
