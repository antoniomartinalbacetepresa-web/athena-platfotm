import '../models/auth_account.dart';

class AuthSession {
  AuthSession._();

  static final AuthSession instance = AuthSession._();

  String? _accessToken;
  AuthAccount? _account;

  String? get accessToken => _accessToken;
  AuthAccount? get account => _account;
  bool get isAuthenticated => _accessToken != null && _account != null;

  void establish({required String accessToken, required AuthAccount account}) {
    final token = accessToken.trim();
    if (token.isEmpty || !account.isActive) {
      throw ArgumentError('La sesión autenticada no es válida.');
    }
    _accessToken = token;
    _account = account;
  }

  void clear() {
    _accessToken = null;
    _account = null;
  }
}
