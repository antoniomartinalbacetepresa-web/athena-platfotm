import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_radius.dart';
import '../../../market/di/market_dependencies.dart';
import '../../../portfolio/models/portfolio.dart';
import '../../../portfolio/services/portfolio_service.dart';

class MySpacePanel extends StatefulWidget {
  const MySpacePanel({super.key});

  @override
  State<MySpacePanel> createState() => _MySpacePanelState();
}

class _MySpacePanelState extends State<MySpacePanel> {
  final PortfolioService _portfolioService = PortfolioService();
  late final MarketDependencies _marketDependencies;

  Portfolio? _portfolio;
  bool _isLoading = true;
  bool _hasLoadError = false;
  List<String> _staleSymbols = const [];

  @override
  void initState() {
    super.initState();
    _marketDependencies = MarketDependencies.create();
    _loadPortfolio();
  }

  @override
  void dispose() {
    _marketDependencies.dispose();
    super.dispose();
  }

  Future<void> _loadPortfolio() async {
    try {
      await _portfolioService.loadPortfolio();

      var staleSymbols = const <String>[];
      final portfolio = _portfolioService.portfolio;
      if (portfolio != null && portfolio.positions.isNotEmpty) {
        try {
          final report = await _portfolioService.refreshCurrentPrices(
            marketRepository: _marketDependencies.repository,
          );
          staleSymbols = report.failedSymbols;
        } catch (_) {
          staleSymbols = portfolio.positions
              .map((position) => position.symbol)
              .toList(growable: false);
        }
      }

      if (!mounted) {
        return;
      }
      setState(() {
        _portfolio = _portfolioService.portfolio;
        _staleSymbols = staleSymbols;
        _isLoading = false;
        _hasLoadError = false;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _portfolio = null;
        _staleSymbols = const [];
        _isLoading = false;
        _hasLoadError = true;
      });
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

    final invested = portfolio.investedValue;
    final current = portfolio.currentValue;
    final profitLoss = portfolio.profitLoss;
    final hasReferenceCapital = portfolio.initialCapital > 0;
    final remainingReference = hasReferenceCapital
        ? portfolio.referenceCapitalRemaining
        : null;
    final referenceExcess = hasReferenceCapital
        ? portfolio.referenceCapitalExcess
        : null;

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_staleSymbols.isNotEmpty) ...[
            _priceWarning(_staleSymbols),
            const SizedBox(height: 10),
          ],
          _row(
            'Valor actual posiciones',
            _formatCurrency(current),
            '${portfolio.positions.length} posiciones',
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
          if (hasReferenceCapital && portfolio.isOverReferenceCapital)
            _row(
              'Exceso sobre referencia',
              _formatCurrency(referenceExcess ?? 0),
              'Coste invertido por encima de la referencia',
              const Color(0xFFFFB86B),
            )
          else
            _row(
              'Referencia sin utilizar',
              remainingReference == null
                  ? 'No disponible'
                  : _formatCurrency(remainingReference),
              remainingReference == null
                  ? 'Falta capital de referencia'
                  : 'Referencia menos coste invertido',
              AthenaColors.text,
            ),
          _divider(),
          _row(
            'Resultado no realizado',
            _formatSignedCurrency(profitLoss),
            invested == 0
                ? 'Sin capital invertido'
                : '${portfolio.profitLossPercentage >= 0 ? '+' : ''}${portfolio.profitLossPercentage.toStringAsFixed(2)} %',
            profitLoss > 0
                ? const Color(0xFF45D483)
                : profitLoss < 0
                    ? const Color(0xFFFF5C5C)
                    : AthenaColors.text,
          ),
          _divider(),
          _row(
            'Riesgo',
            'Pendiente',
            'Sin métrica validada de cartera',
            AthenaColors.textSecondary,
          ),
        ],
      ),
    );
  }

  static Widget _priceWarning(List<String> symbols) {
    final label = symbols.length == 1
        ? 'Precio sin actualizar: ${symbols.single}'
        : '${symbols.length} precios sin actualizar';

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(9),
      decoration: BoxDecoration(
        color: AthenaColors.cardSecondary,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Text(
        '$label. Se conserva el último valor guardado y no se sustituye por una estimación.',
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

  static String _formatCurrency(num value) {
    return '${value.toStringAsFixed(2)} €';
  }

  static String _formatSignedCurrency(num value) {
    final prefix = value > 0 ? '+' : '';
    return '$prefix${value.toStringAsFixed(2)} €';
  }
}
