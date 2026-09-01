import 'market/historical_price.dart';

/// Datos utilizados por ATHENA TYCHE para analizar una acción.
///
/// Este modelo es independiente de cualquier proveedor de datos.
///
/// La información puede proceder de diferentes fuentes y posteriormente
/// ser combinada antes de llegar al motor de análisis.
///
/// Este modelo contiene:
/// - información actual de mercado,
/// - valoración,
/// - crecimiento,
/// - rentabilidad,
/// - balance y deuda,
/// - flujo de caja,
/// - dividendos,
/// - indicadores técnicos,
/// - información de mercado,
/// - información adicional de la empresa,
/// - histórico de precios.
///
/// El modelo NO contiene reglas de inversión ni decisiones de compra/venta.
class StockAnalysisData {
  final String symbol;
  final String companyName;

  // ===========================================================================
  // PRECIO Y MERCADO
  // ===========================================================================

  final double? currentPrice;
  final double? previousClose;
  final double? marketCap;
  final double? enterpriseValue;

  final double? dayChangePercent;
  final double? weekChangePercent;
  final double? monthChangePercent;
  final double? threeMonthChangePercent;
  final double? sixMonthChangePercent;
  final double? yearChangePercent;

  // ===========================================================================
  // VALORACIÓN
  // ===========================================================================

  final double? peRatio;
  final double? forwardPeRatio;
  final double? pegRatio;
  final double? priceToSales;
  final double? priceToBook;
  final double? enterpriseValueToEbitda;

  // ===========================================================================
  // CRECIMIENTO
  // ===========================================================================

  final double? revenueGrowth;
  final double? earningsGrowth;
  final double? epsGrowth;

  // ===========================================================================
  // RENTABILIDAD
  // ===========================================================================

  final double? grossMargin;
  final double? operatingMargin;
  final double? profitMargin;
  final double? returnOnEquity;
  final double? returnOnAssets;

  // ===========================================================================
  // BALANCE Y DEUDA
  // ===========================================================================

  final double? totalDebt;
  final double? totalCash;
  final double? debtToEquity;
  final double? currentRatio;
  final double? quickRatio;

  // ===========================================================================
  // FLUJO DE CAJA
  // ===========================================================================

  final double? operatingCashFlow;
  final double? freeCashFlow;

  // ===========================================================================
  // DIVIDENDO
  // ===========================================================================

  final double? dividendYield;
  final double? dividendPerShare;
  final double? payoutRatio;

  // ===========================================================================
  // INDICADORES TÉCNICOS
  // ===========================================================================

  final double? fiftyTwoWeekHigh;
  final double? fiftyTwoWeekLow;
  final double? movingAverage50;
  final double? movingAverage200;
  final double? relativeStrengthIndex;

  // ===========================================================================
  // HISTÓRICO DE PRECIOS
  // ===========================================================================

  /// Serie histórica de precios utilizada por ATHENA TYCHE.
  ///
  /// Contiene las observaciones históricas disponibles para la acción.
  ///
  /// Una lista vacía significa que todavía no se ha cargado histórico.
  ///
  /// El histórico no constituye por sí mismo una recomendación.
  /// Será utilizado posteriormente por el análisis técnico y por el estudio
  /// de comportamiento del precio.
  final List<HistoricalPrice> historicalPrices;

  // ===========================================================================
  // INFORMACIÓN DE MERCADO
  // ===========================================================================

  final double? beta;
  final double? averageVolume;
  final double? relativeVolume;

  // ===========================================================================
  // INFORMACIÓN ADICIONAL
  // ===========================================================================

  final String? sector;
  final String? industry;
  final String? country;

  // ===========================================================================
  // METADATOS
  // ===========================================================================

  /// Fecha y hora en la que se obtuvieron los datos.
  final DateTime? dataTimestamp;

  /// Fuentes utilizadas para construir este conjunto de datos.
  ///
  /// Ejemplo:
  /// ['Financial Modeling Prep', 'Yahoo Finance']
  final List<String> sources;

  // ===========================================================================
  // CONSTRUCTOR
  // ===========================================================================

  const StockAnalysisData({
    required this.symbol,
    required this.companyName,

    // Precio y mercado.
    this.currentPrice,
    this.previousClose,
    this.marketCap,
    this.enterpriseValue,
    this.dayChangePercent,
    this.weekChangePercent,
    this.monthChangePercent,
    this.threeMonthChangePercent,
    this.sixMonthChangePercent,
    this.yearChangePercent,

    // Valoración.
    this.peRatio,
    this.forwardPeRatio,
    this.pegRatio,
    this.priceToSales,
    this.priceToBook,
    this.enterpriseValueToEbitda,

    // Crecimiento.
    this.revenueGrowth,
    this.earningsGrowth,
    this.epsGrowth,

    // Rentabilidad.
    this.grossMargin,
    this.operatingMargin,
    this.profitMargin,
    this.returnOnEquity,
    this.returnOnAssets,

    // Balance y deuda.
    this.totalDebt,
    this.totalCash,
    this.debtToEquity,
    this.currentRatio,
    this.quickRatio,

    // Flujo de caja.
    this.operatingCashFlow,
    this.freeCashFlow,

    // Dividendos.
    this.dividendYield,
    this.dividendPerShare,
    this.payoutRatio,

    // Indicadores técnicos.
    this.fiftyTwoWeekHigh,
    this.fiftyTwoWeekLow,
    this.movingAverage50,
    this.movingAverage200,
    this.relativeStrengthIndex,

    // Histórico.
    this.historicalPrices = const [],

    // Información de mercado.
    this.beta,
    this.averageVolume,
    this.relativeVolume,

    // Información adicional.
    this.sector,
    this.industry,
    this.country,

    // Metadatos.
    this.dataTimestamp,
    this.sources = const [],
  });

  // ===========================================================================
  // UTILIDADES
  // ===========================================================================

  /// Indica si existe información suficiente para realizar algún análisis.
  ///
  /// El histórico por sí solo NO hace que el modelo se considere con datos
  /// suficientes para el análisis general.
  bool get hasData {
    return currentPrice != null ||
        peRatio != null ||
        revenueGrowth != null ||
        earningsGrowth != null ||
        freeCashFlow != null ||
        movingAverage50 != null ||
        movingAverage200 != null;
  }

  /// Indica si existe información histórica de precios.
  bool get hasHistoricalData {
    return historicalPrices.isNotEmpty;
  }

  // ===========================================================================
  // COPY WITH
  // ===========================================================================

  /// Crea una copia modificando únicamente los valores indicados.
  StockAnalysisData copyWith({
    String? symbol,
    String? companyName,

    double? currentPrice,
    double? previousClose,
    double? marketCap,
    double? enterpriseValue,
    double? dayChangePercent,
    double? weekChangePercent,
    double? monthChangePercent,
    double? threeMonthChangePercent,
    double? sixMonthChangePercent,
    double? yearChangePercent,

    double? peRatio,
    double? forwardPeRatio,
    double? pegRatio,
    double? priceToSales,
    double? priceToBook,
    double? enterpriseValueToEbitda,

    double? revenueGrowth,
    double? earningsGrowth,
    double? epsGrowth,

    double? grossMargin,
    double? operatingMargin,
    double? profitMargin,
    double? returnOnEquity,
    double? returnOnAssets,

    double? totalDebt,
    double? totalCash,
    double? debtToEquity,
    double? currentRatio,
    double? quickRatio,

    double? operatingCashFlow,
    double? freeCashFlow,

    double? dividendYield,
    double? dividendPerShare,
    double? payoutRatio,

    double? fiftyTwoWeekHigh,
    double? fiftyTwoWeekLow,
    double? movingAverage50,
    double? movingAverage200,
    double? relativeStrengthIndex,

    List<HistoricalPrice>? historicalPrices,

    double? beta,
    double? averageVolume,
    double? relativeVolume,

    String? sector,
    String? industry,
    String? country,

    DateTime? dataTimestamp,
    List<String>? sources,
  }) {
    return StockAnalysisData(
      symbol: symbol ?? this.symbol,
      companyName: companyName ?? this.companyName,

      // Precio y mercado.
      currentPrice: currentPrice ?? this.currentPrice,
      previousClose: previousClose ?? this.previousClose,
      marketCap: marketCap ?? this.marketCap,
      enterpriseValue: enterpriseValue ?? this.enterpriseValue,
      dayChangePercent: dayChangePercent ?? this.dayChangePercent,
      weekChangePercent: weekChangePercent ?? this.weekChangePercent,
      monthChangePercent: monthChangePercent ?? this.monthChangePercent,
      threeMonthChangePercent:
          threeMonthChangePercent ?? this.threeMonthChangePercent,
      sixMonthChangePercent:
          sixMonthChangePercent ?? this.sixMonthChangePercent,
      yearChangePercent: yearChangePercent ?? this.yearChangePercent,

      // Valoración.
      peRatio: peRatio ?? this.peRatio,
      forwardPeRatio: forwardPeRatio ?? this.forwardPeRatio,
      pegRatio: pegRatio ?? this.pegRatio,
      priceToSales: priceToSales ?? this.priceToSales,
      priceToBook: priceToBook ?? this.priceToBook,
      enterpriseValueToEbitda:
          enterpriseValueToEbitda ?? this.enterpriseValueToEbitda,

      // Crecimiento.
      revenueGrowth: revenueGrowth ?? this.revenueGrowth,
      earningsGrowth: earningsGrowth ?? this.earningsGrowth,
      epsGrowth: epsGrowth ?? this.epsGrowth,

      // Rentabilidad.
      grossMargin: grossMargin ?? this.grossMargin,
      operatingMargin: operatingMargin ?? this.operatingMargin,
      profitMargin: profitMargin ?? this.profitMargin,
      returnOnEquity: returnOnEquity ?? this.returnOnEquity,
      returnOnAssets: returnOnAssets ?? this.returnOnAssets,

      // Balance y deuda.
      totalDebt: totalDebt ?? this.totalDebt,
      totalCash: totalCash ?? this.totalCash,
      debtToEquity: debtToEquity ?? this.debtToEquity,
      currentRatio: currentRatio ?? this.currentRatio,
      quickRatio: quickRatio ?? this.quickRatio,

      // Flujo de caja.
      operatingCashFlow: operatingCashFlow ?? this.operatingCashFlow,
      freeCashFlow: freeCashFlow ?? this.freeCashFlow,

      // Dividendos.
      dividendYield: dividendYield ?? this.dividendYield,
      dividendPerShare: dividendPerShare ?? this.dividendPerShare,
      payoutRatio: payoutRatio ?? this.payoutRatio,

      // Indicadores técnicos.
      fiftyTwoWeekHigh: fiftyTwoWeekHigh ?? this.fiftyTwoWeekHigh,
      fiftyTwoWeekLow: fiftyTwoWeekLow ?? this.fiftyTwoWeekLow,
      movingAverage50: movingAverage50 ?? this.movingAverage50,
      movingAverage200: movingAverage200 ?? this.movingAverage200,
      relativeStrengthIndex:
          relativeStrengthIndex ?? this.relativeStrengthIndex,

      // Histórico.
      historicalPrices:
          historicalPrices ?? this.historicalPrices,

      // Información de mercado.
      beta: beta ?? this.beta,
      averageVolume: averageVolume ?? this.averageVolume,
      relativeVolume: relativeVolume ?? this.relativeVolume,

      // Información adicional.
      sector: sector ?? this.sector,
      industry: industry ?? this.industry,
      country: country ?? this.country,

      // Metadatos.
      dataTimestamp: dataTimestamp ?? this.dataTimestamp,
      sources: sources ?? this.sources,
    );
  }
}