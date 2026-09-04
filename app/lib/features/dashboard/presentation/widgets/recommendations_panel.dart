import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_spacing.dart';
import '../../../../core/widgets/dashboard_panel.dart';
import '../../../recommendations/controllers/recommendation_learning_controller.dart';
import '../../../recommendations/di/recommendation_dependencies.dart';
import '../../../recommendations/models/recommendation_learning_status.dart';
import '../../../recommendations/services/recommendation_learning_status_provider.dart';

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
                const Expanded(
                  child: Text(
                    'RECOMENDACIONES ATHENA',
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: AthenaColors.text,
                      fontSize: 24,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
                const SizedBox(width: AthenaSpacing.md),
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
                    'APRENDIZAJE SHADOW',
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
          Expanded(child: _buildBody()),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_controller.isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_controller.error != null) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(AthenaSpacing.lg),
          child: Text(
            'No se pudo verificar el aprendizaje de ATHENA.\n'
            'No se mostrarán señales mientras el estado no sea verificable.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 15,
            ),
          ),
        ),
      );
    }

    final status = _controller.status;
    if (status == null || !status.isShadowSafe) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(AthenaSpacing.lg),
          child: Text(
            'Estado de recomendaciones no verificable.',
            style: TextStyle(color: AthenaColors.textSecondary),
          ),
        ),
      );
    }

    return _buildLearningStatus(status);
  }

  Widget _buildLearningStatus(RecommendationLearningStatus status) {
    final persisted = status.persistedShadowCandidateCount;
    final evaluatedCandidates = status.evaluatedShadowCandidateCount;
    final observations = status.evaluatedShadowObservationCount;
    final dueCount = _nonNegativeInt(status.evaluationSchedule['dueCount']);
    final hasEvidence = status.hasMatureShadowEvidence;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(AthenaSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            hasEvidence
                ? 'ATHENA ya está midiendo candidatos con resultados reales.'
                : 'ATHENA está generando y siguiendo candidatos en sombra.',
            style: const TextStyle(
              color: AthenaColors.text,
              fontSize: 18,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: AthenaSpacing.sm),
          Text(
            hasEvidence
                ? 'Las observaciones maduras se comparan con el exceso de retorno real frente al benchmark congelado. Aún no implican una señal de inversión.'
                : 'Los resultados de 7, 30, 90, 180 y 365 días se incorporarán únicamente cuando hayan vencido y sean conocidos por ATHENA.',
            style: const TextStyle(
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
              _metric('Candidatos shadow', _displayCount(persisted)),
              _metric('Candidatos evaluados', _displayCount(evaluatedCandidates)),
              _metric('Observaciones maduras', _displayCount(observations)),
              _metric('Evaluaciones pendientes', _displayCount(dueCount)),
            ],
          ),
          const SizedBox(height: AthenaSpacing.lg),
          Text(
            hasEvidence
                ? 'Estado: evidencia fuera de muestra acumulándose. Recomendaciones productivas aún bloqueadas.'
                : 'Estado: esperando evidencia fuera de muestra suficiente. Recomendaciones productivas bloqueadas.',
            style: const TextStyle(
              color: AthenaColors.warning,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
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

  String _displayCount(int? value) => value?.toString() ?? '—';

  int? _nonNegativeInt(dynamic value) {
    if (value is bool) {
      return null;
    }
    int? parsed;
    if (value is int) {
      parsed = value;
    } else if (value is num) {
      if (!value.isFinite || value != value.truncateToDouble()) {
        return null;
      }
      parsed = value.toInt();
    } else if (value is String) {
      parsed = int.tryParse(value.trim());
    }
    return parsed != null && parsed >= 0 ? parsed : null;
  }
}
