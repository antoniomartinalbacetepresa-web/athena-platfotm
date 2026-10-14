class AuthenticatedPortfolioHistoryEvent {
  static final RegExp _sha256Pattern = RegExp(r'^[0-9a-f]{64}$');
  static const Set<String> _allowedEventTypes = {
    'external_cash_flow',
    'trade_execution',
    'cash_dividend',
    'fee',
    'tax',
    'split_adjustment',
    'corporate_action',
  };

  const AuthenticatedPortfolioHistoryEvent({
    required this.sequence,
    required this.recordHash,
    required this.eventKey,
    required this.portfolioId,
    required this.eventType,
    required this.occurredAt,
    required this.availableAt,
    required this.currency,
    required this.amount,
    required this.instrumentId,
    required this.quantity,
    required this.source,
    required this.sourceRef,
  });

  final int sequence;
  final String recordHash;
  final String eventKey;
  final String portfolioId;
  final String eventType;
  final DateTime occurredAt;
  final DateTime availableAt;
  final String currency;
  final double? amount;
  final String? instrumentId;
  final double? quantity;
  final String source;
  final String sourceRef;

  factory AuthenticatedPortfolioHistoryEvent.fromJson(
    Map<String, dynamic> json,
  ) {
    final sequence = json['sequence'];
    final recordHash = json['recordHash'];
    final eventKey = json['eventKey'];
    final portfolioId = json['portfolioId'];
    final eventType = json['eventType'];
    final occurredAt = _parseTimestamp(json['occurredAt'], 'occurredAt');
    final availableAt = _parseTimestamp(json['availableAt'], 'availableAt');
    final currency = json['currency'];
    final amount = _optionalFiniteNumber(json['amount'], 'amount');
    final instrumentId = json['instrumentId'];
    final quantity = _optionalFiniteNumber(json['quantity'], 'quantity');
    final source = json['source'];
    final sourceRef = json['sourceRef'];

    if (sequence is! int || sequence <= 0) {
      throw const FormatException('Historial con sequence inválida.');
    }
    if (recordHash is! String || !_sha256Pattern.hasMatch(recordHash)) {
      throw const FormatException('Historial con recordHash inválido.');
    }
    if (eventKey is! String || !_sha256Pattern.hasMatch(eventKey)) {
      throw const FormatException('Historial con eventKey inválido.');
    }
    if (portfolioId is! String || portfolioId.trim().isEmpty) {
      throw const FormatException('Historial con portfolioId inválido.');
    }
    if (eventType is! String || !_allowedEventTypes.contains(eventType)) {
      throw const FormatException('Historial con eventType inválido.');
    }
    if (occurredAt.isAfter(availableAt)) {
      throw const FormatException(
        'Historial viola occurredAt <= availableAt.',
      );
    }
    if (currency is! String ||
        !RegExp(r'^[A-Za-z]{3}$').hasMatch(currency)) {
      throw const FormatException('Historial con currency inválida.');
    }
    if (instrumentId != null &&
        (instrumentId is! String || instrumentId.trim().isEmpty)) {
      throw const FormatException('Historial con instrumentId inválido.');
    }
    if (source is! String || source.trim().isEmpty) {
      throw const FormatException('Historial con source inválido.');
    }
    if (sourceRef is! String || sourceRef.trim().isEmpty) {
      throw const FormatException('Historial con sourceRef inválido.');
    }

    return AuthenticatedPortfolioHistoryEvent(
      sequence: sequence,
      recordHash: recordHash,
      eventKey: eventKey,
      portfolioId: portfolioId.trim(),
      eventType: eventType,
      occurredAt: occurredAt,
      availableAt: availableAt,
      currency: currency.toUpperCase(),
      amount: amount,
      instrumentId: instrumentId == null ? null : (instrumentId as String).trim(),
      quantity: quantity,
      source: source.trim(),
      sourceRef: sourceRef.trim(),
    );
  }

  static DateTime _parseTimestamp(Object? raw, String field) {
    if (raw is! String || raw.trim().isEmpty) {
      throw FormatException('Historial con $field inválido.');
    }
    final parsed = DateTime.tryParse(raw);
    if (parsed == null || !raw.contains(RegExp(r'(Z|[+-]\d\d:\d\d)$'))) {
      throw FormatException('Historial con $field sin zona horaria válida.');
    }
    return parsed.toUtc();
  }

  static double? _optionalFiniteNumber(Object? raw, String field) {
    if (raw == null) return null;
    if (raw is! num) {
      throw FormatException('Historial con $field no numérico.');
    }
    final value = raw.toDouble();
    if (!value.isFinite) {
      throw FormatException('Historial con $field no finito.');
    }
    return value;
  }
}

class AuthenticatedPortfolioHistory {
  const AuthenticatedPortfolioHistory({
    required this.portfolioId,
    required this.asOf,
    required this.events,
    required this.hasMore,
  });

  final String portfolioId;
  final DateTime asOf;
  final List<AuthenticatedPortfolioHistoryEvent> events;
  final bool hasMore;

  factory AuthenticatedPortfolioHistory.fromJson(Map<String, dynamic> json) {
    final portfolioId = json['portfolioId'];
    final rawAsOf = json['asOf'];
    final rawEvents = json['events'];
    final eventCount = json['eventCount'];
    final hasMore = json['hasMore'];

    if (portfolioId is! String || portfolioId.trim().isEmpty) {
      throw const FormatException('Historial sin portfolioId válido.');
    }
    final asOf = AuthenticatedPortfolioHistoryEvent._parseTimestamp(
      rawAsOf,
      'asOf',
    );
    if (rawEvents is! List || eventCount is! int || hasMore is! bool) {
      throw const FormatException('Respuesta de historial incompleta.');
    }
    final events = rawEvents.map((item) {
      if (item is! Map<String, dynamic>) {
        throw const FormatException('Evento de historial no válido.');
      }
      return AuthenticatedPortfolioHistoryEvent.fromJson(item);
    }).toList(growable: false);
    if (eventCount != events.length) {
      throw const FormatException('eventCount no coincide con events.');
    }
    if (events.any((event) => event.portfolioId != portfolioId)) {
      throw const FormatException('Historial mezcla portfolioId distintos.');
    }
    if (events.any((event) => event.availableAt.isAfter(asOf))) {
      throw const FormatException('Historial contiene evidencia posterior a asOf.');
    }

    return AuthenticatedPortfolioHistory(
      portfolioId: portfolioId.trim(),
      asOf: asOf,
      events: events,
      hasMore: hasMore,
    );
  }
}
