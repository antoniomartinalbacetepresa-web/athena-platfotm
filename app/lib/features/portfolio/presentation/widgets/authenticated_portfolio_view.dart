import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_spacing.dart';
import '../../models/authenticated_portfolio_view_position.dart';
import '../controllers/authenticated_portfolio_controller.dart';

/// Fail-closed presentation for an authenticated owner's holdings.
///
/// This view consumes only [AuthenticatedPortfolioController]. It never adapts
/// authenticated holdings into the legacy locally-persisted Portfolio model.
class AuthenticatedPortfolioView extends StatelessWidget {
  const AuthenticatedPortfolioView({
    super.key,
    required this.controller,
    required this.onRetry,
    required this.onAdd,
    required this.onRemove,
  });

  final AuthenticatedPortfolioController controller;
  final VoidCallback onRetry;
  final VoidCallback onAdd;
  final ValueChanged<AuthenticatedPortfolioViewPosition> onRemove;

  @override
  Widget build(BuildContext context) {
    if (controller.isLoading) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(40),
          child: CircularProgressIndicator(),
        ),
      );
    }

    if (controller.sessionRejected) {
      return _StateCard(
        icon: Icons.lock_outline,
        title: 'Sesión requerida',
        message:
            'La sesión ya no es válida. ATHENA ha retirado las posiciones de la vista y requiere iniciar sesión de nuevo.',
        actionLabel: null,
        onAction: null,
      );
    }

    final error = controller.error;
    if (error != null) {
      return _StateCard(
        icon: Icons.error_outline,
        title: 'Cartera no disponible',
        message: error,
        actionLabel: 'Reintentar',
        onAction: onRetry,
      );
    }

    final positions = controller.positions;
    if (positions.isEmpty) {
      return _StateCard(
        icon: Icons.account_balance_wallet_outlined,
        title: 'Cartera vacía',
        message:
            'Todavía no hay posiciones asociadas a esta cuenta. Las posiciones autenticadas se guardan exclusivamente en ATHENA.',
        actionLabel: 'Añadir posición',
        onAction: onAdd,
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _ComparableSummary(controller: controller),
        const SizedBox(height: AthenaSpacing.lg),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'POSICIONES AUTENTICADAS',
              style: TextStyle(
                color: AthenaColors.text,
                fontSize: 18,
                fontWeight: FontWeight.bold,
              ),
            ),
            ElevatedButton.icon(
              onPressed: onAdd,
              icon: const Icon(Icons.add, size: 18),
              label: const Text('Añadir'),
            ),
          ],
        ),
        const SizedBox(height: AthenaSpacing.md),
        ...positions.map(
          (position) => Padding(
            padding: const EdgeInsets.only(bottom: AthenaSpacing.md),
            child: _PositionCard(
              position: position,
              onRemove: () => onRemove(position),
            ),
          ),
        ),
      ],
    );
  }
}

class _ComparableSummary extends StatelessWidget {
  const _ComparableSummary({required this.controller});

  final AuthenticatedPortfolioController controller;

  @override
  Widget build(BuildContext context) {
    final currency = controller.directlyComparableCurrency;
    final current = controller.directlyComparableCurrentValue;
    final invested = controller.directlyComparableInvestedValue;
    final comparable = currency != null && current != null;

    return Container(
      padding: const EdgeInsets.all(AthenaSpacing.lg),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        border: Border.all(color: AthenaColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Valoración verificable',
            style: TextStyle(
              color: AthenaColors.text,
              fontWeight: FontWeight.bold,
              fontSize: 18,
            ),
          ),
          const SizedBox(height: AthenaSpacing.sm),
          Text(
            comparable
                ? 'Valor actual: ${current.toStringAsFixed(2)} $currency'
                : 'Valor total no disponible: las posiciones usan monedas distintas o falta moneda verificable.',
            style: const TextStyle(color: AthenaColors.text),
          ),
          const SizedBox(height: 4),
          Text(
            comparable && invested != null
                ? 'Capital invertido declarado: ${invested.toStringAsFixed(2)} $currency'
                : 'Capital invertido: No disponible',
            style: const TextStyle(color: AthenaColors.textSecondary),
          ),
          const SizedBox(height: AthenaSpacing.sm),
          const Text(
            'ATHENA no suma directamente monedas distintas ni fabrica costes de compra ausentes.',
            style: TextStyle(color: AthenaColors.textSecondary, fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _PositionCard extends StatelessWidget {
  const _PositionCard({required this.position, required this.onRemove});

  final AuthenticatedPortfolioViewPosition position;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final currency = position.currency ?? '';
    final cost = position.averagePurchasePrice;
    final pnl = position.profitLoss;

    return Container(
      padding: const EdgeInsets.all(AthenaSpacing.md),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        border: Border.all(color: AthenaColors.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${position.companyName} (${position.symbol})',
                  style: const TextStyle(
                    color: AthenaColors.text,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  '${position.quantity} acciones · ${position.currentPrice.toStringAsFixed(2)} $currency',
                  style: const TextStyle(color: AthenaColors.textSecondary),
                ),
                const SizedBox(height: 4),
                Text(
                  cost == null
                      ? 'Precio medio: No disponible · P/L: No disponible'
                      : 'Precio medio: ${cost.toStringAsFixed(2)} $currency · P/L: ${pnl?.toStringAsFixed(2) ?? 'No disponible'} $currency',
                  style: const TextStyle(color: AthenaColors.textSecondary),
                ),
                const SizedBox(height: 4),
                Text(
                  'Fuente: ${position.marketSourceProvider} · observada ${position.marketObservedAt.toLocal()}',
                  style: const TextStyle(
                    color: AthenaColors.textSecondary,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Eliminar posición',
            onPressed: onRemove,
            icon: const Icon(Icons.delete_outline),
          ),
        ],
      ),
    );
  }
}

class _StateCard extends StatelessWidget {
  const _StateCard({
    required this.icon,
    required this.title,
    required this.message,
    required this.actionLabel,
    required this.onAction,
  });

  final IconData icon;
  final String title;
  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AthenaSpacing.lg),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        border: Border.all(color: AthenaColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        children: [
          Icon(icon, color: AthenaColors.textSecondary, size: 34),
          const SizedBox(height: AthenaSpacing.sm),
          Text(
            title,
            style: const TextStyle(
              color: AthenaColors.text,
              fontWeight: FontWeight.bold,
              fontSize: 18,
            ),
          ),
          const SizedBox(height: AthenaSpacing.sm),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: AthenaColors.textSecondary),
          ),
          if (actionLabel != null && onAction != null) ...[
            const SizedBox(height: AthenaSpacing.md),
            ElevatedButton(onPressed: onAction, child: Text(actionLabel!)),
          ],
        ],
      ),
    );
  }
}
