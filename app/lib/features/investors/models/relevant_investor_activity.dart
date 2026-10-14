class RelevantInvestorHolding {
  final String issuerName;
  final String titleOfClass;
  final String cusip;
  final int valueThousandsUsd;
  final double shareOrPrincipalAmount;
  final String shareOrPrincipalType;
  final String? putCall;
  final String investmentDiscretion;
  final double votingSole;
  final double votingShared;
  final double votingNone;

  const RelevantInvestorHolding({
    required this.issuerName,
    required this.titleOfClass,
    required this.cusip,
    required this.valueThousandsUsd,
    required this.shareOrPrincipalAmount,
    required this.shareOrPrincipalType,
    required this.putCall,
    required this.investmentDiscretion,
    required this.votingSole,
    required this.votingShared,
    required this.votingNone,
  });

  factory RelevantInvestorHolding.fromMap(Map<String, dynamic> map) {
    String requiredText(String key) {
      final value = map[key]?.toString().trim() ?? '';
      if (value.isEmpty) throw FormatException('$key es obligatorio.');
      return value;
    }

    double nonNegativeNumber(String key) {
      final value = map[key];
      if (value is! num) throw FormatException('$key debe ser numérico.');
      final parsed = value.toDouble();
      if (!parsed.isFinite || parsed < 0) {
        throw FormatException('$key debe ser finito y no negativo.');
      }
      return parsed;
    }

    final cusip = requiredText('cusip').toUpperCase();
    if (!RegExp(r'^[A-Z0-9*@#]{9}$').hasMatch(cusip)) {
      throw const FormatException('CUSIP 13F inválido.');
    }
    final value = map['valueThousandsUsd'];
    if (value is! int || value < 0) {
      throw const FormatException('valueThousandsUsd debe ser entero no negativo.');
    }
    final quantityType = requiredText('shareOrPrincipalType').toUpperCase();
    if (quantityType != 'SH' && quantityType != 'PRN') {
      throw const FormatException('Tipo de cantidad 13F no soportado.');
    }
    if (map['identityResolved'] != false ||
        map['canonicalInstrumentId'] != null ||
        map['ticker'] != null) {
      throw const FormatException(
        'Un holding 13F no puede inventar identidad canónica o ticker.',
      );
    }
    final voting = map['votingAuthority'];
    if (voting is! Map) {
      throw const FormatException('votingAuthority es obligatorio.');
    }
    final votingMap = Map<String, dynamic>.from(voting);

    return RelevantInvestorHolding(
      issuerName: requiredText('issuerName'),
      titleOfClass: requiredText('titleOfClass'),
      cusip: cusip,
      valueThousandsUsd: value,
      shareOrPrincipalAmount: nonNegativeNumber('shareOrPrincipalAmount'),
      shareOrPrincipalType: quantityType,
      putCall: map['putCall']?.toString().trim().isEmpty == false
          ? map['putCall'].toString().trim()
          : null,
      investmentDiscretion: requiredText('investmentDiscretion'),
      votingSole: _nonNegativeFrom(votingMap, 'sole'),
      votingShared: _nonNegativeFrom(votingMap, 'shared'),
      votingNone: _nonNegativeFrom(votingMap, 'none'),
    );
  }

  static double _nonNegativeFrom(Map<String, dynamic> map, String key) {
    final value = map[key];
    if (value is! num) throw FormatException('votingAuthority.$key debe ser numérico.');
    final parsed = value.toDouble();
    if (!parsed.isFinite || parsed < 0) {
      throw FormatException('votingAuthority.$key debe ser finito y no negativo.');
    }
    return parsed;
  }
}

class RelevantInvestorActivity {
  final String cik;
  final String form;
  final String accessionNumber;
  final DateTime positionDate;
  final DateTime filingDate;
  final DateTime publicationDateTime;
  final DateTime retrievedAt;
  final String sourceUrl;
  final String sourceProvider;
  final String valueUnit;
  final List<RelevantInvestorHolding> holdings;

  const RelevantInvestorActivity({
    required this.cik,
    required this.form,
    required this.accessionNumber,
    required this.positionDate,
    required this.filingDate,
    required this.publicationDateTime,
    required this.retrievedAt,
    required this.sourceUrl,
    required this.sourceProvider,
    required this.valueUnit,
    required this.holdings,
  });

  String get recommendationPolicy => 'no_advice';
  bool get productionEligible => false;
  bool get athenaRecommendationInfluence => false;
  bool get automaticScoring => false;
  bool get automaticTrading => false;
  bool get isWeightingReady => false;

  factory RelevantInvestorActivity.fromApi({
    required String cik,
    required Map<String, dynamic> envelope,
  }) {
    final normalizedCik = cik.trim();
    if (!RegExp(r'^\d{1,10}$').hasMatch(normalizedCik)) {
      throw const FormatException('CIK inválido.');
    }
    final dataRaw = envelope['data'];
    if (dataRaw is! Map) throw const FormatException('Falta data 13F.');
    final data = Map<String, dynamic>.from(dataRaw);

    String requiredText(String key) {
      final value = data[key]?.toString().trim() ?? '';
      if (value.isEmpty) throw FormatException('$key es obligatorio.');
      return value;
    }

    DateTime dateOnly(String key) {
      final text = requiredText(key);
      final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(text);
      if (match == null) throw FormatException('$key no es fecha AAAA-MM-DD.');
      final result = DateTime.utc(
        int.parse(match.group(1)!),
        int.parse(match.group(2)!),
        int.parse(match.group(3)!),
      );
      if (result.toIso8601String().substring(0, 10) != text) {
        throw FormatException('$key contiene una fecha inválida.');
      }
      return result;
    }

    DateTime utcTimestamp(String key) {
      final text = requiredText(key);
      if (!text.endsWith('Z')) {
        throw FormatException('$key debe estar expresado explícitamente en UTC.');
      }
      final result = DateTime.tryParse(text);
      if (result == null) throw FormatException('$key no es timestamp ISO válido.');
      return result.toUtc();
    }

    if (data['advisoryStatus'] != 'no_advice' ||
        data['productionEligible'] != false ||
        data['athenaRecommendationInfluence'] != false ||
        data['automaticScoring'] != false ||
        data['automaticTrading'] != false) {
      throw const FormatException(
        'La actividad 13F no puede influir en recomendación, scoring o trading.',
      );
    }
    final identity = data['identityPolicy'];
    if (identity is! Map ||
        identity['canonicalInstrumentResolved'] != false ||
        identity['isWeightingReady'] != false ||
        identity['identifier'] != 'cusip_as_reported') {
      throw const FormatException('La política de identidad 13F no es fail-closed.');
    }

    final publication = utcTimestamp('publicationDateTime');
    final retrieved = utcTimestamp('retrievedAt');
    if (retrieved.isBefore(publication)) {
      throw const FormatException('La recuperación 13F precede a su publicación.');
    }
    final sourceProvider = requiredText('sourceProvider');
    if (sourceProvider != 'SEC EDGAR') {
      throw const FormatException('La actividad institucional no procede de SEC EDGAR.');
    }
    final sourceUrl = requiredText('sourceUrl');
    _requireSecArchiveUrl(sourceUrl);

    final rawHoldings = data['holdings'];
    if (rawHoldings is! List || rawHoldings.isEmpty) {
      throw const FormatException('El 13F no contiene holdings verificables.');
    }
    final holdings = rawHoldings
        .map((item) {
          if (item is! Map) throw const FormatException('Holding 13F inválido.');
          return RelevantInvestorHolding.fromMap(Map<String, dynamic>.from(item));
        })
        .toList(growable: false);
    final holdingCount = data['holdingCount'];
    if (holdingCount is! int || holdingCount != holdings.length) {
      throw const FormatException('holdingCount no coincide con los holdings recibidos.');
    }

    final selectedRaw = envelope['selectedFiling'];
    if (selectedRaw is! Map) throw const FormatException('Falta selectedFiling.');
    final selected = Map<String, dynamic>.from(selectedRaw);
    final form = requiredText('form');
    final accession = requiredText('accessionNumber');
    if (selected['form']?.toString() != form ||
        selected['accessionNumber']?.toString() != accession ||
        selected['reportDate']?.toString() != requiredText('positionDate') ||
        selected['filingDate']?.toString() != requiredText('filingDate')) {
      throw const FormatException('selectedFiling no coincide con el documento 13F parseado.');
    }
    if (form != '13F-HR' && form != '13F-HR/A') {
      throw const FormatException('Formulario institucional no soportado.');
    }

    return RelevantInvestorActivity(
      cik: normalizedCik,
      form: form,
      accessionNumber: accession,
      positionDate: dateOnly('positionDate'),
      filingDate: dateOnly('filingDate'),
      publicationDateTime: publication,
      retrievedAt: retrieved,
      sourceUrl: sourceUrl,
      sourceProvider: sourceProvider,
      valueUnit: requiredText('valueUnit'),
      holdings: List.unmodifiable(holdings),
    );
  }

  static void _requireSecArchiveUrl(String url) {
    final uri = Uri.tryParse(url);
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host.toLowerCase() != 'www.sec.gov' ||
        !uri.path.startsWith('/Archives/edgar/data/') ||
        uri.hasQuery ||
        uri.hasFragment) {
      throw const FormatException('URL SEC EDGAR no aprobada.');
    }
  }
}
