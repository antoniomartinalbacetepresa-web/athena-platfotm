from fastapi import FastAPI

from app.api.market import router as market_router
from app.api.sources import router as sources_router


app = FastAPI(
    title="ATHENA TYCHE Backend",
    version="0.1.0",
    description="Backend seguro y normalizado de ATHENA TYCHE.",
)

app.include_router(market_router)
app.include_router(sources_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "athena-tyche-backend",
    }
