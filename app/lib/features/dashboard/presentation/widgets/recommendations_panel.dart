import 'package:flutter/material.dart';

import '../../../../../core/theme/athena_colors.dart';
import '../../../../../core/theme/athena_spacing.dart';
import '../../../../../core/widgets/dashboard_panel.dart';
import '../../../../recommendations/controllers/recommendation_learning_controller.dart';
import '../../../../recommendations/di/recommendation_dependencies.dart';
import '../../../../recommendations/models/recommendation_learning_status.dart';
import '../../../../recommendations/services/recommendation_learning_status_provider.dart';

class RecommendationsPanel extends StatefulWidget {
  final RecommendationLearningStatusProvider? learningStatusProvider;

  const RecommendationsPanel({
    super.key,
    this.learningStatusProvider,
  });

  @override
  State<RecommendationsPanel> createState() => _RecommendationsPanelState();
}

class _RecommendationsPanelState extends State<RecommendationsPanel> {
  RecommendationDependencies? _dependencies;
  late final RecommendationLearningController _controller;

  @override
  void initState() {
    super.initState();

    final injectedProvider = widget.learningStatusProvider;
    if (injectedProvider != null) {
      _controller = RecommendationLearningController(
        provider: injectedProvider,
      );
    } else {
      _dependencies = RecommendationDependencies.create();
      _controller = _dependencies!.learningController;
    }

    _controller.addListener(_onControllerChanged);
    _controller.load();
  }

  void _onControllerChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  @override
  void dispose() {
    _controller.removeListener(_onControllerChanged);
    if (_dependencies != null) {
      _dependencies!.dispose();
    } else {
      _controller.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return DashboardPanel(
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(AthenaSpacing.lg),
            child: Row(
              children: [
                const Text(
                  'RECOMENDACIONES ATHENA',
                  style: TextStyle(
                    color: AthenaColors.text,
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const Spacer(),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 6,
                  ),
                  decoration: BoxDecoration(
                    color: AthenaColors.warning.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                      color: AthenaColors.warning.withValues(alpha: 0.45),
                    ),
                  ),
                  child: const Text(
                    'MOTOR EN VALIDACIÓN',
                    style: TextStyle(
                      color: AthenaColors.warning,
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(AthenaSpacing.lg),
              child: _buildBody(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_controller.isLoading) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: AthenaSpacing.md),
            Text(
              'Comprobando el estado del motor de recomendaciones...',
              style: TextStyle(color: AthenaColors.textSecondary),
            ),
          ],
        ),
      );
    }

    if (_controller.error != null) {
      return const Center(
        child: Text(
          'No se pudo consultar el estado del motor de recomendaciones.\n'
          'ATHENA no mostrará señales de inversión sin validación.',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 15,
          ),
        ),
      );
    }

    final status = _controller.status;
    if (status == null) {
      return const Center(
        child: Text(
          'El motor de recomendaciones todavía no está disponible.',
          style: TextStyle(color: AthenaColors.textSecondary),
        ),
      );
    }

    return _buildLearningStatus(status);
  }

  Widget _buildLearningStatus(RecommendationLearningStatus status) {
    final sampleCount = _int(status.performance['sampleCount']) ?? 0;
    final dueCount = _int(status.evaluationSchedule['dueCount']) ?? 0;
    final driftStatus = status.drift?['status']?.toString() ?? 'sin muestra';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'ATHENA todavía no publica recomendaciones activas.',
          style: TextStyle(
            color: AthenaColors.text,
            fontSize: 18,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: AthenaSpacing.sm),
        const Text(
          'Las señales COMPRAR, MANTENER, REDUCIR o VENDER aparecerán aquí '
          'únicamente cuando procedan del motor real y puedan conservar su '
          'evidencia point-in-time para ser evaluadas después.',
          style: TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 14,
            height: 1.4,
          ),
        ),
        const SizedBox(height: AthenaSpacing.lg),
        Wrap(
          spacing: AthenaSpacing.md,
          runSpacing: AthenaSpacing.md,
          children: [
            _metric('Resultados evaluados', '$sampleCount'),
            _metric('Evaluaciones pendientes', '$dueCount'),
            _metric('Deriva del modelo', driftStatus.toUpperCase()),
            _metric(
              'Cambios automáticos',
              status.automaticModelMutation ? 'ACTIVOS' : 'BLOQUEADOS',
            ),
          ],
        ),
        const Spacer(),
        const Text(
          'Estado actual: diagnóstico y aprendizaje. Ninguna calibración se '
          'aplica automáticamente.',
          style: TextStyle(
            color: AthenaColors.warning,
            fontSize: 13,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }

  Widget _metric(String label, String value) {
    return Container(
      constraints: const BoxConstraints(minWidth: 170),
      padding: const EdgeInsets.all(AthenaSpacing.md),
      decoration: BoxDecoration(
        color: AthenaColors.cardSecondary,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: const TextStyle(
              color: AthenaColors.text,
              fontSize: 17,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  int? _int(dynamic value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    if (value is String) {
      return int.tryParse(value.trim());
    }
    return null;
  }
}
