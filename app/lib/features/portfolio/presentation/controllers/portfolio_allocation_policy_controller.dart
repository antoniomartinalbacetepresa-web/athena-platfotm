import 'package:flutter/foundation.dart';

import '../../data/athena_backend_portfolio_allocation_policy_data_source.dart';
import '../../models/portfolio_allocation_policy.dart';

class PortfolioAllocationPolicyController extends ChangeNotifier {
  final AthenaBackendPortfolioAllocationPolicyDataSource dataSource;

  List<PortfolioAllocationPolicy> _policies = const [];
  PortfolioAllocationPolicy? _selectedPolicy;
  bool _isLoading = false;
  String? _error;

  PortfolioAllocationPolicyController({required this.dataSource});

  List<PortfolioAllocationPolicy> get policies => _policies;
  PortfolioAllocationPolicy? get selectedPolicy => _selectedPolicy;
  bool get isLoading => _isLoading;
  String? get error => _error;
  bool get requiresExplicitSelection => _policies.isNotEmpty && _selectedPolicy == null;
  bool get hasNoPolicies => !_isLoading && _error == null && _policies.isEmpty;

  Future<void> load() async {
    _policies = const [];
    _selectedPolicy = null;
    _error = null;
    _isLoading = true;
    notifyListeners();
    try {
      _policies = await dataSource.listPolicies();
      _selectedPolicy = null;
    } catch (error) {
      _policies = const [];
      _selectedPolicy = null;
      _error = error.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  void selectPolicy(String policyId) {
    final normalized = policyId.trim();
    if (normalized.isEmpty) {
      throw ArgumentError.value(policyId, 'policyId');
    }
    PortfolioAllocationPolicy? resolved;
    for (final policy in _policies) {
      if (policy.policyId == normalized) {
        resolved = policy;
        break;
      }
    }
    if (resolved == null) {
      throw StateError('La política seleccionada no pertenece al registro verificado cargado.');
    }
    _selectedPolicy = resolved;
    _error = null;
    notifyListeners();
  }

  void clearSelection() {
    _selectedPolicy = null;
    notifyListeners();
  }

  void clear() {
    _policies = const [];
    _selectedPolicy = null;
    _isLoading = false;
    _error = null;
    notifyListeners();
  }
}
