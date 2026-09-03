import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_radius.dart';
import '../../../../core/theme/athena_spacing.dart';
import '../../../market/di/market_dependencies.dart';
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
  static const _baseCurrency = 'EUR';

  final PortfolioService _portfolioService = PortfolioService();
  late final MarketDependencies _marketDependencies;

  List<PortfolioPosition> _positions = [];
  bool _isLoading = true;
  bool _isRefreshingPrices = false;
  String? _loadError;
  String? _priceRefreshMessage;

  Portfolio? get _portfolio => _portfolioService.portfolio;

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
      String? refreshMessage;
      final portfolio = _portfolio;
      if (portfolio != null && portfolio.positions.isNotEmpty) {
        try {
          final report = await _portfolioService.refreshCurrentPrices(
            marketRepository: _marketDependencies.repository,
          );
          refreshMessage = _refreshMessageFor(report);
        } catch (_) {
          refreshMessage =
              'La cartera se ha cargado, pero no se pudieron actualizar las '
              'cotizaciones. Se conservan los últimos precios persistidos.';
        }
      }

      if (!mounted) return;
      setState(() {
        _positions = _portfolio?.positions ?? [];
        _isLoading = false;
        _loadError = null;
        _priceRefreshMessage = refreshMessage;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _positions = [];
        _isLoading = false;
        _loadError = 'No se pudo cargar la cartera guardada.';
        _priceRefreshMessage = null;
      });
    }
  }

  Future<void> _refreshPrices() async {
    if (_isRefreshingPrices || _positions.isEmpty) return;

    setState(() {
      _isRefreshingPrices = true;
      _priceRefreshMessage = null;
    });

    try {
      final report = await _portfolioService.refreshCurrentPrices(
        marketRepository: _marketDependencies.repository,
      );
      if (!mounted) return;
      setState(() {
        _positions = _portfolio?.positions ?? [];
        _isRefreshingPrices = false;
        _priceRefreshMessage = _refreshMessageFor(report);
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _positions = _portfolio?.positions ?? [];
        _isRefreshingPrices = false;
        _priceRefreshMessage =
            'No se pudieron actualizar las cotizaciones. Se conservan los '
            'últimos precios persistidos; ATHENA no los sustituye por estimaciones.';
      });
    }
  }

  String? _refreshMessageFor(PortfolioPriceRefreshReport report) {
    if (report.totalPositions == 0 || report.isComplete) return null;
    final failed = report.failedSymbols.join(', ');
    return 'Cotizaciones actualizadas: ${report.updatedPositions} de '
        '${report.totalPositions}. Sin actualización verificable: $failed. '
        'Se mantiene el último precio conocido para esos símbolos.';
  }

  Future<void> _setReferenceCapital() async {
    final value = await showDialog<double>(
      context: context,
      builder: (context) => SetReferenceCapitalDialog(
        currentValue: _portfolio?.initialCapital,
      ),
    );
    if (value == null) return;

    try {
      await _portfolioService.updateReferenceCapital(value);
      if (!mounted) return;
      setState(() => _positions = _portfolio?.positions ?? []);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Capital de referencia actualizado.')),
      );
    } catch (_) {
      if (!mounted) return;
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
      builder: (context) => AddPositionDialog(
        marketRepository: _marketDependencies.repository,
      ),
    );
    if (result == null) return;

    final position = PortfolioPosition(
      symbol: result.symbol,
      companyName: result.companyName,
      shares: result.shares,
      averagePrice: result.averagePrice,
      currentPrice: result.currentPrice,
      priceCurrency: result.priceCurrency,
      exchange: result.exchange,
      quoteType: result.quoteType,
      currentPriceUpdatedAt: result.currentPriceUpdatedAt,
      currentPriceSourceProvider: result.currentPriceSourceProvider,
      currentPriceRetrievedAt: result.currentPriceRetrievedAt,
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
      if (!mounted) return;
      setState(() {
        _positions = _portfolio?.positions ?? [];
        _priceRefreshMessage = null;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${position.companyName} se ha añadido con cotización trazable.',
          ),
        ),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No se pudo guardar la posición.')),
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
          '¿Quieres eliminar ${position.companyName} (${position.symbol}) de tu cartera?',
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
    if (confirmed != true) return;

    try {
      await _portfolioService.removePosition(position.symbol);
      if (!mounted) return;
      setState(() => _positions = _portfolio?.positions ?? []);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No se pudo guardar el cambio.')),
      );
    }
  }

  bool get _allPositionsComparableInBaseCurrency {
    if (_positions.isEmpty) return true;
    return _positions.every((position) {
      final currency = position.priceCurrency?.trim().toUpperCase();
      return currency == _baseCurrency;
    });
  }

  double get _baseInvestedValue =>
      _positions.fold(0.0, (sum, position) => sum + position.investedValue);

  double get _baseCurrentValue =>
      _positions.fold(0.0, (sum, position) => sum + position.currentValue);

  @override
  Widget build(BuildContext context) {
    final portfolio = _portfolio;
    final referenceCapital = portfolio?.initialCapital ?? 0.0;
    final hasReferenceCapital = referenceCapital > 0;
    final comparable = _allPositionsComparableInBaseCurrency;
    final totalInvested = comparable ? _baseInvestedValue : null;
    final totalCurrentValue = comparable ? _baseCurrentValue : null;
    final totalProfitLoss = comparable && totalInvested != null && totalCurrentValue != null
        ? totalCurrentValue - totalInvested
        : null;
    final totalProfitLossPercentage = totalProfitLoss != null && totalInvested! > 0
        ? (totalProfitLoss / totalInvested) * 100
        : null;
    final unallocatedCapital = hasReferenceCapital && totalInvested != null
        ? (referenceCapital - totalInvested).clamp(0.0, double.infinity)
        : null;
    final excessOverReference = hasReferenceCapital && totalInvested != null
        ? (totalInvested - referenceCapital).clamp(0.0, double.infinity)
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
                    _statusBanner(_loadError!, isError: true),
                    const SizedBox(height: AthenaSpacing.md),
                  ],
                  if (_priceRefreshMessage != null) ...[
                    _statusBanner(_priceRefreshMessage!),
                    const SizedBox(height: AthenaSpacing.md),
                  ],
                  if (!comparable && _positions.isNotEmpty) ...[
                    _statusBanner(
                      'La cartera contiene posiciones en monedas distintas de EUR. '
                      'ATHENA conserva los importes nativos y bloquea los agregados '
                      'hasta aplicar FX verificable; no suma divisas como si fueran euros.',
                    ),
                    const SizedBox(height: AthenaSpacing.md),
                  ],
                  _buildSummary(
                    totalInvested: totalInvested,
                    totalCurrentValue: totalCurrentValue,
                    totalProfitLoss: totalProfitLoss,
                    totalProfitLossPercentage: totalProfitLossPercentage,
                    referenceCapital: referenceCapital,
                    hasReferenceCapital: hasReferenceCapital,
                    unallocatedCapital: unallocatedCapital,
                    excessOverReference: excessOverReference,
                  ),
                  const SizedBox(height: AthenaSpacing.lg),
                  _buildAthenaAllocationState(
                    hasReferenceCapital: hasReferenceCapital,
                    referenceCapital: referenceCapital,
                    unallocatedCapital: unallocatedCapital,
                    comparable: comparable,
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
            icon: const Icon(Icons.arrow_back_rounded, color: AthenaColors.text),
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
              style: TextStyle(color: AthenaColors.textSecondary, fontSize: 14),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildPositionsHeader() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final actions = Wrap(
          spacing: AthenaSpacing.sm,
          runSpacing: AthenaSpacing.sm,
          children: [
            OutlinedButton.icon(
              onPressed: _positions.isEmpty || _isRefreshingPrices
                  ? null
                  : _refreshPrices,
              icon: _isRefreshingPrices
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh_rounded, size: 18),
              label: const Text('Actualizar precios'),
            ),
            ElevatedButton.icon(
              onPressed: _addPosition,
              icon: const Icon(Icons.add, size: 18),
              label: const Text('Añadir posición'),
            ),
          ],
        );

        if (constraints.maxWidth < 620) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'POSICIONES',
                style: TextStyle(
                  color: AthenaColors.text,
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: AthenaSpacing.md),
              actions,
            ],
          );
        }

        return Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'POSICIONES',
              style: TextStyle(
                color: AthenaColors.text,
                fontSize: 20,
                fontWeight: FontWeight.bold,
              ),
            ),
            actions,
          ],
        );
      },
    );
  }

  Widget _buildSummary({
    required double? totalInvested,
    required double? totalCurrentValue,
    required double? totalProfitLoss,
    required double? totalProfitLossPercentage,
    required double referenceCapital,
    required bool hasReferenceCapital,
    required double? unallocatedCapital,
    required double? excessOverReference,
  }) {
    final profitColor = totalProfitLoss == null
        ? AthenaColors.textSecondary
        : totalProfitLoss > 0
            ? const Color(0xFF45D483)
            : totalProfitLoss < 0
                ? const Color(0xFFFF5C5C)
                : AthenaColors.text;

    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 40,
            runSpacing: 20,
            children: [
              _summaryItem(
                'Capital de referencia',
                hasReferenceCapital ? _formatCurrency(referenceCapital, _baseCurrency) : 'No definido',
                AthenaColors.text,
              ),
              _summaryItem(
                'Capital invertido',
                totalInvested == null ? 'Pendiente FX' : _formatCurrency(totalInvested, _baseCurrency),
                AthenaColors.text,
              ),
              _summaryItem(
                'Valor actual posiciones',
                totalCurrentValue == null ? 'Pendiente FX' : _formatCurrency(totalCurrentValue, _baseCurrency),
                AthenaColors.text,
              ),
              _summaryItem(
                excessOverReference != null && excessOverReference > 0
                    ? 'Exceso sobre referencia'
                    : 'Capital no asignado',
                excessOverReference != null && excessOverReference > 0
                    ? _formatCurrency(excessOverReference, _baseCurrency)
                    : unallocatedCapital == null
                        ? 'No disponible'
                        : _formatCurrency(unallocatedCapital, _baseCurrency),
                AthenaColors.text,
              ),
              _summaryItem(
                'Beneficio / pérdida',
                totalProfitLoss == null
                    ? 'No disponible'
                    : _formatSignedCurrency(totalProfitLoss, _baseCurrency),
                profitColor,
              ),
              _summaryItem(
                'Rentabilidad',
                totalProfitLossPercentage == null
                    ? 'No disponible'
                    : '${totalProfitLossPercentage >= 0 ? '+' : ''}${totalProfitLossPercentage.toStringAsFixed(2)} %',
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
    required bool comparable,
  }) {
    final referenceText = hasReferenceCapital
        ? 'Capital de referencia: ${_formatCurrency(referenceCapital, _baseCurrency)}. '
            '${comparable ? 'Capital actualmente no asignado: ${_formatCurrency(unallocatedCapital ?? 0, _baseCurrency)}.' : 'El capital no asignado no se calcula hasta convertir la cartera a EUR con FX verificable.'}'
        : 'Define un capital de referencia para que una futura planificación validada pueda expresarse en euros y porcentajes.';

    return _card(
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
            referenceText,
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 13,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 10),
          const Text(
            'ATHENA no propone todavía importes por activo porque el motor de '
            'recomendaciones sigue en validación. La asignación sólo se habilitará '
            'con recomendaciones reales, trazables y elegibles para producción.',
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

  Widget _card({required Widget child}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AthenaSpacing.lg),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
        border: Border.all(color: AthenaColors.border),
      ),
      child: child,
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

  static Widget _statusBanner(String message, {bool isError = false}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AthenaSpacing.md),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(AthenaRadius.md),
        border: Border.all(
          color: isError ? const Color(0xFFFF5C5C) : AthenaColors.border,
        ),
      ),
      child: Text(
        isError ? '$message No se muestran datos sustitutivos.' : message,
        style: const TextStyle(
          color: AthenaColors.textSecondary,
          fontSize: 13,
          height: 1.35,
        ),
      ),
    );
  }

  static Widget _summaryItem(String title, String value, Color valueColor) {
    return SizedBox(
      width: 210,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 13),
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

  static String _formatCurrency(num value, String currency) =>
      '${value.toStringAsFixed(2)} $currency';

  static String _formatSignedCurrency(num value, String currency) =>
      '${value > 0 ? '+' : ''}${value.toStringAsFixed(2)} $currency';
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

  const _PositionWithDelete({required this.position, required this.onDelete});

  String get _currency {
    final currency = position.priceCurrency?.trim().toUpperCase();
    if (currency == null || !RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
      return 'MONEDA?';
    }
    return currency;
  }

  bool get _hasCompleteProvenance {
    final provider = position.currentPriceSourceProvider?.trim();
    final updatedAt = position.currentPriceUpdatedAt;
    final retrievedAt = position.currentPriceRetrievedAt;
    return provider != null &&
        provider.isNotEmpty &&
        updatedAt != null &&
        retrievedAt != null &&
        !retrievedAt.isBefore(updatedAt);
  }

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
          final values = Wrap(
            spacing: AthenaSpacing.lg,
            runSpacing: AthenaSpacing.md,
            children: [
              _valueColumn('Invertido', _format(position.investedValue)),
              _valueColumn('Valor actual', _format(position.currentValue)),
              _valueColumn(
                'Resultado nominal',
                '${position.profitLoss > 0 ? '+' : ''}${position.profitLoss.toStringAsFixed(2)} $_currency',
                valueColor: profitColor,
              ),
            ],
          );

          if (constraints.maxWidth < 720) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _identity(),
                const SizedBox(height: AthenaSpacing.md),
                values,
                const SizedBox(height: AthenaSpacing.md),
                _provenance(),
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

          return Column(
            children: [
              Row(
                children: [
                  Expanded(child: _identity()),
                  values,
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
              const SizedBox(height: AthenaSpacing.sm),
              Align(alignment: Alignment.centerLeft, child: _provenance()),
            ],
          );
        },
      ),
    );
  }

  Widget _identity() {
    final metadata = <String>[
      position.symbol,
      _currency,
      if (position.exchange?.trim().isNotEmpty == true) position.exchange!.trim(),
      if (position.quoteType?.trim().isNotEmpty == true) position.quoteType!.trim(),
    ];

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
                '${metadata.join(' · ')} · ${_formatNumber(position.shares)} acciones',
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

  Widget _provenance() {
    if (!_hasCompleteProvenance) {
      return const Text(
        'Precio persistido sin provenance completa · actualizar antes de usar esta posición como evidencia.',
        style: TextStyle(
          color: Color(0xFFFFB86B),
          fontSize: 11,
          height: 1.3,
        ),
      );
    }

    final provider = position.currentPriceSourceProvider!.trim();
    final updatedAt = position.currentPriceUpdatedAt!.toLocal();
    final retrievedAt = position.currentPriceRetrievedAt!.toLocal();
    return Text(
      'Precio: $provider · observado ${_formatDateTime(updatedAt)} · recuperado ${_formatDateTime(retrievedAt)}',
      style: const TextStyle(
        color: AthenaColors.textSecondary,
        fontSize: 11,
        height: 1.3,
      ),
    );
  }

  Widget _valueColumn(String title, String value, {Color valueColor = AthenaColors.text}) {
    return SizedBox(
      width: 132,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            title,
            style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
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

  String _format(double value) => '${value.toStringAsFixed(2)} $_currency';

  static String _formatNumber(double value) {
    if (value == value.roundToDouble()) return value.toInt().toString();
    return value.toStringAsFixed(4).replaceFirst(RegExp(r'0+$'), '');
  }

  static String _formatDateTime(DateTime value) {
    String two(int number) => number.toString().padLeft(2, '0');
    return '${two(value.day)}/${two(value.month)}/${value.year} ${two(value.hour)}:${two(value.minute)}';
  }
}
