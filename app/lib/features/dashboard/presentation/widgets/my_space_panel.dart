import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_radius.dart';
import '../../../market/di/market_dependencies.dart';
import '../../../portfolio/data/athena_backend_portfolio_correlation_data_source.dart';
import '../../../portfolio/models/portfolio.dart';
import '../../../portfolio/models/portfolio_valuation_summary.dart';
import '../../../portfolio/presentation/controllers/portfolio_concentration_controller.dart';
import '../../../portfolio/presentation/controllers/portfolio_correlation_controller.dart';
import '../../../portfolio/presentation/controllers/portfolio_current_valuation_controller.dart';
import '../../../portfolio/services/portfolio_concentration_service.dart';
import '../../../portfolio/services/portfolio_correlation_evidence_service.dart';
import '../../../portfolio/services/portfolio_service.dart';

class MySpacePanel extends StatefulWidget {
  const MySpacePanel({super.key});

  @override
  State<MySpacePanel> createState() => _MySpacePanelState();
}

class _MySpacePanelState extends State<MySpacePanel> {
  static const _baseCurrency = 'EUR';
  static const _backendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  final PortfolioService _portfolioService = PortfolioService();
  late final MarketDependencies _marketDependencies;
  late final AthenaBackendPortfolioCorrelationDataSource _correlationDataSource;
  late final PortfolioCurrentValuationController _valuationController;
  late final PortfolioConcentrationController _concentrationController;
  late final PortfolioCorrelationController _correlationController;

  Portfolio? _portfolio;
  bool _isLoading = true;
  bool _hasLoadError = false;
  List<String> _staleSymbols = const [];

  @override
  void initState() {
    super.initState();
    _marketDependencies = MarketDependencies.create();
    _correlationDataSource = AthenaBackendPortfolioCorrelationDataSource(
      baseUrl: _backendUrl,
    );
    _valuationController =
        PortfolioCurrentValuationController.forMarketDependencies(
      _marketDependencies,
    )..addListener(_onEvidenceChanged);
    _concentrationController = PortfolioConcentrationController.forService(
      PortfolioConcentrationService(
        loadValuation: _valuationController.loadValuation,
      ),
    )..addListener(_onEvidenceChanged);
    _correlationController = PortfolioCorrelationController(
      service: PortfolioCorrelationEvidenceService(
        loadPair: _correlationDataSource.getPair,
      ),
    )..addListener(_onEvidenceChanged);
    _loadPortfolio();
  }

  @override
  void dispose() {
    _valuationController.removeListener(_onEvidenceChanged);
    _concentrationController.removeListener(_onEvidenceChanged);
    _correlationController.removeListener(_onEvidenceChanged);
    _valuationController.dispose();
    _concentrationController.dispose();
    _correlationController.dispose();
    _correlationDataSource.dispose();
    _marketDependencies.dispose();
    super.dispose();
  }

  void _onEvidenceChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _loadEvidence(Portfolio portfolio) async {
    if (portfolio.positions.isEmpty) {
      _valuationController.clear();
      _concentrationController.clear();
      _correlationController.clear();
      return;
    }

    final tasks = <Future<void>>[
      _valuationController.load(
        positions: portfolio.positions,
        baseCurrency: _baseCurrency,
      ),
      _concentrationController.load(
        positions: portfolio.positions,
        baseCurrency: _baseCurrency,
      ),
    ];
    if (portfolio.positions.length >= 2) {
      tasks.add(
        _correlationController.load(
          positions: portfolio.positions,
          knowledgeCutoff: DateTime.now().toUtc(),
        ),
      );
    } else {
      _correlationController.clear();
    }
    await Future.wait(tasks);
  }

  Future<void> _loadPortfolio() async {
    try {
      await _portfolioService.loadPortfolio();

      var staleSymbols = const <String>[];
      final loaded = _portfolioService.portfolio;
      if (loaded != null && loaded.positions.isNotEmpty) {
        try {
          final report = await _portfolioService.refreshCurrentPrices(
            marketRepository: _marketDependencies.repository,
          );
          staleSymbols = report.failedSymbols;
        } catch (_) {
          staleSymbols = loaded.positions
              .map((position) => position.symbol)
              .toList(growable: false);
        }
      }

      final portfolio = _portfolioService.portfolio;
      if (portfolio != null) {
        await _loadEvidence(portfolio);
      } else {
        _valuationController.clear();
        _concentrationController.clear();
        _correlationController.clear();
      }

      if (!mounted) return;
      setState(() {
        _portfolio = portfolio;
        _staleSymbols = staleSymbols;
        _isLoading = false;
        _hasLoadError = false;
      });
    } catch (_) {
      if (!mounted) return;
      _valuationController.clear();
      _concentrationController.clear();
      _correlationController.clear();
      setState(() {
        _portfolio = null;
        _staleSymbols = const [];
        _isLoading = false;
        _hasLoadError = true;
      });
    }
  }

  PortfolioValuationSummary? _valuationSummary(Portfolio portfolio) {
    final valuation = _valuationController.valuation;
    if (valuation == null) return null;
    try {
      return PortfolioValuationSummary.fromValuation(
        valuation: valuation,
        referenceCapital: portfolio.initialCapital,
      );
    } catch (_) {
      return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 245,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'MI ESPACIO',
            style: TextStyle(
              color: AthenaColors.text,
              fontSize: 20,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 12),
          Expanded(child: _buildContent()),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            height: 40,
            child: ElevatedButton(
              onPressed: () async {
                await Navigator.pushNamed(context, '/portfolio');
                await _loadPortfolio();
              },
              child: const Text('Ver cartera'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildContent() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_hasLoadError) {
      return const Center(
        child: Text(
          'No se pudo cargar la cartera.\nNo se muestran cifras estimadas.',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 12,
            height: 1.4,
          ),
        ),
      );
    }

    final portfolio = _portfolio;
    if (portfolio == null) {
      return const Center(
        child: Text(
          'Cartera sin configurar.\nDefine tu capital y posiciones para ver métricas reales.',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 12,
            height: 1.4,
          ),
        ),
      );
    }

    final summary = _valuationSummary(portfolio);
    final concentration = _concentrationController.snapshot;
    final correlation = _correlationController.snapshot;
    final hasPositions = portfolio.positions.isNotEmpty;
    final hasReferenceCapital = portfolio.initialCapital > 0;
    final current = hasPositions ? summary?.currentValue : 0.0;
    final invested = hasPositions ? summary?.investedCapital : 0.0;
    final profitLoss = hasPositions ? summary?.profitLoss : 0.0;
    final profitLossPercentage =
        hasPositions ? summary?.profitLossPercentage : 0.0;
    final referenceExcess = hasPositions
        ? summary?.excessOverReference
        : (hasReferenceCapital ? 0.0 : null);
    final remainingReference = hasPositions
        ? summary?.unallocatedCapital
        : (hasReferenceCapital ? portfolio.initialCapital : null);

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_staleSymbols.isNotEmpty) ...[
            _priceWarning(_staleSymbols),
            const SizedBox(height: 10),
          ],
          if (_valuationController.error != null && hasPositions) ...[
            _evidenceWarning(
              'Valoración EUR no disponible: falta precio o FX verificable.',
            ),
            const SizedBox(height: 10),
          ],
          _row(
            'Valor actual posiciones',
            current == null ? 'No disponible' : _formatCurrency(current),
            current == null
                ? 'ATHENA no suma monedas sin conversión verificable'
                : '${portfolio.positions.length} posiciones · base EUR',
            AthenaColors.text,
          ),
          _divider(),
          _row(
            'Capital de referencia',
            hasReferenceCapital
                ? _formatCurrency(portfolio.initialCapital)
                : 'No definido',
            hasReferenceCapital
                ? 'Base declarada por el usuario'
                : 'Configúralo en Mi cartera',
            AthenaColors.text,
          ),
          _divider(),
          if (referenceExcess != null && referenceExcess > 0)
            _row(
              'Exceso sobre referencia',
              _formatCurrency(referenceExcess),
              'Coste histórico EUR verificable por encima de la referencia',
              const Color(0xFFFFB86B),
            )
          else
            _row(
              'Referencia sin utilizar',
              remainingReference == null
                  ? 'No disponible'
                  : _formatCurrency(remainingReference),
              remainingReference == null
                  ? 'Requiere coste histórico EUR verificable'
                  : 'Referencia menos coste histórico verificable',
              AthenaColors.text,
            ),
          _divider(),
          _row(
            'Resultado no realizado',
            profitLoss == null
                ? 'No disponible'
                : _formatSignedCurrency(profitLoss),
            profitLoss == null || profitLossPercentage == null
                ? 'Sin comparación histórica EUR verificable'
                : '${profitLossPercentage >= 0 ? '+' : ''}${profitLossPercentage.toStringAsFixed(2)} %',
            profitLoss == null
                ? AthenaColors.textSecondary
                : profitLoss > 0
                    ? const Color(0xFF45D483)
                    : profitLoss < 0
                        ? const Color(0xFFFF5C5C)
                        : AthenaColors.text,
          ),
          _divider(),
          _row(
            'Concentración',
            concentration == null
                ? 'No disponible'
                : 'HHI ${concentration.concentrationIndex.toStringAsFixed(3)}',
            concentration == null
                ? 'Requiere valoración individual EUR verificable'
                : '${concentration.effectivePositionCount.toStringAsFixed(2)} posiciones efectivas · mayor ${concentration.largestPositionSymbol} ${(concentration.largestPositionWeight * 100).toStringAsFixed(1)} %',
            AthenaColors.textSecondary,
          ),
          _divider(),
          _row(
            'Correlación PIT',
            portfolio.positions.length < 2
                ? 'No aplica'
                : correlation == null
                    ? 'No disponible'
                    : correlation.meanCorrelation.toStringAsFixed(3),
            portfolio.positions.length < 2
                ? 'Requiere al menos dos posiciones'
                : correlation == null
                    ? 'Requiere identidad canónica e históricos PIT alineados'
                    : '${correlation.pairs.length} pares · mín ${correlation.minimumCorrelation.toStringAsFixed(3)} · máx ${correlation.maximumCorrelation.toStringAsFixed(3)} · n≥${correlation.minimumSampleCount}',
            AthenaColors.textSecondary,
          ),
          if (invested == null && hasPositions) ...[
            _divider(),
            const Text(
              'El coste/P&L histórico permanece bloqueado si una posición multimoneda no tiene fecha de coste o FX histórico verificable.',
              style: TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 10,
                height: 1.35,
              ),
            ),
          ],
        ],
      ),
    );
  }

  static Widget _priceWarning(List<String> symbols) {
    final label = symbols.length == 1
        ? 'Precio sin actualizar: ${symbols.single}'
        : '${symbols.length} precios sin actualizar';

    return _evidenceWarning(
      '$label. Se conserva el último valor guardado y no se sustituye por una estimación.',
    );
  }

  static Widget _evidenceWarning(String message) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(9),
      decoration: BoxDecoration(
        color: AthenaColors.cardSecondary,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Text(
        message,
        style: const TextStyle(
          color: AthenaColors.textSecondary,
          fontSize: 10,
          height: 1.35,
        ),
      ),
    );
  }

  static Widget _divider() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Container(height: 1, color: AthenaColors.border),
    );
  }

  static Widget _row(
    String title,
    String value,
    String subtitle,
    Color valueColor,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 12,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: TextStyle(
            color: valueColor,
            fontSize: 18,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          subtitle,
          style: const TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 11,
          ),
        ),
      ],
    );
  }

  static String _formatCurrency(num value) =>
      '${value.toStringAsFixed(2)} €';

  static String _formatSignedCurrency(num value) {
    final prefix = value > 0 ? '+' : '';
    return '$prefix${value.toStringAsFixed(2)} €';
  }
}
