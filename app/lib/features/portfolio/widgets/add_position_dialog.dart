import 'package:flutter/material.dart';

import '../../../core/theme/athena_colors.dart';
import '../../../core/theme/athena_radius.dart';
import '../../../core/theme/athena_spacing.dart';
import '../../market/di/market_dependencies.dart';
import '../../market/repositories/market_repository.dart';
import '../data/athena_backend_portfolio_identity_data_source.dart';
import '../models/portfolio_position.dart';
import '../services/portfolio_identity_enrichment_service.dart';

class AddPositionDialog extends StatefulWidget {
  final MarketRepository? marketRepository;
  final PortfolioIdentityResolver? identityResolver;

  const AddPositionDialog({
    super.key,
    this.marketRepository,
    this.identityResolver,
  });

  @override
  State<AddPositionDialog> createState() => _AddPositionDialogState();
}

class _AddPositionDialogState extends State<AddPositionDialog> {
  static const String _defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
  static const PortfolioIdentityEnrichmentService _identityEnrichmentService =
      PortfolioIdentityEnrichmentService();

  final _formKey = GlobalKey<FormState>();

  final _symbolController = TextEditingController();
  final _sharesController = TextEditingController();
  final _averagePriceController = TextEditingController();
  final _costBasisDateController = TextEditingController();

  MarketDependencies? _marketDependencies;
  AthenaBackendPortfolioIdentityDataSource? _identityDataSource;
  late final MarketRepository _marketRepository;
  late final PortfolioIdentityResolver _identityResolver;

  bool _isSaving = false;
  String? _quoteError;

  @override
  void initState() {
    super.initState();

    final injectedRepository = widget.marketRepository;
    if (injectedRepository != null) {
      _marketRepository = injectedRepository;
    } else {
      _marketDependencies = MarketDependencies.create();
      _marketRepository = _marketDependencies!.repository;
    }

    final injectedIdentityResolver = widget.identityResolver;
    if (injectedIdentityResolver != null) {
      _identityResolver = injectedIdentityResolver;
    } else {
      _identityDataSource = AthenaBackendPortfolioIdentityDataSource(
        baseUrl: _defaultBackendUrl,
      );
      _identityResolver = _identityDataSource!.resolve;
    }
  }

  @override
  void dispose() {
    _symbolController.dispose();
    _sharesController.dispose();
    _averagePriceController.dispose();
    _costBasisDateController.dispose();
    _identityDataSource?.dispose();
    _marketDependencies?.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_isSaving || !_formKey.currentState!.validate()) {
      return;
    }

    final symbol = _symbolController.text.trim().toUpperCase();
    final shares = _parseNumber(_sharesController.text);
    final averagePrice = _parseNumber(_averagePriceController.text);
    final costBasisDate = _parseOptionalCostBasisDate(
      _costBasisDateController.text,
    );

    setState(() {
      _isSaving = true;
      _quoteError = null;
    });

    try {
      final quote = await _marketRepository.getQuote(symbol);
      final currentPrice = quote.currentPrice;

      if (!currentPrice.isFinite || currentPrice <= 0) {
        throw StateError(
          'La fuente de mercado no devolvió un precio actual válido.',
        );
      }

      final verifiedSymbol = quote.symbol.trim().toUpperCase();
      if (verifiedSymbol.isEmpty || verifiedSymbol != symbol) {
        throw StateError(
          'La cotización verificada no corresponde al instrumento solicitado.',
        );
      }

      final sourceProvider = quote.sourceProvider?.trim();
      if (sourceProvider == null || sourceProvider.isEmpty) {
        throw StateError(
          'La cotización no incluye un proveedor de origen verificable.',
        );
      }

      final retrievedAt = quote.retrievedAt;
      if (retrievedAt == null) {
        throw StateError(
          'La cotización no incluye un timestamp de recuperación.',
        );
      }

      if (retrievedAt.isBefore(quote.updatedAt)) {
        throw StateError(
          'La recuperación no puede preceder a la observación de mercado.',
        );
      }

      final priceCurrency = quote.currency?.trim().toUpperCase();
      if (priceCurrency == null ||
          priceCurrency.length != 3 ||
          !RegExp(r'^[A-Z]{3}$').hasMatch(priceCurrency)) {
        throw StateError(
          'La cotización no incluye una moneda ISO verificable.',
        );
      }

      final exchange = _optionalText(quote.exchange)?.toUpperCase();
      if (exchange == null || exchange.isEmpty) {
        throw StateError(
          'La cotización no incluye un exchange verificable para resolver identidad.',
        );
      }
      final quoteType = _optionalText(quote.quoteType);
      final verifiedName = quote.companyName.trim();

      final draftPosition = PortfolioPosition(
        symbol: verifiedSymbol,
        companyName: verifiedName.isEmpty ? symbol : verifiedName,
        shares: shares,
        averagePrice: averagePrice,
        currentPrice: currentPrice,
        costBasisDate: costBasisDate,
        priceCurrency: priceCurrency,
        exchange: exchange,
        quoteType: quoteType,
        currentPriceUpdatedAt: quote.updatedAt,
        currentPriceSourceProvider: sourceProvider,
        currentPriceRetrievedAt: retrievedAt,
      );
      final verifiedPosition = await _identityEnrichmentService.enrich(
        position: draftPosition,
        resolver: _identityResolver,
      );

      if (!verifiedPosition.hasVerifiedCanonicalIdentity) {
        throw StateError(
          'La identidad canónica no quedó verificada para riesgo y correlación.',
        );
      }

      if (!mounted) {
        return;
      }

      Navigator.of(context).pop(
        AddPositionResult(
          symbol: verifiedPosition.symbol,
          companyName: verifiedPosition.companyName,
          shares: verifiedPosition.shares,
          averagePrice: verifiedPosition.averagePrice,
          currentPrice: verifiedPosition.currentPrice,
          costBasisDate: verifiedPosition.costBasisDate,
          priceCurrency: verifiedPosition.priceCurrency!,
          exchange: verifiedPosition.exchange,
          quoteType: verifiedPosition.quoteType,
          currentPriceUpdatedAt: verifiedPosition.currentPriceUpdatedAt!,
          currentPriceSourceProvider:
              verifiedPosition.currentPriceSourceProvider!,
          currentPriceRetrievedAt: verifiedPosition.currentPriceRetrievedAt!,
          databaseInstrumentId: verifiedPosition.databaseInstrumentId!,
          canonicalInstrumentId: verifiedPosition.canonicalInstrumentId!,
          canonicalIssuerId: verifiedPosition.canonicalIssuerId!,
          identitySourceProvider: verifiedPosition.identitySourceProvider!,
          identityRetrievedAt: verifiedPosition.identityRetrievedAt!,
          identityResolutionMethod: verifiedPosition.identityResolutionMethod!,
          identityExchangeVerified:
              verifiedPosition.identityExchangeVerified,
          identityRiskReady: verifiedPosition.identityRiskReady,
        ),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }

      setState(() {
        _isSaving = false;
        _quoteError =
            'No se pudo verificar el instrumento, el precio, la moneda, el '
            'listing y su identidad canónica con el backend de ATHENA. La '
            'posición no se guardará con datos manuales, estimados, ambiguos o '
            'sin trazabilidad.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AthenaColors.card,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
      ),
      title: const Text(
        'Añadir posición',
        style: TextStyle(
          color: AthenaColors.text,
          fontSize: 22,
          fontWeight: FontWeight.bold,
        ),
      ),
      content: SizedBox(
        width: 430,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _field(
                  controller: _symbolController,
                  label: 'Ticker',
                  hint: 'Ej. MSFT',
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'Introduce el ticker';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: AthenaSpacing.md),
                _field(
                  controller: _sharesController,
                  label: 'Número de acciones',
                  hint: 'Ej. 15',
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  validator: _validateNumber,
                ),
                const SizedBox(height: AthenaSpacing.md),
                _field(
                  controller: _averagePriceController,
                  label: 'Precio medio de compra',
                  hint: 'Ej. 350',
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  validator: _validateNumber,
                ),
                const SizedBox(height: AthenaSpacing.md),
                _field(
                  controller: _costBasisDateController,
                  label: 'Fecha del coste (AAAA-MM-DD, opcional)',
                  hint: 'Ej. 2026-08-15',
                  keyboardType: TextInputType.datetime,
                  validator: _validateOptionalCostBasisDate,
                ),
                const SizedBox(height: AthenaSpacing.sm),
                const Text(
                  'Indica la fecha sólo si el precio medio corresponde a una '
                  'única compra. Si agrega varias compras, déjala vacía: ATHENA '
                  'bloqueará el P/L multimoneda antes que aplicar un único FX '
                  'histórico a lotes distintos.',
                  style: TextStyle(
                    color: AthenaColors.textSecondary,
                    fontSize: 11,
                    height: 1.35,
                  ),
                ),
                const SizedBox(height: AthenaSpacing.md),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(AthenaSpacing.md),
                  decoration: BoxDecoration(
                    color: AthenaColors.cardSecondary,
                    borderRadius: BorderRadius.circular(AthenaRadius.md),
                    border: Border.all(color: AthenaColors.border),
                  ),
                  child: const Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(
                        Icons.verified_outlined,
                        color: AthenaColors.textSecondary,
                        size: 20,
                      ),
                      SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'ATHENA verifica instrumento, precio, moneda, listing '
                          'e identidad canónica con provenance temporal antes de '
                          'guardar. No se aceptan identidades ni precios actuales '
                          'escritos a mano.',
                          style: TextStyle(
                            color: AthenaColors.textSecondary,
                            fontSize: 12,
                            height: 1.35,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                if (_quoteError != null) ...[
                  const SizedBox(height: AthenaSpacing.md),
                  Text(
                    _quoteError!,
                    style: const TextStyle(
                      color: Color(0xFFFF6B6B),
                      fontSize: 12,
                      height: 1.35,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
      actionsPadding: const EdgeInsets.fromLTRB(
        AthenaSpacing.lg,
        0,
        AthenaSpacing.lg,
        AthenaSpacing.lg,
      ),
      actions: [
        TextButton(
          onPressed: _isSaving ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        ElevatedButton(
          onPressed: _isSaving ? null : _save,
          child: _isSaving
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Guardar posición'),
        ),
      ],
    );
  }

  Widget _field({
    required TextEditingController controller,
    required String label,
    required String hint,
    TextInputType? keyboardType,
    String? Function(String?)? validator,
  }) {
    return TextFormField(
      controller: controller,
      enabled: !_isSaving,
      keyboardType: keyboardType,
      style: const TextStyle(color: AthenaColors.text),
      validator: validator,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        labelStyle: const TextStyle(color: AthenaColors.textSecondary),
        hintStyle: const TextStyle(color: AthenaColors.textSecondary),
        filled: true,
        fillColor: AthenaColors.background,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.all(Radius.circular(AthenaRadius.md)),
        ),
      ),
    );
  }

  String? _validateNumber(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Introduce un valor';
    }

    final number = double.tryParse(value.trim().replaceAll(',', '.'));
    if (number == null || !number.isFinite) {
      return 'Introduce un número válido';
    }

    if (number <= 0) {
      return 'El valor debe ser mayor que 0';
    }

    return null;
  }

  String? _validateOptionalCostBasisDate(String? value) {
    final text = value?.trim() ?? '';
    if (text.isEmpty) {
      return null;
    }

    final parsed = _tryParseCostBasisDate(text);
    if (parsed == null) {
      return 'Usa una fecha válida con formato AAAA-MM-DD';
    }

    final now = DateTime.now().toUtc();
    final today = DateTime.utc(now.year, now.month, now.day);
    if (parsed.isAfter(today)) {
      return 'La fecha del coste no puede estar en el futuro';
    }

    return null;
  }

  DateTime? _parseOptionalCostBasisDate(String value) {
    final text = value.trim();
    if (text.isEmpty) {
      return null;
    }
    return _tryParseCostBasisDate(text);
  }

  DateTime? _tryParseCostBasisDate(String value) {
    final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(value);
    if (match == null) {
      return null;
    }

    final year = int.tryParse(match.group(1)!);
    final month = int.tryParse(match.group(2)!);
    final day = int.tryParse(match.group(3)!);
    if (year == null || month == null || day == null) {
      return null;
    }

    final parsed = DateTime.utc(year, month, day);
    if (parsed.year != year || parsed.month != month || parsed.day != day) {
      return null;
    }
    return parsed;
  }

  double _parseNumber(String value) {
    return double.parse(value.trim().replaceAll(',', '.'));
  }

  String? _optionalText(String? value) {
    final text = value?.trim();
    return text == null || text.isEmpty ? null : text;
  }
}

class AddPositionResult {
  final String symbol;
  final String companyName;
  final double shares;
  final double averagePrice;
  final double currentPrice;
  final DateTime? costBasisDate;
  final String priceCurrency;
  final String? exchange;
  final String? quoteType;
  final DateTime currentPriceUpdatedAt;
  final String currentPriceSourceProvider;
  final DateTime currentPriceRetrievedAt;
  final int databaseInstrumentId;
  final String canonicalInstrumentId;
  final String canonicalIssuerId;
  final String identitySourceProvider;
  final DateTime identityRetrievedAt;
  final String identityResolutionMethod;
  final bool identityExchangeVerified;
  final bool identityRiskReady;

  const AddPositionResult({
    required this.symbol,
    required this.companyName,
    required this.shares,
    required this.averagePrice,
    required this.currentPrice,
    this.costBasisDate,
    required this.priceCurrency,
    this.exchange,
    this.quoteType,
    required this.currentPriceUpdatedAt,
    required this.currentPriceSourceProvider,
    required this.currentPriceRetrievedAt,
    required this.databaseInstrumentId,
    required this.canonicalInstrumentId,
    required this.canonicalIssuerId,
    required this.identitySourceProvider,
    required this.identityRetrievedAt,
    required this.identityResolutionMethod,
    required this.identityExchangeVerified,
    required this.identityRiskReady,
  });
}
