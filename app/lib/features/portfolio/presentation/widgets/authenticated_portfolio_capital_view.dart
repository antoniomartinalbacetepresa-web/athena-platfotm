import 'package:flutter/material.dart';

import '../controllers/authenticated_portfolio_capital_controller.dart';

/// Presentation-only projection of encrypted owner-scoped Profile capital.
///
/// This widget never infers capital from holdings and never performs FX
/// conversion. A value is rendered only when Profile supplied both a validated
/// amount and ISO currency through [AuthenticatedPortfolioCapitalController].
class AuthenticatedPortfolioCapitalView extends StatelessWidget {
  const AuthenticatedPortfolioCapitalView({
    super.key,
    required this.controller,
    required this.onRetry,
  });

  final AuthenticatedPortfolioCapitalController controller;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    if (controller.isLoading) {
      return const Card(
        key: Key('authenticated-capital-loading'),
        child: ListTile(
          leading: SizedBox.square(
            dimension: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          title: Text('Verificando capital disponible…'),
        ),
      );
    }

    if (controller.sessionRejected) {
      return const Card(
        key: Key('authenticated-capital-session-rejected'),
        child: ListTile(
          leading: Icon(Icons.lock_outline),
          title: Text('Capital disponible no accesible'),
          subtitle: Text('La sesión ya no está autorizada. Inicia sesión de nuevo.'),
        ),
      );
    }

    if (controller.error != null) {
      return Card(
        key: const Key('authenticated-capital-error'),
        child: ListTile(
          leading: const Icon(Icons.warning_amber_rounded),
          title: const Text('Capital disponible no verificado'),
          subtitle: Text(controller.error!),
          trailing: IconButton(
            key: const Key('authenticated-capital-retry'),
            tooltip: 'Reintentar',
            onPressed: () => onRetry(),
            icon: const Icon(Icons.refresh),
          ),
        ),
      );
    }

    if (!controller.hasVerifiedCapital) {
      return const Card(
        key: Key('authenticated-capital-not-configured'),
        child: ListTile(
          leading: Icon(Icons.account_balance_wallet_outlined),
          title: Text('Capital disponible no configurado'),
          subtitle: Text('Configúralo en Perfil para mantener una única fuente cifrada y protegida.'),
        ),
      );
    }

    final amount = controller.availableCapital!;
    final currency = controller.currency!;
    return Card(
      key: const Key('authenticated-capital-verified'),
      child: ListTile(
        leading: const Icon(Icons.account_balance_wallet_outlined),
        title: const Text('Capital disponible'),
        subtitle: const Text('Fuente: preferencias cifradas de tu Perfil ATHENA'),
        trailing: Text(
          '${amount.toStringAsFixed(2)} $currency',
          key: const Key('authenticated-capital-value'),
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w700,
              ),
        ),
      ),
    );
  }
}
