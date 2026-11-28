/// Read-only PIT diagnostics. These records never authorize production or orders.
class MarketHistoryGap {
  const MarketHistoryGap({
    required this.instrumentId,
    required this.symbol,
    required this.reason,
    required this.sourceCount,
    required this.bestSourceProvider,
    required this.bestHistorySpanDays,
    required this.bestMaximumGapDays,
  });

  static const reasons = <String>{
    'no_observations',
    'insufficient_span',
    'discontinuous_source',
    'stale_source',
  };

  final int instrumentId;
  final String symbol;
  final String reason;
  final int sourceCount;
  final String? bestSourceProvider;
  final double? bestHistorySpanDays;
  final double? bestMaximumGapDays;

  String get reasonLabel => switch (reason) {
        'no_observations' => 'Sin observaciones PIT',
        'insufficient_span' => 'Menos de 365 días',
        'discontinuous_source' => 'Histórico discontinuo',
        'stale_source' => 'Fuente sin vigencia',
        _ => 'Diagnóstico no disponible',
      };

  factory MarketHistoryGap.fromMap(Map<String, dynamic> map) {
    final id = map['instrumentId'];
    final symbol = map['symbol'];
    final reason = map['reason'];
    final sources = map['sourceCount'];
    final provider = map['bestSourceProvider'];
    final span = map['bestHistorySpanDays'];
    final gap = map['bestMaximumGapDays'];
    if (id is! int ||
        id <= 0 ||
        symbol is! String ||
        symbol.trim().isEmpty ||
        reason is! String ||
        !reasons.contains(reason) ||
        sources is! int ||
        sources < 0 ||
        (provider != null &&
            (provider is! String || provider.trim().isEmpty)) ||
        (sources == 0 && provider != null) ||
        (span != null && (span is! num || !span.isFinite || span < 0)) ||
        (gap != null && (gap is! num || !gap.isFinite || gap < 0))) {
      throw const FormatException('Bloqueo histórico PIT inválido.');
    }
    return MarketHistoryGap(
      instrumentId: id,
      symbol: symbol.trim(),
      reason: reason,
      sourceCount: sources,
      bestSourceProvider: provider as String?,
      bestHistorySpanDays: (span as num?)?.toDouble(),
      bestMaximumGapDays: (gap as num?)?.toDouble(),
    );
  }
}

class MarketHistoryGapsPage {
  const MarketHistoryGapsPage({
    required this.asOf,
    required this.totalBlockingCount,
    required this.blockingByReason,
    required this.limit,
    required this.offset,
    required this.items,
  });

  final DateTime asOf;
  final int totalBlockingCount;
  final Map<String, int> blockingByReason;
  final int limit;
  final int offset;
  final List<MarketHistoryGap> items;

  factory MarketHistoryGapsPage.fromMap(
    Map<String, dynamic> map, {
    required DateTime expectedAsOf,
  }) {
    final asOfText = map['asOf'];
    final asOf = asOfText is String &&
            RegExp(r'(?:Z|[+-]\d{2}:\d{2})$').hasMatch(asOfText)
        ? DateTime.tryParse(asOfText)
        : null;
    final total = map['totalBlockingCount'];
    final limit = map['limit'];
    final offset = map['offset'];
    final rawCounts = map['blockingByReason'];
    final rawItems = map['items'];
    if (map['status'] != 'diagnostic_only' ||
        map['pointInTimeCutoffApplied'] != true ||
        map['productionEvidenceClaimed'] != false ||
        asOf == null ||
        !asOf.isAtSameMomentAs(expectedAsOf) ||
        total is! int ||
        total < 0 ||
        limit is! int ||
        limit < 1 ||
        limit > 1000 ||
        offset is! int ||
        offset < 0 ||
        rawCounts is! Map ||
        rawItems is! List ||
        rawItems.length > limit) {
      throw const FormatException('Diagnóstico histórico PIT incoherente.');
    }
    final counts = <String, int>{};
    for (final reason in MarketHistoryGap.reasons) {
      final count = rawCounts[reason];
      if (count is! int || count < 0) {
        throw const FormatException('Recuentos de bloqueos PIT inválidos.');
      }
      counts[reason] = count;
    }
    if (rawCounts.length != MarketHistoryGap.reasons.length ||
        counts.values.fold<int>(0, (sum, count) => sum + count) != total) {
      throw const FormatException('Recuentos de bloqueos PIT incoherentes.');
    }
    final items = <MarketHistoryGap>[];
    for (final raw in rawItems) {
      if (raw is! Map) {
        throw const FormatException('Instrumento histórico PIT inválido.');
      }
      final item = MarketHistoryGap.fromMap(Map<String, dynamic>.from(raw));
      if (counts[item.reason] == 0) {
        throw const FormatException('Motivo de bloqueo PIT incoherente.');
      }
      items.add(item);
    }
    if ((items.isNotEmpty && offset + items.length > total) ||
        (offset < total && items.isEmpty) ||
        items.map((item) => item.instrumentId).toSet().length != items.length) {
      throw const FormatException('Página de bloqueos PIT incoherente.');
    }
    return MarketHistoryGapsPage(
      asOf: asOf,
      totalBlockingCount: total,
      blockingByReason: Map<String, int>.unmodifiable(counts),
      limit: limit,
      offset: offset,
      items: List<MarketHistoryGap>.unmodifiable(items),
    );
  }
}
