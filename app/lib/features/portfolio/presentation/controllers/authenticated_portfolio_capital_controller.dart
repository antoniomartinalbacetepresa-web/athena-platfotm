import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../auth/services/auth_session.dart';
import '../../../profile/models/user_preferences.dart';
import '../../../profile/services/user_preferences_service.dart';

/// Read-only Portfolio projection of owner-scoped encrypted Profile preferences.
///
/// Portfolio must not create a second personal-preferences store. Profile remains
/// authoritative and this controller deliberately fails closed when preferences
/// are invalid or temporarily unavailable. The verified base currency is kept
/// independently from optional available capital so authenticated FX valuation
/// does not depend on the user having configured a cash amount.
///
/// Authentication authority is part of the state contract: capital/currency from
/// one owner are cleared synchronously on logout or owner replacement, and a new
/// authenticated owner is reloaded without allowing an older request to win.
class AuthenticatedPortfolioCapitalController extends ChangeNotifier {
  AuthenticatedPortfolioCapitalController({
    required this.preferencesService,
    AuthSession? session,
  }) : _session = session ?? AuthSession.instance {
    _session.addListener(_onAuthorityChanged);
  }

  @visibleForTesting
  final UserPreferencesService preferencesService;
  final AuthSession _session;

  bool _isLoading = false;
  bool _sessionRejected = false;
  String? _error;
  double? _availableCapital;
  String? _currency;
  int _loadGeneration = 0;

  bool get isLoading => _isLoading;
  bool get sessionRejected => _sessionRejected;
  String? get error => _error;
  double? get availableCapital => _availableCapital;

  /// Verified Profile base currency, even when available capital is not set.
  String? get currency => _currency;
  bool get hasVerifiedBaseCurrency => _currency != null && _error == null;
  bool get hasVerifiedCapital =>
      _availableCapital != null && hasVerifiedBaseCurrency;

  void _onAuthorityChanged() {
    _loadGeneration += 1;
    _isLoading = false;
    _sessionRejected = false;
    _error = null;
    _availableCapital = null;
    _currency = null;
    notifyListeners();

    if (_session.isAuthenticated) {
      unawaited(load());
    }
  }

  Future<void> load() async {
    final generation = ++_loadGeneration;
    _isLoading = true;
    _sessionRejected = false;
    _error = null;
    _availableCapital = null;
    _currency = null;
    notifyListeners();

    try {
      final UserPreferences? preferences = await preferencesService.load();
      if (generation != _loadGeneration) return;
      if (preferences == null) return;

      final currency = preferences.baseCurrency.trim().toUpperCase();
      if (!RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
        throw const FormatException('Moneda base autenticada no válida.');
      }
      _currency = currency;

      final capital = preferences.availableCapital;
      if (capital != null) {
        if (!capital.isFinite ||
            capital < 0 ||
            capital > UserPreferences.maxAvailableCapital) {
          throw const FormatException('Capital disponible autenticado no válido.');
        }
        _availableCapital = capital;
      }
    } on UserPreferencesSessionRejectedException {
      if (generation != _loadGeneration) return;
      _sessionRejected = true;
      _availableCapital = null;
      _currency = null;
    } on UserPreferencesAuthorityChangedException {
      if (generation != _loadGeneration) return;
      _error = null;
      _availableCapital = null;
      _currency = null;
    } catch (_) {
      if (generation != _loadGeneration) return;
      _error = 'No se pudo verificar el capital disponible de tu perfil.';
      _availableCapital = null;
      _currency = null;
    } finally {
      if (generation == _loadGeneration) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  @override
  void dispose() {
    _session.removeListener(_onAuthorityChanged);
    super.dispose();
  }
}
