import 'package:flutter/foundation.dart';

import '../../../recommendations/models/recommendation_allocation_request_context.dart';
import '../../data/athena_backend_portfolio_allocation_authority_data_source.dart';
import '../../data/athena_backend_portfolio_allocation_data_source.dart';
import '../../models/portfolio_position.dart';

class PortfolioAllocationController extends ChangeNotifier {
  final AthenaBackendPortfolioAllocationAuthorityDataSource authorityDataSource;
  final AthenaBackendPortfolioAllocationDataSource allocationDataSource;

  AthenaBackendPortfolioAllocationCandidate? _candidate;
  bool _isLoading = false;
  String? _blockedReason;
  String? _error;

  PortfolioAllocationController({
    required this.authorityDataSource,
    required this.allocationDataSource,
  });

  AthenaBackendPortfolioAllocationCandidate? get candidate => _candidate;
  bool get isLoading => _isLoading;
  String? get blockedReason => _blockedReason;
  String? get error => _error;
  bool get isReady => _candidate != null && _blockedReason == null && _error == null;

  Future<void> loadFromRecommendationContext({
    required RecommendationAllocationRequestContext context,
    required String allocationPolicyId,
    required double referenceCapital,
    required String baseCurrency,
    required List<PortfolioPosition> positions,
  }) {
    return load(
      instrumentId: context.instrumentId,
      horizonDays: context.horizonDays,
      allocationPolicyId: allocationPolicyId,
      referenceCapital: referenceCapital,
      baseCurrency: baseCurrency,
      positions: positions,
      asOf: context.requestAsOf,
    );
  }

  Future<void> load({
    required int instrumentId,
    required int horizonDays,
    required String allocationPolicyId,
    required double referenceCapital,
    required String baseCurrency,
    required List<PortfolioPosition> positions,
    required DateTime asOf,
  }) async {
    _candidate = null;
    _blockedReason = null;
    _error = null;
    _isLoading = true;
    notifyListeners();

    try {
      if (instrumentId <= 0) {
        throw ArgumentError.value(instrumentId, 'instrumentId');
      }
      if (horizonDays <= 0) {
        throw ArgumentError.value(horizonDays, 'horizonDays');
      }
      if (!referenceCapital.isFinite || referenceCapital <= 0) {
        throw ArgumentError.value(referenceCapital, 'referenceCapital');
      }
      final currency = baseCurrency.trim().toUpperCase();
      if (!RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
        throw ArgumentError.value(baseCurrency, 'baseCurrency');
      }
      final cutoff = asOf.toUtc();
      final heldInstrumentIds = <int>[];
      final seen = <int>{};
      for (final position in positions) {
        final id = position.databaseInstrumentId;
        if (!position.hasVerifiedCanonicalIdentity || id == null || id <= 0) {
          throw StateError(
            'Allocation requiere identidad canónica verificable en toda la cartera.',
          );
        }
        if (!position.hasVerifiedPositionProvenance) {
          throw StateError(
            'Allocation requiere provenance verificable en toda la cartera.',
          );
        }
        if (!position.shares.isFinite || position.shares <= 0) {
          throw StateError('Allocation requiere cantidades positivas y finitas.');
        }
        if (!seen.add(id)) {
          throw StateError(
            'Allocation no admite instrumentos canónicos duplicados.',
          );
        }
        heldInstrumentIds.add(id);
      }

      final authority = await authorityDataSource.resolve(
        instrumentId: instrumentId,
        horizonDays: horizonDays,
        heldInstrumentIds: heldInstrumentIds,
        asOf: cutoff,
      );
      if (!authority.ready) {
        final reason = authority.reason?.trim();
        if (reason == null || reason.isEmpty) {
          throw StateError(
            'El backend bloqueó allocation sin una razón verificable.',
          );
        }
        _blockedReason = reason;
        return;
      }

      final actionFingerprint = authority.actionCandidateFingerprint;
      if (actionFingerprint == null || actionFingerprint.isEmpty) {
        throw StateError(
          'La autoridad de allocation no devolvió una acción sellada.',
        );
      }

      _candidate = await allocationDataSource.buildAuthorizedCandidate(
        uncertaintyBoundActionCandidateFingerprint: actionFingerprint,
        allocationPolicyId: allocationPolicyId,
        referenceCapital: referenceCapital,
        baseCurrency: currency,
        positions: positions,
        correlationEvidenceFingerprints:
            authority.correlationEvidenceFingerprints,
        asOf: cutoff,
      );
    } catch (error) {
      _candidate = null;
      _blockedReason = null;
      _error = error.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  void clear() {
    _candidate = null;
    _blockedReason = null;
    _error = null;
    _isLoading = false;
    notifyListeners();
  }
}
