import 'dart:math' as math;

import 'portfolio_position.dart';

class Portfolio {
  final String id;
  final String name;
  final double initialCapital;
  final String referenceCapitalCurrency;
  final List<PortfolioPosition> positions;
  final DateTime createdAt;

  const Portfolio({
    required this.id,
    required this.name,
    required this.initialCapital,
    this.referenceCapitalCurrency = 'EUR',
    required this.positions,
    required this.createdAt,
  });

  double get investedValue {
    return positions.fold(
      0,
      (total, position) => total + position.investedValue,
    );
  }

  double get currentValue {
    return positions.fold(
      0,
      (total, position) => total + position.currentValue,
    );
  }

  double get profitLoss {
    return currentValue - investedValue;
  }

  double get profitLossPercentage {
    if (investedValue == 0) {
      return 0;
    }

    return (profitLoss / investedValue) * 100;
  }

  /// Parte del capital de referencia que todavía no está representada por el
  /// coste declarado de las posiciones existentes.
  ///
  /// Nunca es negativa: si el coste invertido supera la referencia, el exceso
  /// se expone mediante [referenceCapitalExcess] en lugar de ocultarlo.
  double get referenceCapitalRemaining {
    if (initialCapital <= 0) {
      return 0;
    }
    return math.max(0, initialCapital - investedValue).toDouble();
  }

  /// Coste declarado de posiciones que excede el capital de referencia.
  ///
  /// Este valor es informativo. No implica deuda, efectivo negativo ni margen:
  /// únicamente evita presentar falsamente un "capital no asignado = 0" cuando
  /// la cartera existente rebasa la referencia elegida por el usuario.
  double get referenceCapitalExcess {
    if (initialCapital <= 0) {
      return 0;
    }
    return math.max(0, investedValue - initialCapital).toDouble();
  }

  bool get isOverReferenceCapital => referenceCapitalExcess > 0;

  Portfolio copyWith({
    String? id,
    String? name,
    double? initialCapital,
    String? referenceCapitalCurrency,
    List<PortfolioPosition>? positions,
    DateTime? createdAt,
  }) {
    return Portfolio(
      id: id ?? this.id,
      name: name ?? this.name,
      initialCapital: initialCapital ?? this.initialCapital,
      referenceCapitalCurrency:
          referenceCapitalCurrency ?? this.referenceCapitalCurrency,
      positions: positions ?? this.positions,
      createdAt: createdAt ?? this.createdAt,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'name': name,
      'initialCapital': initialCapital,
      'referenceCapitalCurrency': referenceCapitalCurrency,
      'positions': positions.map((position) => position.toMap()).toList(),
      'createdAt': createdAt.toIso8601String(),
    };
  }

  factory Portfolio.fromMap(Map<String, dynamic> map) {
    final currency = _referenceCurrencyFromMap(map);
    return Portfolio(
      id: map['id'] as String,
      name: map['name'] as String,
      initialCapital: (map['initialCapital'] as num).toDouble(),
      referenceCapitalCurrency: currency,
      positions: (map['positions'] as List<dynamic>)
          .map(
            (position) => PortfolioPosition.fromMap(
              Map<String, dynamic>.from(position as Map),
            ),
          )
          .toList(),
      createdAt: DateTime.parse(map['createdAt'] as String),
    );
  }

  static String _referenceCurrencyFromMap(Map<String, dynamic> map) {
    // Los registros anteriores a la identidad monetaria explícita eran
    // interpretados exclusivamente como EUR por PortfolioPage. La migración
    // conserva esa semántica histórica; no infiere moneda desde posiciones.
    final raw = map['referenceCapitalCurrency'] ?? 'EUR';
    final currency = raw.toString().trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
      throw const FormatException(
        'La moneda del capital de referencia debe ser ISO de tres letras.',
      );
    }
    return currency;
  }

  Map<String, dynamic> toJson() {
    return toMap();
  }

  factory Portfolio.fromJson(Map<String, dynamic> json) {
    return Portfolio.fromMap(json);
  }
}
