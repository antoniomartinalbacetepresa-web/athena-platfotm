/// Regiones principales utilizadas por ATHENA TYCHE
/// para construir el contexto global del mercado.
///
/// Las regiones tienen el mismo nivel dentro del modelo.
/// Su peso se utiliza únicamente durante la construcción
/// del contexto global.
enum MarketRegion {
  america,
  europe,
  asia,
}

extension MarketRegionExtension on MarketRegion {
  /// Nombre mostrado al usuario.
  String get label {
    switch (this) {
      case MarketRegion.america:
        return 'AMÉRICA';

      case MarketRegion.europe:
        return 'EUROPA';

      case MarketRegion.asia:
        return 'ASIA';
    }
  }

  /// Identificador estable utilizado internamente.
  String get key {
    switch (this) {
      case MarketRegion.america:
        return 'america';

      case MarketRegion.europe:
        return 'europe';

      case MarketRegion.asia:
        return 'asia';
    }
  }
}