import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_spacing.dart';
import '../../../../core/widgets/dashboard_panel.dart';
import '../../../recommendations/controllers/recommendation_learning_controller.dart';
import '../../../recommendations/di/recommendation_dependencies.dart';
import '../../../recommendations/models/recommendation_learning_status.dart';
import '../../../recommendations/models/recommendation_shadow_candidate_snapshot.dart';
import '../../../recommendations/services/recommendation_learning_status_provider.dart';
import '../../../recommendations/services/recommendation_shadow_candidate_provider.dart';

class RecommendationsPanel extends StatefulWidget {
  final RecommendationLearningStatusProvider? learningStatusProvider;
  final RecommendationShadowCandidateProvider? shadowCandidateProvider;

  const RecommendationsPanel({
    super.key,
    this.learningStatusProvider,
    this.shadowCandidateProvider,
  });

  @override
  State<RecommendationsPanel> createState() => _RecommendationsPanelState();
}

class _RecommendationsPanelState extends State<RecommendationsPanel> {
  RecommendationDependencies? _dependencies;
  late final RecommendationLearningController _controller;
  late final RecommendationShadowCandidateProvider _shadowCandidateProvider;
  late final bool _controllerOwnedByDependencies;
  RecommendationShadowCandidateSnapshot? _shadowSnapshot;
  bool _shadowLoading = true;
  bool _shadowError = false;

  @override
  void initState() {
    super.initState();

    if (widget.learningStatusProvider == null ||
        widget.shadowCandidateProvider == null) {
      _dependencies = RecommendationDependencies.create();
    }

    final injectedLearning = widget.learningStatusProvider;
    if (injectedLearning != null) {
      _controller = RecommendationLearningController(provider: injectedLearning);
      _controllerOwnedByDependencies = false;
    } else {
      _controller = _dependencies!.learningController;
      _controllerOwnedByDependencies = true;
    }

    _shadowCandidateProvider = widget.shadowCandidateProvider ??
        _dependencies!.shadowCandidateDataSource;

    _controller.addListener(_onControllerChanged);
    _controller.load();
    _loadShadowCandidate();
  }

  Future<void> _loadShadowCandidate() async {
    try {
      final snapshot = await _shadowCandidateProvider.getLatest();
      if (!mounted) {
        return;
      }
      setState(() {
        _shadowSnapshot = snapshot.isShadowSafe ? snapshot : null;
        _shadowError = !snapshot.isShadowSafe;
        _shadowLoading = false;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _shadowSnapshot = null;
        _shadowError = true;
        _shadowLoading = false;
      });
    }
  }

  void _onControllerChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  @override
  void dispose() {
    _controller.removeListener(_onControllerChanged);
    if (!_controllerOwnedByDependencies) {
      _controller.dispose();
    }
    _dependencies?.dispose();
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
          _buildShadowCandidateEvidence(),
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

  Widget _buildShadowCandidateEvidence() {
    if (_shadowLoading) {
      return const Text(
        'Verificando el último candidato shadow conocido…',
        style: TextStyle(color: AthenaColors.textSecondary, fontSize: 13),
      );
    }
    if (_shadowError) {
      return const Text(
        'El candidato shadow actual no pudo verificarse y no se muestra.',
        style: TextStyle(color: AthenaColors.warning, fontSize: 13),
      );
    }
    final snapshot = _shadowSnapshot;
    final candidate = snapshot?.candidate;
    if (snapshot == null || candidate == null) {
      return const Text(
        'Todavía no existe un candidato shadow verificable conocido por ATHENA.',
        style: TextStyle(color: AthenaColors.textSecondary, fontSize: 13),
      );
    }

    final horizons = candidate.inferredHorizons;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AthenaSpacing.md),
      decoration: BoxDecoration(
        color: AthenaColors.cardSecondary,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AthenaColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Candidato shadow verificable · ${candidate.symbol}',
            style: const TextStyle(
              color: AthenaColors.text,
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Estimaciones fuera de producción. No constituyen una recomendación ni una orden de inversión.',
            style: TextStyle(
              color: AthenaColors.warning,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          if (horizons.isNotEmpty) ...[
            const SizedBox(height: AthenaSpacing.sm),
            Wrap(
              spacing: AthenaSpacing.md,
              runSpacing: AthenaSpacing.sm,
              children: horizons
                  .map(
                    (item) => Text(
                      '${item.horizonDays}d: ${_formatReturn(item.expectedExcessReturn)} exceso esperado',
                      style: const TextStyle(
                        color: AthenaColors.textSecondary,
                        fontSize: 13,
                      ),
                    ),
                  )
                  .toList(growable: false),
            ),
            ..._explanationWidgets(horizons.first),
          ],
        ],
      ),
    );
  }

  List<Widget> _explanationWidgets(RecommendationShadowHorizon horizon) {
    final raw = horizon.explanation['largestAbsoluteContributors'];
    if (raw is! List || raw.isEmpty) {
      return const <Widget>[];
    }
    final labels = <String>[];
    for (final item in raw.take(3)) {
      if (item is! Map) {
        continue;
      }
      final feature = item['feature']?.toString().trim() ?? '';
      final contribution = _finiteDouble(item['contribution']);
      if (feature.isEmpty || contribution == null) {
        continue;
      }
      labels.add('$feature ${contribution >= 0 ? '+' : ''}${(contribution * 100).toStringAsFixed(2)} pp');
    }
    if (labels.isEmpty) {
      return const <Widget>[];
    }
    return [
      const SizedBox(height: AthenaSpacing.sm),
      Text(
        'Factores principales (${horizon.horizonDays}d): ${labels.join(' · ')}',
        style: const TextStyle(
          color: AthenaColors.textSecondary,
          fontSize: 12,
          height: 1.35,
        ),
      ),
    ];
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

  String _formatReturn(double? value) {
    if (value == null || !value.isFinite) {
      return '—';
    }
    final percentage = value * 100;
    return '${percentage >= 0 ? '+' : ''}${percentage.toStringAsFixed(2)}%';
  }

  double? _finiteDouble(dynamic value) {
    if (value is bool) {
      return null;
    }
    final parsed = value is num ? value.toDouble() : double.tryParse(value?.toString() ?? '');
    return parsed != null && parsed.isFinite ? parsed : null;
  }

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
