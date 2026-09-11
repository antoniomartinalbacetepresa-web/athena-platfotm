from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.macro import router as macro_router
from app.api.market import router as market_router
from app.api.news import router as news_router
from app.api.portfolio import router as portfolio_router
from app.api.portfolio_allocation_authority import (
    router as portfolio_allocation_authority_router,
)
from app.api.portfolio_allocation_policy import (
    router as portfolio_allocation_policy_router,
)
from app.api.readiness import router as readiness_router
from app.api.recommendation_athena_radar import router as recommendation_athena_radar_router
from app.api.recommendation_catalysts import router as recommendation_catalysts_router
from app.api.recommendation_devils_advocate import router as recommendation_devils_advocate_router
from app.api.recommendation_factor_risk_sealed_value import (
    router as recommendation_factor_risk_sealed_value_router,
)
from app.api.recommendation_fundamental_factor_evidence import (
    router as recommendation_fundamental_factor_evidence_router,
)
from app.api.recommendation_investment_journal import (
    router as recommendation_investment_journal_router,
)
from app.api.recommendation_market_factor_exposure import (
    router as recommendation_market_factor_exposure_router,
)
from app.api.recommendation_performance_attribution import (
    router as recommendation_performance_attribution_router,
)
from app.api.recommendation_portfolio_event_ledger import (
    router as recommendation_portfolio_event_ledger_router,
)
from app.api.recommendation_portfolio_nlv_snapshot import (
    router as recommendation_portfolio_nlv_snapshot_router,
)
from app.api.recommendation_portfolio_performance_attribution import (
    router as recommendation_portfolio_performance_attribution_router,
)
from app.api.recommendation_portfolio_state_reconstruction import (
    router as recommendation_portfolio_state_reconstruction_router,
)
from app.api.recommendation_portfolio_time_weighted_return import (
    router as recommendation_portfolio_time_weighted_return_router,
)
from app.api.recommendation_production import router as recommendation_production_router
from app.api.recommendation_professional_research import (
    router as recommendation_professional_research_router,
)
from app.api.recommendation_professional_research_cycle import (
    router as recommendation_professional_research_cycle_router,
)
from app.api.recommendation_reconciled_portfolio_weights import (
    router as recommendation_reconciled_portfolio_weights_router,
)
from app.api.recommendation_research import router as recommendation_research_router
from app.api.recommendation_research_forecast_evaluation import (
    router as recommendation_research_forecast_evaluation_router,
)
from app.api.recommendation_research_outcome_attribution import (
    router as recommendation_research_outcome_attribution_router,
)
from app.api.recommendation_research_outcome_oos_cohort import (
    router as recommendation_research_outcome_oos_cohort_router,
)
from app.api.recommendation_shadow_operations import (
    router as recommendation_shadow_operations_router,
)
from app.api.recommendation_thesis_invalidation import (
    router as recommendation_thesis_invalidation_router,
)
from app.api.recommendations import router as recommendations_router
from app.api.sec import router as sec_router
from app.api.sec_fundamental_pit import router as sec_fundamental_pit_router
from app.api.sources import router as sources_router
from app.api.user_portfolio import router as user_portfolio_router
from app.api.user_profile import router as user_profile_router
from app.security.portfolio_owner_context import bind_portfolio_owner_context


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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(user_portfolio_router)
app.include_router(user_profile_router)
app.include_router(market_router)
app.include_router(sec_router)
app.include_router(sec_fundamental_pit_router)
app.include_router(macro_router)
app.include_router(news_router)
app.include_router(sources_router)
app.include_router(readiness_router)
app.include_router(portfolio_router)
app.include_router(portfolio_allocation_authority_router)
app.include_router(portfolio_allocation_policy_router)
app.include_router(recommendations_router)
app.include_router(recommendation_production_router)
app.include_router(recommendation_research_router)
app.include_router(recommendation_professional_research_router)
app.include_router(recommendation_thesis_invalidation_router)
app.include_router(recommendation_catalysts_router)
app.include_router(recommendation_factor_risk_sealed_value_router)
app.include_router(recommendation_market_factor_exposure_router)
app.include_router(recommendation_fundamental_factor_evidence_router)
app.include_router(recommendation_performance_attribution_router)
app.include_router(
    recommendation_portfolio_performance_attribution_router,
    dependencies=[Depends(bind_portfolio_owner_context)],
)
app.include_router(
    recommendation_portfolio_time_weighted_return_router,
    dependencies=[Depends(bind_portfolio_owner_context)],
)
app.include_router(recommendation_portfolio_event_ledger_router)
app.include_router(
    recommendation_portfolio_nlv_snapshot_router,
    dependencies=[Depends(bind_portfolio_owner_context)],
)
app.include_router(recommendation_portfolio_state_reconstruction_router)
app.include_router(recommendation_reconciled_portfolio_weights_router)
app.include_router(recommendation_investment_journal_router)
app.include_router(recommendation_devils_advocate_router)
app.include_router(recommendation_athena_radar_router)
app.include_router(recommendation_professional_research_cycle_router)
app.include_router(recommendation_research_outcome_attribution_router)
app.include_router(recommendation_research_outcome_oos_cohort_router)
app.include_router(recommendation_research_forecast_evaluation_router)
app.include_router(recommendation_shadow_operations_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "athena-tyche-backend",
    }
