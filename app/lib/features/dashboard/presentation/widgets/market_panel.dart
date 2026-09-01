import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../market/controllers/global_market_context_controller.dart';
import '../../../market/di/market_dependencies.dart';
import '../../../market/models/global_market_context.dart';
import '../../../market/models/regional_market_context.dart';
import 'base/athena_card.dart';

class MarketPanel extends StatefulWidget {
  const MarketPanel({super.key});

  @override
  State<MarketPanel> createState() => _MarketPanelState();
}

class _MarketPanelState extends State<MarketPanel> {
  late final MarketDependencies _dependencies;
  late final GlobalMarketContextController _contextController;

  @override
  void initState() {
    super.initState();

    _dependencies = MarketDependencies.create();

    _contextController = GlobalMarketContextController(
      service: _dependencies.globalMarketDataService,
    );

    _contextController.addListener(_onControllerChanged);

    _contextController.loadGlobalContext();
  }

  void _onControllerChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  @override
  void dispose() {
    _contextController
      ..removeListener(_onControllerChanged)
      ..dispose();

    _dependencies.dispose();

    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final globalContext = _contextController.context;

    return AthenaCard(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'MERCADO GLOBAL',
            style: TextStyle(
              color: AthenaColors.text,
              fontSize: 22,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 14),
          Expanded(
            child: _marketContextView(globalContext),
          ),
        ],
      ),
    );
  }

  Widget _marketContextView(
    GlobalMarketContext? globalContext,
  ) {
    if (_contextController.isLoading) {
      return const Center(
        child: CircularProgressIndicator(),
      );
    }

    if (_contextController.error != null) {
      return Align(
        alignment: Alignment.topLeft,
        child: Text(
          _contextController.error!,
          style: const TextStyle(
            color: Colors.redAccent,
            fontSize: 12,
          ),
        ),
      );
    }

    if (globalContext == null) {
      return const Align(
        alignment: Alignment.topLeft,
        child: Text(
          'Sin contexto global del mercado.',
          style: TextStyle(
            color: AthenaColors.text,
          ),
        ),
      );
    }

    return _buildGlobalMarketView(globalContext);
  }

  Widget _buildGlobalMarketView(
    GlobalMarketContext globalContext,
  ) {
    final sentimentColor =
        _sentimentColor(globalContext.sentiment);

    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxHeight < 320;

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              globalContext.summary,
              maxLines: compact ? 1 : 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: AthenaColors.text,
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
            ),
            SizedBox(height: compact ? 4 : 6),
            const Text(
              'COBERTURA PILOTO · DIRECCIÓN POR BENCHMARKS · PESOS SOBRE UNIVERSO SEMILLA',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 8,
                fontWeight: FontWeight.w600,
              ),
            ),
            SizedBox(height: compact ? 6 : 10),
            _regionalRow(
              context: globalContext.america,
              weight: globalContext.americaWeight,
              compact: compact,
            ),
            SizedBox(height: compact ? 5 : 8),
            _regionalRow(
              context: globalContext.europe,
              weight: globalContext.europeWeight,
              compact: compact,
            ),
            SizedBox(height: compact ? 5 : 8),
            _regionalRow(
              context: globalContext.asia,
              weight: globalContext.asiaWeight,
              compact: compact,
            ),
            const Spacer(),
            Container(
              width: double.infinity,
              padding: EdgeInsets.symmetric(
                horizontal: 12,
                vertical: compact ? 5 : 8,
              ),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: AthenaColors.border,
                ),
              ),
              child: Row(
                children: [
                  const Expanded(
                    child: Text(
                      'SESGO GLOBAL',
                      style: TextStyle(
                        color: AthenaColors.textSecondary,
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                  Text(
                    _sentimentLabel(
                      globalContext.sentiment,
                    ),
                    style: TextStyle(
                      color: sentimentColor,
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
            ),
            SizedBox(height: compact ? 5 : 8),
            Row(
              children: [
                Expanded(
                  child: _secondaryMetric(
                    label: 'BENCHMARKS',
                    value:
                        _totalAssets(globalContext).toString(),
                    compact: compact,
                  ),
                ),
                Expanded(
                  child: _secondaryMetric(
                    label: 'SUBIENDO',
                    value:
                        '${globalContext.advancingPercentage.toStringAsFixed(1)}%',
                    compact: compact,
                  ),
                ),
                Expanded(
                  child: _secondaryMetric(
                    label: 'BAJANDO',
                    value:
                        '${globalContext.decliningPercentage.toStringAsFixed(1)}%',
                    compact: compact,
                  ),
                ),
              ],
            ),
            SizedBox(height: compact ? 3 : 6),
            _secondaryMetric(
              label: 'ACTUALIZADO',
              value: _formatUpdatedAt(
                globalContext.updatedAt,
              ),
              compact: compact,
            ),
          ],
        );
      },
    );
  }

  Widget _regionalRow({
    required RegionalMarketContext context,
    required double weight,
    required bool compact,
  }) {
    final color =
        _sentimentColor(context.sentiment);

    return Container(
      width: double.infinity,
      padding: EdgeInsets.symmetric(
        horizontal: 10,
        vertical: compact ? 5 : 8,
      ),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: AthenaColors.border,
        ),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 68,
            child: Text(
              context.displayName.toUpperCase(),
              style: const TextStyle(
                color: AthenaColors.text,
                fontSize: 10,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          Expanded(
            child: Text(
              '▲ ${context.advancingPercentage.toStringAsFixed(0)}%',
              style: TextStyle(
                color: color,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Text(
            '▼ ${context.decliningPercentage.toStringAsFixed(0)}%',
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            '${(weight * 100).toStringAsFixed(1)}%',
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 10,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  Widget _secondaryMetric({
    required String label,
    required String value,
    required bool compact,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 9,
            fontWeight: FontWeight.bold,
          ),
        ),
        SizedBox(height: compact ? 1 : 3),
        Text(
          value,
          style: TextStyle(
            color: AthenaColors.text,
            fontSize: compact ? 12 : 13,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }

  int _totalAssets(
    GlobalMarketContext globalContext,
  ) {
    return globalContext.america.assetsAnalyzed +
        globalContext.europe.assetsAnalyzed +
        globalContext.asia.assetsAnalyzed;
  }

  String _sentimentLabel(String sentiment) {
    switch (sentiment.toLowerCase()) {
      case 'positive':
        return 'POSITIVO';

      case 'negative':
        return 'NEGATIVO';

      case 'neutral':
        return 'NEUTRO';

      default:
        return sentiment.toUpperCase();
    }
  }

  Color _sentimentColor(String sentiment) {
    switch (sentiment.toLowerCase()) {
      case 'positive':
        return const Color(0xFF45D483);

      case 'negative':
        return Colors.redAccent;

      default:
        return AthenaColors.textSecondary;
    }
  }

  String _formatUpdatedAt(
    DateTime updatedAt,
  ) {
    final hour =
        updatedAt.hour.toString().padLeft(2, '0');

    final minute =
        updatedAt.minute.toString().padLeft(2, '0');

    return '$hour:$minute';
  }
}
