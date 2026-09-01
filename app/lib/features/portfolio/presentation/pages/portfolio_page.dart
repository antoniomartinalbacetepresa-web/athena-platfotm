import 'package:flutter/material.dart';

import '../../../../../core/theme/athena_colors.dart';
import '../../../../../core/theme/athena_radius.dart';
import '../../../../../core/theme/athena_spacing.dart';
import '../../models/portfolio_position.dart';
import '../../services/portfolio_service.dart';
import '../../widgets/add_position_dialog.dart';

class PortfolioPage extends StatefulWidget {
  const PortfolioPage({super.key});

  @override
  State<PortfolioPage> createState() => _PortfolioPageState();
}

class _PortfolioPageState extends State<PortfolioPage> {
  final PortfolioService _portfolioService =
      PortfolioService();

  List<PortfolioPosition> _positions = [];
  bool _isLoading = true;

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
        _positions =
            _portfolioService.portfolio?.positions ?? [];
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }

      setState(() {
        _positions = [];
        _isLoading = false;
      });
    }
  }

  Future<void> _addPosition() async {
    final result = await showDialog<AddPositionResult>(
      context: context,
      builder: (context) {
        return const AddPositionDialog();
      },
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
          id: DateTime.now()
              .millisecondsSinceEpoch
              .toString(),
          name: 'Mi cartera',
          initialCapital: 0,
        );
      }

      await _portfolioService.addPosition(
        position,
      );

      if (!mounted) {
        return;
      }

      setState(() {
        _positions =
            _portfolioService.portfolio?.positions ?? [];
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
          content: Text(
            'No se ha podido guardar la posición.',
          ),
        ),
      );
    }
  }

  Future<void> _removePosition(
    PortfolioPosition position,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) {
        return AlertDialog(
          backgroundColor: AthenaColors.card,
          title: const Text(
            'Eliminar posición',
            style: TextStyle(
              color: AthenaColors.text,
              fontWeight: FontWeight.bold,
            ),
          ),
          content: Text(
            '¿Quieres eliminar ${position.companyName} '
            '(${position.symbol}) de tu cartera?',
            style: const TextStyle(
              color: AthenaColors.textSecondary,
            ),
          ),
          actions: [
            TextButton(
              onPressed: () {
                Navigator.of(context).pop(false);
              },
              child: const Text(
                'Cancelar',
              ),
            ),
            ElevatedButton(
              onPressed: () {
                Navigator.of(context).pop(true);
              },
              child: const Text(
                'Eliminar',
              ),
            ),
          ],
        );
      },
    );

    if (confirmed != true) {
      return;
    }

    try {
      await _portfolioService.removePosition(
        position.symbol,
      );

      if (!mounted) {
        return;
      }

      setState(() {
        _positions =
            _portfolioService.portfolio?.positions ?? [];
      });

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${position.companyName} se ha eliminado de tu cartera.',
          ),
        ),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'No se ha podido guardar el cambio.',
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final totalInvested = _positions.fold<double>(
      0.0,
      (total, position) =>
          total + position.investedValue,
    );

    final totalCurrentValue = _positions.fold<double>(
      0.0,
      (total, position) =>
          total + position.currentValue,
    );

    final totalProfitLoss =
        totalCurrentValue - totalInvested;

    final totalProfitLossPercentage =
        totalInvested == 0.0
            ? 0.0
            : (totalProfitLoss / totalInvested) * 100;

    return Scaffold(
      backgroundColor: AthenaColors.background,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(
            AthenaSpacing.lg,
          ),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(
                maxWidth: 1200,
              ),
              child: Column(
                crossAxisAlignment:
                    CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 44,
                        height: 44,
                        decoration: BoxDecoration(
                          color: AthenaColors.card,
                          borderRadius:
                              BorderRadius.circular(
                            AthenaRadius.md,
                          ),
                          border: Border.all(
                            color: AthenaColors.border,
                          ),
                        ),
                        child: IconButton(
                          tooltip: 'Volver',
                          onPressed: () {
                            Navigator.of(context)
                                .maybePop();
                          },
                          icon: const Icon(
                            Icons.arrow_back_rounded,
                            color: AthenaColors.text,
                          ),
                        ),
                      ),
                      const SizedBox(
                        width: AthenaSpacing.md,
                      ),
                      const Column(
                        crossAxisAlignment:
                            CrossAxisAlignment.start,
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
                            'Gestiona tus inversiones',
                            style: TextStyle(
                              color:
                                  AthenaColors.textSecondary,
                              fontSize: 14,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),
                  _summarySection(
                    totalInvested: totalInvested,
                    totalCurrentValue:
                        totalCurrentValue,
                    totalProfitLoss:
                        totalProfitLoss,
                    totalProfitLossPercentage:
                        totalProfitLossPercentage,
                  ),
                  const SizedBox(height: 28),
                  Row(
                    mainAxisAlignment:
                        MainAxisAlignment.spaceBetween,
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
                        icon: const Icon(
                          Icons.add,
                          size: 18,
                        ),
                        label: const Text(
                          'Añadir posición',
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  if (_isLoading)
                    const Center(
                      child: Padding(
                        padding: EdgeInsets.all(40),
                        child:
                            CircularProgressIndicator(),
                      ),
                    )
                  else if (_positions.isEmpty)
                    _emptyPortfolio()
                  else
                    ..._positions.map(
                      (position) => _positionItem(
                        position,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _positionItem(
    PortfolioPosition position,
  ) {
    return _PositionWithDelete(
      position: position,
      onDelete: () {
        _removePosition(position);
      },
    );
  }

  static Widget _emptyPortfolio() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(40),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(
          AthenaRadius.lg,
        ),
        border: Border.all(
          color: AthenaColors.border,
        ),
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
            'Añade tu primera posición para empezar '
            'a construir tu cartera.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 14,
            ),
          ),
        ],
      ),
    );
  }

  static Widget _summarySection({
    required double totalInvested,
    required double totalCurrentValue,
    required double totalProfitLoss,
    required double totalProfitLossPercentage,
  }) {
    final profitColor = totalProfitLoss >= 0
        ? const Color(0xFF45D483)
        : const Color(0xFFFF5C5C);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(
        AthenaSpacing.lg,
      ),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(
          AthenaRadius.lg,
        ),
        border: Border.all(
          color: AthenaColors.border,
        ),
      ),
      child: Wrap(
        spacing: 40,
        runSpacing: 20,
        children: [
          _summaryItem(
            'Capital invertido',
            _formatCurrency(totalInvested),
            AthenaColors.text,
          ),
          _summaryItem(
            'Valor actual',
            _formatCurrency(totalCurrentValue),
            AthenaColors.text,
          ),
          _summaryItem(
            'Beneficio / pérdida',
            _formatCurrency(totalProfitLoss),
            profitColor,
          ),
          _summaryItem(
            'Rentabilidad',
            '${totalProfitLossPercentage >= 0 ? '+' : ''}'
            '${totalProfitLossPercentage.toStringAsFixed(2)} %',
            profitColor,
          ),
        ],
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
        crossAxisAlignment:
            CrossAxisAlignment.start,
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
              fontSize: 23,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  static String _formatCurrency(double value) {
    return '${value.toStringAsFixed(2)} €';
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
    final profitColor = position.profitLoss >= 0
        ? const Color(0xFF45D483)
        : const Color(0xFFFF5C5C);

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(
        bottom: AthenaSpacing.md,
      ),
      padding: const EdgeInsets.all(
        AthenaSpacing.lg,
      ),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(
          AthenaRadius.lg,
        ),
        border: Border.all(
          color: AthenaColors.border,
        ),
      ),
      child: Row(
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
              position.symbol.isEmpty
                  ? '?'
                  : position.symbol.substring(0, 1),
              style: const TextStyle(
                color: AthenaColors.text,
                fontSize: 18,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment:
                  CrossAxisAlignment.start,
              children: [
                Text(
                  position.companyName,
                  style: const TextStyle(
                    color: AthenaColors.text,
                    fontSize: 17,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  '${position.symbol} · '
                  '${_formatNumber(position.shares)} acciones',
                  style: const TextStyle(
                    color:
                        AthenaColors.textSecondary,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          _valueColumn(
            'Invertido',
            _formatCurrency(
              position.investedValue,
            ),
          ),
          const SizedBox(width: 28),
          _valueColumn(
            'Valor actual',
            _formatCurrency(
              position.currentValue,
            ),
          ),
          const SizedBox(width: 28),
          SizedBox(
            width: 105,
            child: Column(
              crossAxisAlignment:
                  CrossAxisAlignment.end,
              children: [
                Text(
                  '${position.profitLoss >= 0 ? '+' : ''}'
                  '${position.profitLoss.toStringAsFixed(2)} €',
                  style: TextStyle(
                    color: profitColor,
                    fontSize: 15,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  '${position.profitLossPercentage >= 0 ? '+' : ''}'
                  '${position.profitLossPercentage.toStringAsFixed(2)} %',
                  style: TextStyle(
                    color: profitColor,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
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
      ),
    );
  }

  static Widget _valueColumn(
    String title,
    String value,
  ) {
    return SizedBox(
      width: 110,
      child: Column(
        crossAxisAlignment:
            CrossAxisAlignment.end,
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
            style: const TextStyle(
              color: AthenaColors.text,
              fontSize: 14,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  static String _formatCurrency(double value) {
    return '${value.toStringAsFixed(2)} €';
  }

  static String _formatNumber(double value) {
    if (value == value.roundToDouble()) {
      return value.toInt().toString();
    }

    return value.toStringAsFixed(2);
  }
}