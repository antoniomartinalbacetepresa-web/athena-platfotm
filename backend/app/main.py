from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.macro import router as macro_router
from app.api.market import router as market_router
from app.api.sec import router as sec_router
from app.api.sources import router as sources_router


app = FastAPI(
    title="ATHENA TYCHE Backend",
    version="0.1.0",
    description="Backend seguro y normalizado de ATHENA TYCHE.",
)

# Flutter Web se sirve durante desarrollo desde un puerto local variable.
# Permitimos únicamente orígenes HTTP(S) locales; no abrimos CORS a cualquier
# dominio. En producción se configurará el origen exacto del frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(market_router)
app.include_router(sec_router)
app.include_router(macro_router)
app.include_router(sources_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "athena-tyche-backend",
    }
