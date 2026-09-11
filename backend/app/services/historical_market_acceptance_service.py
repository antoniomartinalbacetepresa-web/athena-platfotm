from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.services.corporate_action_reconciliation_service import (
    CorporateActionReconciliationReport,
)
from app.services.market_observation_coverage_service import (
    MarketObservationCoverageReport,
)


@dataclass(frozen=True)
class HistoricalMarketAcceptanceReport:
    coverage: MarketObservationCoverageReport
    reconciliation_reports: tuple[CorporateActionReconciliationReport, ...]
    required_history_days: int
    required_deep_history_coverage: float
    independent_secondary_source_verified: bool

    @property
    def depth_gate_passed(self) -> bool:
        return (
            self.coverage.history_eligible_instrument_count > 0
            and self.coverage.observation_count > 0
            and self.coverage.minimum_history_days >= self.required_history_days
            and self.coverage.deep_history_coverage
            >= self.required_deep_history_coverage
        )

    @property
    def agreed_event_count(self) -> int:
        return sum(report.agreed_event_count for report in self.reconciliation_reports)

    @property
    def corporate_action_gate_passed(self) -> bool:
        if not self.independent_secondary_source_verified:
            return False
        if not self.reconciliation_reports or self.agreed_event_count <= 0:
            return False
        for report in self.reconciliation_reports:
            if len(report.source_providers) < 2:
                return False
            if report.conflict_event_count > 0 or report.incomplete_event_count > 0:
                return False
            if report.events and not report.reconciled:
                return False
        return True

    @property
    def history_acceptance_passed(self) -> bool:
        return self.depth_gate_passed and self.corporate_action_gate_passed

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "historyAcceptancePassed": self.history_acceptance_passed,
            "depthGatePassed": self.depth_gate_passed,
            "corporateActionGatePassed": self.corporate_action_gate_passed,
            "requiredHistoryDays": self.required_history_days,
            "requiredDeepHistoryCoverage": self.required_deep_history_coverage,
            "measuredDeepHistoryCoverage": self.coverage.deep_history_coverage,
            "independentSecondarySourceVerified": self.independent_secondary_source_verified,
            "reconciliationReportCount": len(self.reconciliation_reports),
            "agreedCorporateActionEventCount": self.agreed_event_count,
            "automaticCanonicalization": False,
            "automaticPriceAdjustment": False,
            "productionAuthorization": False,
            "warning": (
                "Este gate exige profundidad histórica medida sobre el universo elegible "
                "y evidencia explícita de una fuente secundaria independiente. Pasarlo no "
                "autoriza producción, canonicalización automática ni ajustes automáticos."
            ),
        }


class HistoricalMarketAcceptanceService:
    DEFAULT_REQUIRED_HISTORY_DAYS = 365
    DEFAULT_REQUIRED_DEEP_HISTORY_COVERAGE = 1.0

    def __init__(
        self,
        *,
        required_history_days: int = DEFAULT_REQUIRED_HISTORY_DAYS,
        required_deep_history_coverage: float = DEFAULT_REQUIRED_DEEP_HISTORY_COVERAGE,
    ) -> None:
        if required_history_days < self.DEFAULT_REQUIRED_HISTORY_DAYS:
            raise ValueError("required_history_days no puede ser inferior a 365.")
        if not 0 < required_deep_history_coverage <= 1:
            raise ValueError("required_deep_history_coverage debe estar entre 0 y 1.")
        self._required_history_days = int(required_history_days)
        self._required_deep_history_coverage = float(required_deep_history_coverage)

    def evaluate(
        self,
        *,
        coverage: MarketObservationCoverageReport,
        reconciliation_reports: Iterable[CorporateActionReconciliationReport],
        independent_secondary_source_verified: bool,
    ) -> HistoricalMarketAcceptanceReport:
        reports = tuple(reconciliation_reports)
        return HistoricalMarketAcceptanceReport(
            coverage=coverage,
            reconciliation_reports=reports,
            required_history_days=self._required_history_days,
            required_deep_history_coverage=self._required_deep_history_coverage,
            independent_secondary_source_verified=bool(
                independent_secondary_source_verified
            ),
        )
