from fastapi import APIRouter

from app.services.source_catalog import get_source_catalog, get_source_summary


router = APIRouter(
    prefix="/api/v1/sources",
    tags=["sources"],
)


@router.get("")
def list_sources() -> dict[str, object]:
    return {
        "data": get_source_catalog(),
        "summary": get_source_summary(),
    }
