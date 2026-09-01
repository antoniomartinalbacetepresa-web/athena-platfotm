import 'package:flutter/material.dart';

import '../../../../../core/theme/athena_colors.dart';
import '../../../../../core/theme/athena_radius.dart';
import '../../../../../core/theme/athena_spacing.dart';
import '../../models/portfolio_position.dart';

class PortfolioPositionCard extends StatelessWidget {
  final PortfolioPosition position;

  const PortfolioPositionCard({
    super.key,
    required this.position,
  });

  @override
  Widget build(BuildContext context) {
    final profitColor = position.profitLoss >= 0.0
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
          _symbol(),

          const SizedBox(width: 14),

          Expanded(
            child: _companyInfo(),
          ),

          _valueColumn(
            'Invertido',
            _formatCurrency(position.investedValue),
          ),

          const SizedBox(width: 28),

          _valueColumn(
            'Valor actual',
            _formatCurrency(position.currentValue),
          ),

          const SizedBox(width: 28),

          SizedBox(
            width: 105,
            child: Column(
              crossAxisAlignment:
                  CrossAxisAlignment.end,
              children: [
                Text(
                  '${position.profitLoss >= 0.0 ? '+' : ''}'
                  '${position.profitLoss.toStringAsFixed(2)} €',
                  style: TextStyle(
                    color: profitColor,
                    fontSize: 15,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  '${position.profitLossPercentage >= 0.0 ? '+' : ''}'
                  '${position.profitLossPercentage.toStringAsFixed(2)} %',
                  style: TextStyle(
                    color: profitColor,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _symbol() {
    final symbol = position.symbol.trim();

    return Container(
      width: 48,
      height: 48,
      alignment: Alignment.center,
      decoration: const BoxDecoration(
        color: Color(0xFF1D3B5E),
        shape: BoxShape.circle,
      ),
      child: Text(
        symbol.isEmpty ? '?' : symbol.substring(0, 1),
        style: const TextStyle(
          color: AthenaColors.text,
          fontSize: 18,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }

  Widget _companyInfo() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
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
            color: AthenaColors.textSecondary,
            fontSize: 12,
          ),
        ),
      ],
    );
  }

  Widget _valueColumn(
    String title,
    String value,
  ) {
    return SizedBox(
      width: 110,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
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

  String _formatCurrency(double value) {
    return '${value.toStringAsFixed(2)} €';
  }

  String _formatNumber(double value) {
    if (value == value.roundToDouble()) {
      return value.toInt().toString();
    }

    return value.toStringAsFixed(2);
  }
}