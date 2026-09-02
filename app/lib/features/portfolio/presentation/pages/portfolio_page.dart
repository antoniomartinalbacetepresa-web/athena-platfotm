import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_radius.dart';
import '../../../../core/theme/athena_spacing.dart';
import '../../models/portfolio.dart';
import '../../models/portfolio_position.dart';
import '../../services/portfolio_service.dart';
import '../../widgets/add_position_dialog.dart';
import '../../widgets/set_reference_capital_dialog.dart';

class PortfolioPage extends StatefulWidget {
  const PortfolioPage({super.key});

  @override
  State<PortfolioPage> createState() => _PortfolioPageState();
}

class _PortfolioPageState extends State<PortfolioPage> {
  final PortfolioService _portfolioService = PortfolioService();

  List<PortfolioPosition> _positions = [];
  bool _isLoading = true;
  String? _loadError;

  Portfolio? get _portfolio => _portfolioService.portfolio;

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
        _positions = _portfolio?.positions ?? [];
        _isLoading = false;
        _loadError = null;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _positions = [];
        _isLoading = false;
        _loadError = 'No se pudo cargar la cartera guardada.';
      });
    }
  }

  Future<void> _setReferenceCapital() async {
    final value = await showDialog<double>(
      context: context,
      builder: (context) => SetReferenceCapitalDialog(
        currentValue: _portfolio?.initialCapital,
      ),
    );

    if (value == null) {
      return;
    }

    try {
      await _portfolioService.updateReferenceCapital(value);
      if (!mounted) {
        return;
      }
      setState(() {
        _positions = _portfolio?.positions ?? [];
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Capital de referencia actualizado.'),
        ),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('No se pudo guardar el capital de referencia.'),
        ),
      );
    }
  }

  Future<void> _addPosition() async {
    final result = await showDialog<AddPositionResult>(
      context: context,
      builder: (context) => const AddPositionDialog(),
    );

    if (result == null) {
      return;
    }

    final position = PortfolioPosition(
      symbol: result.symbol,
      companyName: result.companyName,
      shares: result.shares,
      averagePrice: result.averagePrice,
      currentPrice: result.currentPrice,
    );

    try {
      if (!_portfolioService.hasPortfolio) {
        await _portfolioService.createPortfolio(
          id: DateTime.now().millisecondsSinceEpoch.toString(),
          name: 'Mi cartera',
          initialCapital: 0,
        );
      }

      await _portfolioService.addPosition(position);
      if (!mounted) {
        return;
      }
      setState(() {
        _positions = _portfolio?.positions ?? [];
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${position.companyName} se ha añadido a tu cartera.',
          ),
        ),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('No se pudo guardar la posición.'),
        ),
      );
    }
  }

  Future<void> _removePosition(PortfolioPosition position) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AthenaColors.card,
        title: const Text(
          'Eliminar posición',
          style: TextStyle(
            color: AthenaColors.text,
            fontWeight: FontWeight.bold,
          ),
        ),
        content: Text(
          '¿Quieres eliminar ${position.companyName} (${position.symbol}) '
          'de tu cartera?',
          style: const TextStyle(color: AthenaColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancelar'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Eliminar'),
          ),
        ],
      ),
    );

    if (confirmed != true) {
      return;
    }

    try {
      await _portfolioService.removePosition(position.symbol);
      if (!mounted) {
        return;
      }
      setState(() {
        _positions = _portfolio?.positions ?? [];
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('No se pudo guardar el cambio.'),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final portfolio = _portfolio;
    final totalInvested = portfolio?.investedValue ?? 0.0;
    final totalCurrentValue = portfolio?.currentValue ?? 0.0;
    final totalProfitLoss = portfolio?.profitLoss ?? 0.0;
    final totalProfitLossPercentage = portfolio?.profitLossPercentage ?? 0.0;
    final referenceCapital = portfolio?.initialCapital ?? 0.0;
    final hasReferenceCapital = referenceCapital > 0;
    final unallocatedCapital = hasReferenceCapital
        ? (referenceCapital - totalInvested).clamp(0.0, double.infinity)
        : null;

    return Scaffold(
      backgroundColor: AthenaColors.background,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AthenaSpacing.lg),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1200),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildHeader(),
                  const SizedBox(height: AthenaSpacing.lg),
                  if (_loadError != null) ...[
                    _errorBanner(_loadError!),
                    const SizedBox(height: AthenaSpacing.lg),
                  ],
                  _buildSummary(
                    totalInvested: totalInvested,
                    totalCurrentValue: totalCurrentValue,
                    totalProfitLoss: totalProfitLoss,
                    totalProfitLossPercentage: totalProfitLossPercentage,
                    referenceCapital: referenceCapital,
                    hasReferenceCapital: hasReferenceCapital,
                    unallocatedCapital: unallocatedCapital,
                  ),
                  const SizedBox(height: AthenaSpacing.lg),
                  _buildAthenaAllocationState(
                    hasReferenceCapital: hasReferenceCapital,
                    referenceCapital: referenceCapital,
                    unallocatedCapital: unallocatedCapital,
                  ),
                  const SizedBox(height: 28),
                  _buildPositionsHeader(),
                  const SizedBox(height: 14),
                  if (_isLoading)
                    const Center(
                      child: Padding(
                        padding: EdgeInsets.all(40),
                        child: CircularProgressIndicator(),
                      ),
                    )
                  else if (_positions.isEmpty)
                    _emptyPortfolio()
                  else
                    ..._positions.map(_positionItem),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Wrap(
      spacing: AthenaSpacing.md,
      runSpacing: AthenaSpacing.md,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        Container(
          width: 44,
          height: 44,
          decoration: BoxDecoration(
            color: AthenaColors.card,
            borderRadius: BorderRadius.circular(AthenaRadius.md),
            border: Border.all(color: AthenaColors.border),
          ),
          child: IconButton(
            tooltip: 'Volver',
            onPressed: () => Navigator.of(context).maybePop(),
            icon: const Icon(
              Icons.arrow_back_rounded,
              color: AthenaColors.text,
            ),
          ),
        ),
        const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'MI CARTERA',
              style: TextStyle(
                color: AthenaColors.text,
                fontSize: 30,
                fontWeight: FontWeight.bold,
              ),
            ),
            SizedBox(height: 4),
            Text(
              'Capital, posiciones y planificación basada en evidencia',
              style: TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 14,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildPositionsHeader() {
    return Wrap(
      spacing: AthenaSpacing.md,
      runSpacing: AthenaSpacing.sm,
      crossAxisAlignment: WrapCrossAlignment.center,
      alignment: WrapAlignment.spaceBetween,
      children: [
        const Text(
          'POSICIONES',
          style: TextStyle(
            color: AthenaColors.text,
            fontSize: 20,
            fontWeight: FontWeight.bold,
          ),
        ),
        ElevatedButton.icon(
          onPressed: _addPosition,
          icon: const Icon(Icons.add, size: 18),
          label: const Text('Añadir posición'),
        ),
      ],
    );
  }

  Widget _buildSummary({
    required double totalInvested,
    required double totalCurrentValue,
    required double totalProfitLoss,
    required double totalProfitLossPercentage,
    required double referenceCapital,
    required bool hasReferenceCapital,
    required double? unallocatedCapital,
  }) {
    final profitColor = totalProfitLoss > 0
        ? const Color(0xFF45D483)
        : totalProfitLoss < 0
            ? const Color(0xFFFF5C5C)
            : AthenaColors.text;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AthenaSpacing.lg),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 40,
            runSpacing: 20,
            children: [
              _summaryItem(
                'Capital de referencia',
                hasReferenceCapital
                    ? _formatCurrency(referenceCapital)
                    : 'No definido',
                AthenaColors.text,
              ),
              _summaryItem(
                'Capital invertido',
                _formatCurrency(totalInvested),
                AthenaColors.text,
              ),
              _summaryItem(
                'Valor actual posiciones',
                _formatCurrency(totalCurrentValue),
                AthenaColors.text,
              ),
              _summaryItem(
                'Capital no asignado',
                unallocatedCapital == null
                    ? 'No disponible'
                    : _formatCurrency(unallocatedCapital),
                AthenaColors.text,
              ),
              _summaryItem(
                'Beneficio / pérdida',
                _formatSignedCurrency(totalProfitLoss),
                profitColor,
              ),
              _summaryItem(
                'Rentabilidad',
                totalInvested == 0
                    ? 'Sin muestra'
                    : '${totalProfitLossPercentage >= 0 ? '+' : ''}'
                        '${totalProfitLossPercentage.toStringAsFixed(2)} %',
                profitColor,
              ),
            ],
          ),
          const SizedBox(height: AthenaSpacing.lg),
          OutlinedButton.icon(
            onPressed: _setReferenceCapital,
            icon: const Icon(Icons.edit_outlined, size: 18),
            label: Text(
              hasReferenceCapital
                  ? 'Modificar capital de referencia'
                  : 'Definir capital de referencia',
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAthenaAllocationState({
    required bool hasReferenceCapital,
    required double referenceCapital,
    required double? unallocatedCapital,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AthenaSpacing.lg),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Wrap(
            spacing: 10,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                'ASIGNACIÓN ATHENA',
                style: TextStyle(
                  color: AthenaColors.text,
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
              _ValidationBadge(),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            hasReferenceCapital
                ? 'Capital de referencia disponible: '
                    '${_formatCurrency(referenceCapital)}. '
                    'Capital actualmente no asignado: '
                    '${_formatCurrency(unallocatedCapital ?? 0)}.'
                : 'Define primero un capital de referencia para que la futura '
                    'planificación pueda expresar importes y porcentajes reales.',
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 13,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 10),
          const Text(
            'ATHENA no propone todavía importes por activo porque el motor de '
            'recomendaciones sigue en validación. La asignación sólo se '
            'habilitará con recomendaciones reales, trazables y elegibles para '
            'producción; hasta entonces no se inventan pesos, retornos ni '
            'expectativas.',
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 13,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }

  Widget _positionItem(PortfolioPosition position) {
    return _PositionWithDelete(
      position: position,
      onDelete: () => _removePosition(position),
    );
  }

  static Widget _emptyPortfolio() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(40),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
        border: Border.all(color: AthenaColors.border),
      ),
      child: const Column(
        children: [
          Icon(
            Icons.account_balance_wallet_outlined,
            size: 52,
            color: AthenaColors.textSecondary,
          ),
          SizedBox(height: 16),
          Text(
            'Tu cartera está vacía',
            style: TextStyle(
              color: AthenaColors.text,
              fontSize: 20,
              fontWeight: FontWeight.bold,
            ),
          ),
          SizedBox(height: 8),
          Text(
            'Puedes definir tu capital de referencia sin inventar posiciones. '
            'Añade únicamente inversiones que realmente mantengas.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 14,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }

  static Widget _errorBanner(String message) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AthenaSpacing.md),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(AthenaRadius.md),
        border: Border.all(color: const Color(0xFFFF5C5C)),
      ),
      child: Text(
        '$message No se muestran datos sustitutivos.',
        style: const TextStyle(
          color: AthenaColors.textSecondary,
          fontSize: 13,
        ),
      ),
    );
  }

  static Widget _summaryItem(
    String title,
    String value,
    Color valueColor,
  ) {
    return SizedBox(
      width: 210,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 13,
            ),
          ),
          const SizedBox(height: 5),
          Text(
            value,
            style: TextStyle(
              color: valueColor,
              fontSize: 22,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  static String _formatCurrency(num value) {
    return '${value.toStringAsFixed(2)} €';
  }

  static String _formatSignedCurrency(num value) {
    return '${value > 0 ? '+' : ''}${value.toStringAsFixed(2)} €';
  }
}

class _ValidationBadge extends StatelessWidget {
  const _ValidationBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: AthenaColors.cardSecondary,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AthenaColors.border),
      ),
      child: const Text(
        'MOTOR EN VALIDACIÓN',
        style: TextStyle(
          color: AthenaColors.textSecondary,
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _PositionWithDelete extends StatelessWidget {
  final PortfolioPosition position;
  final VoidCallback onDelete;

  const _PositionWithDelete({
    required this.position,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final profitColor = position.profitLoss > 0
        ? const Color(0xFF45D483)
        : position.profitLoss < 0
            ? const Color(0xFFFF5C5C)
            : AthenaColors.text;

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: AthenaSpacing.md),
      padding: const EdgeInsets.all(AthenaSpacing.lg),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
        border: Border.all(color: AthenaColors.border),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          if (constraints.maxWidth < 720) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _identity(),
                const SizedBox(height: AthenaSpacing.md),
                Wrap(
                  spacing: AthenaSpacing.lg,
                  runSpacing: AthenaSpacing.md,
                  children: [
                    _valueColumn('Invertido', _format(position.investedValue)),
                    _valueColumn('Valor actual', _format(position.currentValue)),
                    _valueColumn(
                      'Resultado',
                      '${position.profitLoss > 0 ? '+' : ''}'
                      '${position.profitLoss.toStringAsFixed(2)} €',
                      valueColor: profitColor,
                    ),
                  ],
                ),
                Align(
                  alignment: Alignment.centerRight,
                  child: IconButton(
                    tooltip: 'Eliminar',
                    onPressed: onDelete,
                    icon: const Icon(
                      Icons.delete_outline_rounded,
                      color: AthenaColors.textSecondary,
                    ),
                  ),
                ),
              ],
            );
          }

          return Row(
            children: [
              Expanded(child: _identity()),
              _valueColumn('Invertido', _format(position.investedValue)),
              const SizedBox(width: 28),
              _valueColumn('Valor actual', _format(position.currentValue)),
              const SizedBox(width: 28),
              _valueColumn(
                'Resultado',
                '${position.profitLoss > 0 ? '+' : ''}'
                '${position.profitLoss.toStringAsFixed(2)} €',
                valueColor: profitColor,
              ),
              const SizedBox(width: 12),
              IconButton(
                tooltip: 'Eliminar',
                onPressed: onDelete,
                icon: const Icon(
                  Icons.delete_outline_rounded,
                  color: AthenaColors.textSecondary,
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _identity() {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 48,
          height: 48,
          alignment: Alignment.center,
          decoration: const BoxDecoration(
            color: Color(0xFF1D3B5E),
            shape: BoxShape.circle,
          ),
          child: Text(
            position.symbol.isEmpty ? '?' : position.symbol.substring(0, 1),
            style: const TextStyle(
              color: AthenaColors.text,
              fontSize: 18,
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
        const SizedBox(width: 14),
        Flexible(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                position.companyName,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: AthenaColors.text,
                  fontSize: 17,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 3),
              Text(
                '${position.symbol} · ${_formatNumber(position.shares)} acciones',
                style: const TextStyle(
                  color: AthenaColors.textSecondary,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  static Widget _valueColumn(
    String title,
    String value, {
    Color valueColor = AthenaColors.text,
  }) {
    return SizedBox(
      width: 118,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            title,
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
            ),
          ),
          const SizedBox(height: 3),
          Text(
            value,
            textAlign: TextAlign.right,
            style: TextStyle(
              color: valueColor,
              fontSize: 14,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  static String _format(double value) => '${value.toStringAsFixed(2)} €';

  static String _formatNumber(double value) {
    if (value == value.roundToDouble()) {
      return value.toInt().toString();
    }
    return value.toStringAsFixed(4).replaceFirst(RegExp(r'0+$'), '');
  }
}
