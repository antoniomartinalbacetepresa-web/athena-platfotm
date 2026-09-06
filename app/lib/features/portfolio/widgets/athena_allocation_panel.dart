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

/// Panel no operativo que enlaza evidencia shadow real con la frontera de
/// allocation autorizada del backend.
///
/// El usuario debe seleccionar explícitamente horizonte y política. El shadow
/// sólo aporta contexto para consultar al backend; nunca se trata como una
/// recomendación ni como autoridad para asignar capital.
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
  int? _selectedHorizonDays;
  bool _isLoadingEvidence = true;
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
    if (policyId == null) {
      _dependencies.policyController.clearSelection();
      return;
    }
    _dependencies.policyController.selectPolicy(policyId);
  }

  void _selectHorizon(int? horizonDays) {
    _dependencies.allocationController.clear();
    setState(() => _selectedHorizonDays = horizonDays);
  }

  Future<void> _requestAllocation() async {
    final snapshot = _shadowSnapshot;
    final policy = _dependencies.policyController.selectedPolicy;
    final horizonDays = _selectedHorizonDays;
    if (snapshot == null || policy == null || horizonDays == null) return;
    if (!_referenceCapitalIsValid || !_policyCurrencyMatchesReference) return;

    try {
      final context = RecommendationAllocationRequestContext.fromShadowSnapshot(
        snapshot: snapshot,
        horizonDays: horizonDays,
        requestAsOf: snapshot.asOf,
      );
      await _dependencies.allocationController
          .loadFromRecommendationContextWithPolicy(
        context: context,
        allocationPolicy: policy,
        referenceCapital: widget.referenceCapital,
        positions: widget.positions,
      );
    } catch (error) {
      _dependencies.allocationController.clear();
      if (!mounted) return;
      setState(() => _evidenceError = error.toString());
    }
  }

  bool get _referenceCapitalIsValid =>
      widget.referenceCapital.isFinite && widget.referenceCapital > 0;

  bool get _policyCurrencyMatchesReference {
    final policy = _dependencies.policyController.selectedPolicy;
    if (policy == null) return false;
    return policy.baseCurrency == widget.referenceCapitalCurrency.toUpperCase();
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
      !_dependencies.allocationController.isLoading &&
      _shadowSnapshot?.candidate != null &&
      _selectedHorizonDays != null &&
      _dependencies.policyController.selectedPolicy != null &&
      _referenceCapitalIsValid &&
      _policyCurrencyMatchesReference;

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
                ? 'Capital de referencia: ${_money(widget.referenceCapital, widget.referenceCapitalCurrency)}. '
                    '${widget.currentCapitalComparable ? 'Capital actualmente no asignado: ${_money(widget.currentUnallocatedCapital ?? 0, widget.referenceCapitalCurrency)}.' : 'El disponible actual no se usa como comparable hasta disponer de valoración histórica verificable.'}'
                : 'Define un capital de referencia positivo antes de solicitar una planificación.',
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 13,
              height: 1.4,
            ),
          ),
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
                'No existe candidato shadow conocido en el corte PIT actual. No se solicita allocation.',
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
              if (selectedPolicy != null && !_policyCurrencyMatchesReference) ...[
                const SizedBox(height: AthenaSpacing.md),
                _message(
                  'La política seleccionada usa ${selectedPolicy.baseCurrency}, pero el capital de referencia está registrado en ${widget.referenceCapitalCurrency}. ATHENA bloquea la planificación para no reinterpretar importes entre monedas.',
                  isError: true,
                ),
              ],
              const SizedBox(height: AthenaSpacing.md),
              ElevatedButton.icon(
                onPressed: _canRequestAllocation ? _requestAllocation : null,
                icon: allocationController.isLoading
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
          if (allocationController.blockedReason != null) ...[
            const SizedBox(height: AthenaSpacing.md),
            _message(
              'Allocation bloqueada por backend: ${allocationController.blockedReason}',
            ),
          ],
          if (allocationController.error != null) ...[
            const SizedBox(height: AthenaSpacing.md),
            _message(
              _cleanError(allocationController.error!),
              isError: true,
            ),
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
                  'Referencia',
                  _money(candidate.referenceCapital, candidate.baseCurrency),
                ),
                _metric(
                  'Valor actual cartera',
                  _money(
                    candidate.currentPositionValueInBaseCurrency,
                    candidate.baseCurrency,
                  ),
                ),
                _metric(
                  'Exceso sobre referencia',
                  _money(
                    candidate.excessOverReferenceCapital,
                    candidate.baseCurrency,
                  ),
                ),
                _metric(
                  'Déficit frente a referencia',
                  _money(
                    candidate.shortfallVsReferenceCapital,
                    candidate.baseCurrency,
                  ),
                ),
                _metric(
                  'Peso objetivo del instrumento',
                  '${(candidate.targetWeight * 100).toStringAsFixed(2)} %',
                ),
                _metric(
                  'Importe objetivo',
                  _money(
                    candidate.targetAmountInBaseCurrency,
                    candidate.baseCurrency,
                  ),
                ),
                _metric(
                  'Cambio modelado',
                  _signedMoney(
                    candidate.deltaAmountInBaseCurrency,
                    candidate.baseCurrency,
                  ),
                ),
                _metric(
                  'Acción modelada',
                  '${candidate.action.toUpperCase()} · no operativa',
                ),
              ],
            ),
            const SizedBox(height: AthenaSpacing.md),
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
            'Este panel no ejecuta operaciones y no transforma evidencia shadow en consejo. Toda planificación requiere acción sellada, política persistida, valoración y correlaciones verificadas por backend.',
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
    return '${two(value.day)}/${two(value.month)}/${value.year} ${two(value.hour)}:${two(value.minute)}';
  }

  static String _cleanError(String value) {
    return value
        .replaceFirst('Exception: ', '')
        .replaceFirst('Bad state: ', '')
        .trim();
  }
}

class _NonOperationalBadge extends StatelessWidget {
  const _NonOperationalBadge();

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
        'NO OPERATIVO',
        style: TextStyle(
          color: AthenaColors.textSecondary,
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}
