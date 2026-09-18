import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/portfolio.dart';

class PortfolioRepository {
  static const String _portfolioKey = 'athena_tyche_portfolio';

  PortfolioRepository({SharedPreferencesAsync? preferences})
      : _preferences = preferences;

  final SharedPreferencesAsync? _preferences;

  SharedPreferencesAsync get _storage => _preferences ?? SharedPreferencesAsync();

  Future<void> savePortfolio(Portfolio portfolio) async {
    final jsonString = jsonEncode(
      portfolio.toJson(),
    );

    await _storage.setString(
      _portfolioKey,
      jsonString,
    );
  }

  Future<Portfolio?> loadPortfolio() async {
    final jsonString = await _storage.getString(
      _portfolioKey,
    );

    if (jsonString == null || jsonString.isEmpty) {
      return null;
    }

    try {
      final decoded = jsonDecode(jsonString);

      if (decoded is! Map) {
        return null;
      }

      return Portfolio.fromJson(
        Map<String, dynamic>.from(decoded),
      );
    } catch (_) {
      return null;
    }
  }

  Future<void> deletePortfolio() async {
    await _storage.remove(
      _portfolioKey,
    );
  }
}
