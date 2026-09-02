import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_radius.dart';
import '../../../portfolio/models/portfolio.dart';
import '../../../portfolio/services/portfolio_service.dart';

class MySpacePanel extends StatefulWidget {
  const MySpacePanel({super.key});

  @override
  State<MySpacePanel> createState() => _MySpacePanelState();
}

class _MySpacePanelState extends State<MySpacePanel> {
  final PortfolioService _portfolioService = PortfolioService();

  Portfolio? _portfolio;
  bool _isLoading = true;
  bool _hasLoadError = false;

  @override
  void initState() {
    super.initState();
    _loadPortfolio();
  }

  Future<void> _loadPortfolio() async {
    try {
      await _portfolioService.loadPortfolio();
      if (!mounted) {
        return;
      }
      setState(() {
        _portfolio = _portfolioService.portfolio;
        _isLoading = false;
        _hasLoadError = false;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _portfolio = null;
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
    final availableCapital = hasReferenceCapital
        ? (portfolio.initialCapital - invested).clamp(0.0, double.infinity)
        : null;
    final accountValue = availableCapital == null
        ? current
        : current + availableCapital;

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _row(
            'Valor de cartera',
            _formatCurrency(accountValue),
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
          _row(
            'Liquidez estimada',
            availableCapital == null
                ? 'No disponible'
                : _formatCurrency(availableCapital),
            availableCapital == null
                ? 'Falta capital de referencia'
                : 'Capital no asignado',
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
