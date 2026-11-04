import '../../market/data/datasources/athena_backend_fx_data_source.dart';
import 'authenticated_portfolio_fx_valuation_service.dart';

/// Product wiring for authenticated Portfolio current-value FX conversion.
///
/// This adapter deliberately binds the valuation service to ATHENA's backend FX
/// contract rather than a provider-specific client. Provider selection,
/// persistence and provenance remain backend responsibilities. No historical
/// cost/P&L conversion is enabled by this wiring.
class AuthenticatedPortfolioFxDependencies {
  AuthenticatedPortfolioFxDependencies({
    required String backendUrl,
    AthenaBackendFxDataSource? fxDataSource,
  })  : _fxDataSource = fxDataSource ??
            AthenaBackendFxDataSource(
              baseUrl: backendUrl.replaceAll(RegExp(r'/+$'), ''),
            ),
        _ownsFxDataSource = fxDataSource == null;

  final AthenaBackendFxDataSource _fxDataSource;
  final bool _ownsFxDataSource;

  late final AuthenticatedPortfolioFxValuationService valuationService =
      AuthenticatedPortfolioFxValuationService(
    loadCurrentFxRate: ({
      required String baseCurrency,
      required String quoteCurrency,
    }) =>
        _fxDataSource.getCurrentRate(
      baseCurrency: baseCurrency,
      quoteCurrency: quoteCurrency,
    ),
  );

  void dispose() {
    if (_ownsFxDataSource) {
      _fxDataSource.dispose();
    }
  }
}
