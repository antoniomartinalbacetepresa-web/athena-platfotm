import 'package:flutter/foundation.dart';

import '../../../profile/models/user_preferences.dart';
import '../../../profile/services/user_preferences_service.dart';

/// Read-only Portfolio projection of owner-scoped encrypted Profile capital.
///
/// Portfolio must not create a second capital store. Profile preferences remain
/// authoritative and this controller deliberately fails closed when they are
/// absent, invalid or temporarily unavailable.
class AuthenticatedPortfolioCapitalController extends ChangeNotifier {
  AuthenticatedPortfolioCapitalController({
    required UserPreferencesService preferencesService,
  }) : _preferencesService = preferencesService;

  final UserPreferencesService _preferencesService;

  bool _isLoading = false;
  bool _sessionRejected = false;
  String? _error;
  double? _availableCapital;
  String? _currency;

  bool get isLoading => _isLoading;
  bool get sessionRejected => _sessionRejected;
  String? get error => _error;
  double? get availableCapital => _availableCapital;
  String? get currency => _currency;
  bool get hasVerifiedCapital => _availableCapital != null && _currency != null;

  Future<void> load() async {
    _isLoading = true;
    _sessionRejected = false;
    _error = null;
    _availableCapital = null;
    _currency = null;
    notifyListeners();

    try {
      final UserPreferences? preferences = await _preferencesService.load();
      final capital = preferences?.availableCapital;
      if (capital != null) {
        if (!capital.isFinite || capital < 0 || capital > UserPreferences.maxAvailableCapital) {
          throw const FormatException('Capital disponible autenticado no válido.');
        }
        final currency = preferences!.baseCurrency.trim().toUpperCase();
        if (!RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
          throw const FormatException('Moneda base autenticada no válida.');
        }
        _availableCapital = capital;
        _currency = currency;
      }
    } on UserPreferencesSessionRejectedException {
      _sessionRejected = true;
      _availableCapital = null;
      _currency = null;
    } catch (_) {
      _error = 'No se pudo verificar el capital disponible de tu perfil.';
      _availableCapital = null;
      _currency = null;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }
}
