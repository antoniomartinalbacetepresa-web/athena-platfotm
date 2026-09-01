import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/portfolio.dart';

class PortfolioRepository {
  static const String _portfolioKey = 'athena_tyche_portfolio';

  final SharedPreferencesAsync _preferences =
      SharedPreferencesAsync();

  Future<void> savePortfolio(Portfolio portfolio) async {
    final jsonString = jsonEncode(
      portfolio.toJson(),
    );

    await _preferences.setString(
      _portfolioKey,
      jsonString,
    );
  }

  Future<Portfolio?> loadPortfolio() async {
    final jsonString = await _preferences.getString(
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
    await _preferences.remove(
      _portfolioKey,
    );
  }
}