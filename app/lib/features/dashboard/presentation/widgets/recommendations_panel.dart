import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_spacing.dart';
import '../../../../core/widgets/dashboard_panel.dart';
import '../../../recommendations/controllers/recommendation_learning_controller.dart';
import '../../../recommendations/data/datasources/athena_backend_professional_dossier_data_source.dart';
import '../../../recommendations/di/recommendation_dependencies.dart';
import '../../../recommendations/models/recommendation_learning_status.dart';
import '../../../recommendations/models/recommendation_production_state.dart';
import '../../../recommendations/models/recommendation_shadow_candidate_snapshot.dart';
import '../../../recommendations/services/recommendation_learning_status_provider.dart';
import '../../../recommendations/services/recommendation_production_state_provider.dart';
import '../../../recommendations/services/recommendation_shadow_candidate_provider.dart';

class RecommendationsPanel extends StatefulWidget {
  final RecommendationLearningStatusProvider? learningStatusProvider;
  final RecommendationShadowCandidateProvider? shadowCandidateProvider;
  final RecommendationProductionStateProvider? productionStateProvider;
  final AthenaBackendProfessionalDossierDataSource? professionalDossierDataSource;

  const RecommendationsPanel({
    super.key,
    this.learningStatusProvider,
    this.shadowCandidateProvider,
    this.productionStateProvider,
    this.professionalDossierDataSource,
  });

  @override
  State<RecommendationsPanel> createState() => _RecommendationsPanelState();
}

class _RecommendationsPanelState extends State<RecommendationsPanel> {
  static const _professionalModuleLabels = <String, String>{
    'expectationsGap': 'EXPECTATIONS GAP',
    'reverseValuation': 'REVERSE VALUATION',
    'scenarioAsymmetry': 'ASIMETRÍA DE ESCENARIOS',
    'catalysts': 'CATALIZADORES',
    'thesisInvalidation': 'INVALIDACIÓN DE TESIS',
    'factorRisk': 'RIESGO FACTORIAL',
    'performanceAttribution': 'PERFORMANCE ATTRIBUTION',
    'investmentJournal': 'DIARIO DE INVERSIÓN',
    'devilsAdvocate': "DEVIL'S ADVOCATE",
    'athenaRadar': 'ATHENA RADAR',
  };

  RecommendationDependencies? _dependencies;
  late final RecommendationLearningController _controller;
  late final RecommendationShadowCandidateProvider _shadowCandidateProvider;
  late final RecommendationProductionStateProvider _productionStateProvider;
  late final AthenaBackendProfessionalDossierDataSource
      _professionalDossierDataSource;
  late final bool _controllerOwnedByDependencies;
  RecommendationShadowCandidateSnapshot? _shadowSnapshot;
  RecommendationProductionState? _productionState;
  ProfessionalDossier? _professionalDossier;
  bool _shadowLoading = true;
  bool _shadowError = false;
  bool _productionLoading = true;
  bool _productionError = false;
  bool _professionalDossierLoading = true;
  bool _professionalDossierError = false;

  bool get _hasProductiveRecommendation =>
      _productionState?.productionRecommendationAvailable == true &&
      _productionState?.recommendation != null;

  @override
  void initState() {
    super.initState();

    if (widget.learningStatusProvider == null ||
        widget.shadowCandidateProvider == null ||
        widget.productionStateProvider == null ||
        widget.professionalDossierDataSource == null) {
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
    _productionStateProvider =
        widget.productionStateProvider ?? _dependencies!.productionDataSource;
    _professionalDossierDataSource = widget.professionalDossierDataSource ??
        _dependencies!.professionalDossierDataSource;

    _controller.addListener(_onControllerChanged);
    _controller.load();
    _loadShadowCandidate();
    _loadProductionState();
    _loadProfessionalDossier();
  }

  Future<void> _loadShadowCandidate() async {
    try {
      final snapshot = await _shadowCandidateProvider.getLatest();
      if (!mounted) return;
      setState(() {
        _shadowSnapshot = snapshot.isShadowSafe ? snapshot : null;
        _shadowError = !snapshot.isShadowSafe;
        _shadowLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _shadowSnapshot = null;
        _shadowError = true;
        _shadowLoading = false;
      });
    }
  }

  Future<void> _loadProductionState() async {
    try {
      final state = await _productionStateProvider.getLatest();
      if (!mounted) return;
      setState(() {
        _productionState = state.isSafe ? state : null;
        _productionError = !state.isSafe;
        _productionLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _productionState = null;
        _productionError = true;
        _productionLoading = false;
      });
    }
  }

  Future<void> _loadProfessionalDossier() async {
    try {
      final dossier = await _professionalDossierDataSource.getLatest();
      if (!mounted) return;
      setState(() {
        _professionalDossier = dossier.isSafe ? dossier : null;
        _professionalDossierError = !dossier.isSafe;
        _professionalDossierLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _professionalDossier = null;
        _professionalDossierError = true;
        _professionalDossierLoading = false;
      });
    }
  }

  void _onControllerChanged() {
    if (mounted) setState(() {});
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
    final productive = _hasProductiveRecommendation;
    final badgeColor = productive ? AthenaColors.success : AthenaColors.warning;
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
                    color: badgeColor.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: badgeColor.withValues(alpha: 0.45)),
                  ),
                  child: Text(
                    productive ? 'PRODUCTIVO AUTORIZADO' : 'APRENDIZAJE SHADOW',
                    style: TextStyle(
                      color: badgeColor,
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
            'No se pudo verificar el aprendizaje de ATHENA. No se mostrarán señales.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AthenaColors.textSecondary, fontSize: 15),
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
          _buildProductionEvidence(),
          const SizedBox(height: AthenaSpacing.lg),
          _buildProfessionalDossierEvidence(),
          const SizedBox(height: AthenaSpacing.lg),
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
                ? 'Las observaciones maduras se comparan con el exceso de retorno real frente al benchmark congelado.'
                : 'Los horizontes 7/30/90/180/365 se evalúan sólo cuando vencen y son conocibles.',
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
            _hasProductiveRecommendation
                ? 'Estado: existe autorización productiva verificable. Ejecución automática deshabilitada.'
                : hasEvidence
                    ? 'Estado: evidencia fuera de muestra acumulándose. Producción bloqueada hasta autorización válida.'
                    : 'Estado: esperando evidencia fuera de muestra suficiente. Producción bloqueada.',
            style: TextStyle(
              color: _hasProductiveRecommendation
                  ? AthenaColors.success
                  : AthenaColors.warning,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildProfessionalDossierEvidence() {
    if (_professionalDossierLoading) {
      return const Text(
        'Verificando dossier profesional PIT…',
        style: TextStyle(color: AthenaColors.textSecondary, fontSize: 13),
      );
    }
    if (_professionalDossierError) {
      return const Text(
        'El dossier profesional no pudo verificarse y no se muestran módulos.',
        style: TextStyle(color: AthenaColors.warning, fontSize: 13),
      );
    }
    final dossier = _professionalDossier;
    if (dossier == null) {
      return const Text(
        'No existe un dossier profesional verificable.',
        style: TextStyle(color: AthenaColors.textSecondary, fontSize: 13),
      );
    }

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
          const Text(
            'DOSSIER PROFESIONAL PIT',
            style: TextStyle(
              color: AthenaColors.text,
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            '${dossier.advisoryStatus.toUpperCase()} · sólo lectura · corte ${_formatDateTime(dossier.asOf)}',
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 4),
          const Text(
            'Los módulos sin evidencia sellada permanecen visibles como no evidenciados y no alteran la recomendación.',
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 12,
              height: 1.35,
            ),
          ),
          const SizedBox(height: AthenaSpacing.md),
          Wrap(
            spacing: AthenaSpacing.sm,
            runSpacing: AthenaSpacing.sm,
            children: _professionalModuleLabels.entries.map((entry) {
              final module = dossier.modules[entry.key]!;
              return Container(
                constraints: const BoxConstraints(minWidth: 190),
                padding: const EdgeInsets.symmetric(
                  horizontal: AthenaSpacing.sm,
                  vertical: 8,
                ),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: AthenaColors.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      entry.value,
                      style: const TextStyle(
                        color: AthenaColors.text,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _professionalStatusLabel(module.status),
                      style: const TextStyle(
                        color: AthenaColors.textSecondary,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              );
            }).toList(growable: false),
          ),
        ],
      ),
    );
  }

  Widget _buildProductionEvidence() {
    if (_productionLoading) {
      return const Text(
        'Verificando autorizaciones productivas…',
        style: TextStyle(color: AthenaColors.textSecondary, fontSize: 13),
      );
    }
    if (_productionError) {
      return const Text(
        'El estado productivo no pudo verificarse; no se muestra ninguna recomendación.',
        style: TextStyle(color: AthenaColors.warning, fontSize: 13),
      );
    }
    final state = _productionState;
    final recommendation = state?.recommendation;
    if (state == null || recommendation == null) {
      return const Text(
        'No existe una recomendación productiva autorizada conocida por ATHENA.',
        style: TextStyle(color: AthenaColors.textSecondary, fontSize: 13),
      );
    }

    final allocation = state.allocation;
    final horizonDays = recommendation.horizonDays;
    final expectedExcessReturn = recommendation.expectedExcessReturn;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AthenaSpacing.md),
      decoration: BoxDecoration(
        color: AthenaColors.cardSecondary,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AthenaColors.success.withValues(alpha: 0.6)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${_actionLabel(recommendation.action)} · ${recommendation.symbol}',
            style: const TextStyle(
              color: AthenaColors.text,
              fontSize: 18,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Autorización productiva verificada · ${_formatDateTime(recommendation.authorizedAt)}',
            style: const TextStyle(color: AthenaColors.success, fontSize: 12),
          ),
          const SizedBox(height: AthenaSpacing.sm),
          Text(
            'Estado de cartera: ${recommendation.policyState}',
            style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 13),
          ),
          if (horizonDays != null) ...[
            const SizedBox(height: 6),
            Text(
              expectedExcessReturn != null
                  ? 'Horizonte validado: $horizonDays días · exceso esperado OOS ${_formatReturn(expectedExcessReturn)}'
                  : 'Horizonte validado: $horizonDays días',
              style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 13),
            ),
          ],
          if (expectedExcessReturn != null) ...[
            const SizedBox(height: 4),
            const Text(
              'Señal fuera de muestra validada; no es una probabilidad ni una garantía de rentabilidad.',
              style: TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 12,
                height: 1.35,
              ),
            ),
          ],
          if (allocation != null) ...[
            const SizedBox(height: 6),
            Text(
              'Asignación autorizada: ${_formatMoney(allocation.targetAmountInBaseCurrency, allocation.baseCurrency)} '
              'sobre ${_formatMoney(allocation.referenceCapital, allocation.baseCurrency)} de referencia '
              '· cambio ${_formatSignedMoney(allocation.deltaAmountInBaseCurrency, allocation.baseCurrency)}',
              style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 13),
            ),
          ],
          const SizedBox(height: AthenaSpacing.sm),
          const Text(
            'No habilita ejecución de órdenes ni trading automático.',
            style: TextStyle(
              color: AthenaColors.warning,
              fontSize: 12,
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
            'Fuera de producción. No constituye una recomendación ni una orden.',
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
    if (raw is! List || raw.isEmpty) return const <Widget>[];
    final labels = <String>[];
    for (final item in raw.take(3)) {
      if (item is! Map) continue;
      final feature = item['feature']?.toString().trim() ?? '';
      final contribution = _finiteDouble(item['contribution']);
      if (feature.isEmpty || contribution == null) continue;
      labels.add(
        '$feature ${contribution >= 0 ? '+' : ''}${(contribution * 100).toStringAsFixed(2)} pp',
      );
    }
    if (labels.isEmpty) return const <Widget>[];
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
            style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 12),
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

  String _professionalStatusLabel(String status) {
    if (status == 'not_yet_evidenced') return 'SIN EVIDENCIA SELLADA';
    return status.replaceAll('_', ' ').toUpperCase();
  }

  String _displayCount(int? value) => value?.toString() ?? '—';

  String _actionLabel(String action) {
    switch (action) {
      case 'buy':
        return 'COMPRAR';
      case 'hold':
        return 'MANTENER';
      case 'reduce':
        return 'REDUCIR';
      case 'sell':
        return 'VENDER';
      default:
        return action.toUpperCase();
    }
  }

  String _formatDateTime(DateTime value) =>
      '${value.toUtc().day.toString().padLeft(2, '0')}/'
      '${value.toUtc().month.toString().padLeft(2, '0')}/'
      '${value.toUtc().year} '
      '${value.toUtc().hour.toString().padLeft(2, '0')}:'
      '${value.toUtc().minute.toString().padLeft(2, '0')} UTC';

  String _formatMoney(double value, String currency) =>
      '${value.toStringAsFixed(2)} $currency';

  String _formatSignedMoney(double value, String currency) =>
      '${value >= 0 ? '+' : ''}${value.toStringAsFixed(2)} $currency';

  String _formatReturn(double? value) {
    if (value == null || !value.isFinite) return '—';
    final percentage = value * 100;
    return '${percentage >= 0 ? '+' : ''}${percentage.toStringAsFixed(2)}%';
  }

  double? _finiteDouble(dynamic value) {
    if (value is bool) return null;
    final parsed = value is num
        ? value.toDouble()
        : double.tryParse(value?.toString() ?? '');
    return parsed != null && parsed.isFinite ? parsed : null;
  }

  int? _nonNegativeInt(dynamic value) {
    if (value is bool) return null;
    int? parsed;
    if (value is int) {
      parsed = value;
    } else if (value is num) {
      if (!value.isFinite || value != value.truncateToDouble()) return null;
      parsed = value.toInt();
    } else if (value is String) {
      parsed = int.tryParse(value.trim());
    }
    return parsed != null && parsed >= 0 ? parsed : null;
  }
}
