import 'package:flutter/material.dart';

import '../../../core/theme/athena_colors.dart';
import '../../../core/theme/athena_radius.dart';
import '../../../core/theme/athena_spacing.dart';
import '../../recommendations/data/datasources/athena_backend_recommendation_shadow_candidate_data_source.dart';
import '../../recommendations/models/recommendation_allocation_request_context.dart';
import '../../recommendations/models/recommendation_shadow_candidate_snapshot.dart';
import '../di/portfolio_allocation_dependencies.dart';
import '../models/portfolio_allocation_policy.dart';
import '../models/portfolio_position.dart';
import '../services/portfolio_reference_capital_canonicalization_service.dart';

/// Panel no operativo que enlaza evidencia shadow real con la frontera de
/// allocation autorizada del backend.
///
/// El capital declarado por el usuario conserva su importe y moneda original.
/// Antes de consultar allocation se normaliza a la única moneda económica de
/// ATHENA (USD) mediante FX verificable del backend. El shadow sólo aporta
/// identidad/horizonte/corte PIT y nunca se transforma en autoridad de compra.
class AthenaAllocationPanel extends StatefulWidget {
  final double referenceCapital;
  final String referenceCapitalCurrency;
  final List<PortfolioPosition> positions;
  final double? currentUnallocatedCapital;
  final bool currentCapitalComparable;

  const AthenaAllocationPanel({
    super.key,
    required this.referenceCapital,
    required this.referenceCapitalCurrency,
    required this.positions,
    required this.currentUnallocatedCapital,
    required this.currentCapitalComparable,
  });

  @override
  State<AthenaAllocationPanel> createState() => _AthenaAllocationPanelState();
}

class _AthenaAllocationPanelState extends State<AthenaAllocationPanel> {
  late final PortfolioAllocationDependencies _dependencies;
  late final AthenaBackendRecommendationShadowCandidateDataSource
      _shadowDataSource;

  RecommendationShadowCandidateSnapshot? _shadowSnapshot;
  PortfolioCanonicalReferenceCapital? _canonicalReferenceCapital;
  int? _selectedHorizonDays;
  bool _isLoadingEvidence = true;
  bool _isCanonicalizingCapital = false;
  String? _evidenceError;

  @override
  void initState() {
    super.initState();
    _dependencies = PortfolioAllocationDependencies.create();
    _shadowDataSource = AthenaBackendRecommendationShadowCandidateDataSource(
      baseUrl: _dependencies.policyDataSource.baseUrl,
    );
    _dependencies.policyController.addListener(_onControllerChanged);
    _dependencies.allocationController.addListener(_onControllerChanged);
    _loadEvidence();
  }

  @override
  void didUpdateWidget(covariant AthenaAllocationPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.referenceCapital != widget.referenceCapital ||
        oldWidget.referenceCapitalCurrency != widget.referenceCapitalCurrency ||
        oldWidget.positions != widget.positions) {
      _canonicalReferenceCapital = null;
      _dependencies.allocationController.clear();
    }
  }

  @override
  void dispose() {
    _dependencies.policyController.removeListener(_onControllerChanged);
    _dependencies.allocationController.removeListener(_onControllerChanged);
    _shadowDataSource.dispose();
    _dependencies.dispose();
    super.dispose();
  }

  void _onControllerChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _loadEvidence() async {
    setState(() {
      _isLoadingEvidence = true;
      _evidenceError = null;
      _shadowSnapshot = null;
      _selectedHorizonDays = null;
      _canonicalReferenceCapital = null;
    });
    _dependencies.allocationController.clear();
    try {
      await _dependencies.policyController.load();
      if (_dependencies.policyController.error != null) {
        throw StateError(_dependencies.policyController.error!);
      }
      final snapshot = await _shadowDataSource.getLatest();
      if (!snapshot.isShadowSafe) {
        throw StateError(
          'La evidencia shadow no cumple el contrato no_advice/fail-closed.',
        );
      }
      if (!mounted) return;
      setState(() {
        _shadowSnapshot = snapshot;
        _isLoadingEvidence = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _shadowSnapshot = null;
        _selectedHorizonDays = null;
        _isLoadingEvidence = false;
        _evidenceError = error.toString();
      });
    }
  }

  void _selectPolicy(String? policyId) {
    _dependencies.allocationController.clear();
    _canonicalReferenceCapital = null;
    if (policyId == null) {
      _dependencies.policyController.clearSelection();
      return;
    }
    _dependencies.policyController.selectPolicy(policyId);
  }

  void _selectHorizon(int? horizonDays) {
    _dependencies.allocationController.clear();
    _canonicalReferenceCapital = null;
    setState(() => _selectedHorizonDays = horizonDays);
  }

  Future<void> _requestAllocation() async {
    final snapshot = _shadowSnapshot;
    final policy = _dependencies.policyController.selectedPolicy;
    final horizonDays = _selectedHorizonDays;
    if (snapshot == null || policy == null || horizonDays == null) return;
    if (!_referenceCapitalIsValid || !_policyUsesCanonicalCurrency) return;

    setState(() {
      _isCanonicalizingCapital = true;
      _evidenceError = null;
      _canonicalReferenceCapital = null;
    });
    _dependencies.allocationController.clear();

    try {
      final canonical = await _dependencies
          .referenceCapitalCanonicalizationService
          .canonicalize(
        amount: widget.referenceCapital,
        currency: widget.referenceCapitalCurrency,
      );

      // The request cutoff is created only after FX retrieval. Therefore the
      // capital conversion is already known at the PIT boundary sent to the
      // backend and is never retrospectively injected into an older cutoff.
      final requestAsOf = DateTime.now().toUtc();
      final fxRetrievedAt = canonical.fxEvidence?.retrievedAt.toUtc();
      if (fxRetrievedAt != null && fxRetrievedAt.isAfter(requestAsOf)) {
        throw StateError(
          'La evidencia FX fue recuperada después del corte de allocation.',
        );
      }

      final context = RecommendationAllocationRequestContext.fromShadowSnapshot(
        snapshot: snapshot,
        horizonDays: horizonDays,
        requestAsOf: requestAsOf,
      );
      await _dependencies.allocationController
          .loadFromRecommendationContextWithPolicy(
        context: context,
        allocationPolicy: policy,
        referenceCapital: canonical.amountInCanonicalCurrency,
        positions: widget.positions,
      );
      if (!mounted) return;
      setState(() => _canonicalReferenceCapital = canonical);
    } catch (error) {
      _dependencies.allocationController.clear();
      if (!mounted) return;
      setState(() {
        _canonicalReferenceCapital = null;
        _evidenceError = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() => _isCanonicalizingCapital = false);
      }
    }
  }

  bool get _referenceCapitalIsValid =>
      widget.referenceCapital.isFinite && widget.referenceCapital > 0;

  bool get _policyUsesCanonicalCurrency {
    final policy = _dependencies.policyController.selectedPolicy;
    if (policy == null) return false;
    return policy.baseCurrency ==
        PortfolioCanonicalReferenceCapital.canonicalCurrency;
  }

  List<int> get _availableHorizons {
    final candidate = _shadowSnapshot?.candidate;
    if (candidate == null) return const [];
    final values = candidate.horizons.keys.where((days) => days > 0).toList();
    values.sort();
    return values;
  }

  bool get _canRequestAllocation =>
      !_isLoadingEvidence &&
      !_isCanonicalizingCapital &&
      !_dependencies.allocationController.isLoading &&
      _shadowSnapshot?.candidate != null &&
      _selectedHorizonDays != null &&
      _dependencies.policyController.selectedPolicy != null &&
      _referenceCapitalIsValid &&
      _policyUsesCanonicalCurrency;

  @override
  Widget build(BuildContext context) {
    final policyController = _dependencies.policyController;
    final allocationController = _dependencies.allocationController;
    final candidate = allocationController.candidate;
    final selectedPolicy = policyController.selectedPolicy;
    final shadow = _shadowSnapshot?.candidate;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AthenaSpacing.lg),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
        border: Border.all(color: AthenaColors.border),
      ),
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
              _NonOperationalBadge(),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            _referenceCapitalIsValid
                ? 'Capital declarado: ${_money(widget.referenceCapital, widget.referenceCapitalCurrency)}. '
                    'ATHENA calcula allocation únicamente en USD y conserva la moneda original para presentación.'
                : 'Define un capital de referencia positivo antes de solicitar una planificación.',
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 13,
              height: 1.4,
            ),
          ),
          if (widget.currentCapitalComparable &&
              widget.currentUnallocatedCapital != null) ...[
            const SizedBox(height: 6),
            Text(
              'Capital actualmente no asignado: ${_money(widget.currentUnallocatedCapital!, widget.referenceCapitalCurrency)}.',
              style: const TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 12,
              ),
            ),
          ],
          const SizedBox(height: AthenaSpacing.md),
          if (_isLoadingEvidence || policyController.isLoading)
            const LinearProgressIndicator()
          else ...[
            if (_evidenceError != null) ...[
              _message(_cleanError(_evidenceError!), isError: true),
              const SizedBox(height: AthenaSpacing.md),
            ],
            if (policyController.error != null) ...[
              _message(_cleanError(policyController.error!), isError: true),
              const SizedBox(height: AthenaSpacing.md),
            ],
            if (policyController.hasNoPolicies) ...[
              _message(
                'No hay políticas de asignación persistidas. ATHENA no crea una política por defecto.',
              ),
              const SizedBox(height: AthenaSpacing.md),
            ],
            if (_shadowSnapshot != null && shadow == null) ...[
              _message(
                'No existe candidato shadow conocido en el corte actual. No se solicita allocation.',
              ),
              const SizedBox(height: AthenaSpacing.md),
            ],
            if (shadow != null) ...[
              Text(
                'Evidencia shadow: ${shadow.symbol} · observado ${_dateTime(shadow.asOf.toLocal())}',
                style: const TextStyle(
                  color: AthenaColors.textSecondary,
                  fontSize: 12,
                ),
              ),
              const SizedBox(height: AthenaSpacing.md),
              Wrap(
                spacing: AthenaSpacing.md,
                runSpacing: AthenaSpacing.md,
                children: [
                  SizedBox(
                    width: 300,
                    child: DropdownButtonFormField<int>(
                      value: _selectedHorizonDays,
                      decoration: const InputDecoration(
                        labelText: 'Horizonte real del candidato',
                      ),
                      items: _availableHorizons
                          .map(
                            (days) => DropdownMenuItem<int>(
                              value: days,
                              child: Text('$days días'),
                            ),
                          )
                          .toList(growable: false),
                      onChanged: _availableHorizons.isEmpty
                          ? null
                          : _selectHorizon,
                    ),
                  ),
                  SizedBox(
                    width: 360,
                    child: DropdownButtonFormField<String>(
                      value: selectedPolicy?.policyId,
                      decoration: const InputDecoration(
                        labelText: 'Política persistida',
                      ),
                      items: policyController.policies
                          .map(
                            (policy) => DropdownMenuItem<String>(
                              value: policy.policyId,
                              child: Text(
                                '${policy.policyId} · ${policy.baseCurrency}',
                              ),
                            ),
                          )
                          .toList(growable: false),
                      onChanged: policyController.policies.isEmpty
                          ? null
                          : _selectPolicy,
                    ),
                  ),
                ],
              ),
              if (selectedPolicy != null && !_policyUsesCanonicalCurrency) ...[
                const SizedBox(height: AthenaSpacing.md),
                _message(
                  'La política ${selectedPolicy.policyId} usa ${selectedPolicy.baseCurrency}. La frontera económica de ATHENA sólo admite políticas USD; la moneda del usuario se convierte por FX verificable.',
                  isError: true,
                ),
              ],
              const SizedBox(height: AthenaSpacing.md),
              ElevatedButton.icon(
                onPressed: _canRequestAllocation ? _requestAllocation : null,
                icon: _isCanonicalizingCapital || allocationController.isLoading
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.calculate_outlined, size: 18),
                label: const Text('Verificar planificación'),
              ),
            ],
          ],
          if (_canonicalReferenceCapital != null) ...[
            const SizedBox(height: AthenaSpacing.md),
            _canonicalCapitalEvidence(_canonicalReferenceCapital!),
          ],
          if (allocationController.blockedReason != null) ...[
            const SizedBox(height: AthenaSpacing.md),
            _message(
              'Allocation bloqueada por backend: ${allocationController.blockedReason}',
            ),
          ],
          if (allocationController.error != null) ...[
            const SizedBox(height: AthenaSpacing.md),
            _message(_cleanError(allocationController.error!), isError: true),
          ],
          if (candidate != null) ...[
            const SizedBox(height: AthenaSpacing.lg),
            const Divider(color: AthenaColors.border),
            const SizedBox(height: AthenaSpacing.md),
            const Text(
              'PLANIFICACIÓN VERIFICADA · NO OPERATIVA',
              style: TextStyle(
                color: AthenaColors.text,
                fontSize: 13,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: AthenaSpacing.md),
            Wrap(
              spacing: 28,
              runSpacing: 18,
              children: [
                _metric(
                  'Referencia canónica',
                  _money(candidate.referenceCapital, candidate.baseCurrency),
                ),
                _metric(
                  'Valor invertido verificable',
                  _money(candidate.investedPositionsValueInBaseCurrency,
                      candidate.baseCurrency),
                ),
                _metric(
                  'Posición del instrumento',
                  _money(candidate.currentPositionValueInBaseCurrency,
                      candidate.baseCurrency),
                ),
                _metric(
                  'Exceso sobre referencia',
                  _money(candidate.excessOverReferenceCapital,
                      candidate.baseCurrency),
                ),
                _metric(
                  'Déficit frente a referencia',
                  _money(candidate.shortfallVsReferenceCapital,
                      candidate.baseCurrency),
                ),
                _metric(
                  'Peso objetivo del instrumento',
                  '${(candidate.targetWeight * 100).toStringAsFixed(2)} %',
                ),
                _metric(
                  'Importe objetivo',
                  _money(candidate.targetAmountInBaseCurrency,
                      candidate.baseCurrency),
                ),
                _metric(
                  'Cambio modelado',
                  _signedMoney(candidate.deltaAmountInBaseCurrency,
                      candidate.baseCurrency),
                ),
                _metric(
                  'Acción modelada',
                  '${candidate.action.toUpperCase()} · no operativa',
                ),
              ],
            ),
            const SizedBox(height: AthenaSpacing.md),
            const Text(
              'El valor invertido verificable incluye sólo posiciones valoradas por el backend. No representa efectivo, pasivos ni patrimonio neto total.',
              style: TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 11,
                height: 1.35,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              'Corte PIT: ${_dateTime(candidate.asOf.toLocal())} · política: ${selectedPolicy?.policyId ?? 'no disponible'} · fingerprint: ${_shortFingerprint(candidate.allocationCandidateFingerprint)}',
              style: const TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 11,
                height: 1.35,
              ),
            ),
          ],
          const SizedBox(height: AthenaSpacing.md),
          const Text(
            'Este panel no ejecuta operaciones ni transforma evidencia shadow en consejo. El backend mantiene la autoridad sobre acción, valoración, correlaciones y contrato económico.',
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 12,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }

  Widget _canonicalCapitalEvidence(PortfolioCanonicalReferenceCapital capital) {
    if (!capital.usedFx) {
      return _message(
        'Capital canónico: ${_money(capital.amountInCanonicalCurrency, PortfolioCanonicalReferenceCapital.canonicalCurrency)} · no requiere FX.',
      );
    }
    final fx = capital.fxEvidence!;
    return _message(
      'Capital canónico: ${_money(capital.amountInCanonicalCurrency, PortfolioCanonicalReferenceCapital.canonicalCurrency)} · '
      '${fx.baseCurrency}/${fx.quoteCurrency} ${fx.rate.toStringAsFixed(6)} · '
      '${fx.sourceProvider} · observado ${_dateTime(fx.observedAt.toLocal())} · '
      'recuperado ${_dateTime(fx.retrievedAt.toLocal())}.',
    );
  }

  static Widget _message(String text, {bool isError = false}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AthenaSpacing.md),
      decoration: BoxDecoration(
        color: AthenaColors.cardSecondary,
        borderRadius: BorderRadius.circular(AthenaRadius.md),
        border: Border.all(
          color: isError ? const Color(0xFFFF5C5C) : AthenaColors.border,
        ),
      ),
      child: Text(
        text,
        style: const TextStyle(
          color: AthenaColors.textSecondary,
          fontSize: 12,
          height: 1.35,
        ),
      ),
    );
  }

  static Widget _metric(String title, String value) {
    return SizedBox(
      width: 210,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            title,
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: const TextStyle(
              color: AthenaColors.text,
              fontSize: 15,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  static String _money(num value, String currency) =>
      '${value.toStringAsFixed(2)} ${currency.toUpperCase()}';

  static String _signedMoney(num value, String currency) =>
      '${value > 0 ? '+' : ''}${value.toStringAsFixed(2)} ${currency.toUpperCase()}';

  static String _shortFingerprint(String value) {
    final normalized = value.trim().toLowerCase();
    if (normalized.length < 12) return normalized;
    return '${normalized.substring(0, 12)}…';
  }

  static String _dateTime(DateTime value) {
    String two(int number) => number.toString().padLeft(2, '0');
    return '${two(value.day)}/${two(value.month)}/${value.year} '
        '${two(value.hour)}:${two(value.minute)}';
  }

  static String _cleanError(String value) {
    var result = value.trim();
    for (final prefix in const [
      'Exception: ',
      'Bad state: ',
      'Invalid argument(s): ',
    ]) {
      if (result.startsWith(prefix)) result = result.substring(prefix.length);
    }
    return result;
  }
}

class _NonOperationalBadge extends StatelessWidget {
  const _NonOperationalBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(
        color: AthenaColors.cardSecondary,
        borderRadius: BorderRadius.circular(AthenaRadius.sm),
        border: Border.all(color: AthenaColors.border),
      ),
      child: const Text(
        'NO OPERATIVO',
        style: TextStyle(
          color: AthenaColors.textSecondary,
          fontSize: 10,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}
