import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../di/market_dependencies.dart';
import '../../models/market_quote.dart';
import '../../repositories/market_repository.dart';

/// A quote without an explicit ISO-style currency code cannot be displayed
/// as a comparable price. This checks shape, not independent FX/licensing.
bool hasDeclaredQuoteCurrency(String? currency) =>
    currency != null && RegExp(r'^[A-Z]{3} Provenance is declared by the backend, not
/// independently attested; missing or contradictory evidence fails closed.
class VerifiedMarketQuotePanel extends StatefulWidget {
  final String symbol;
  final MarketRepository? repository;
  final void Function(String symbol, int? instrumentId)? onOpenResearch;
  final void Function(String symbol)? onOpenNews;
  final void Function(String symbol, int? instrumentId)? onQuoteValidated;
  final void Function(String symbol, String companyName)? onCompanyQuoteValidated;
  final VoidCallback? onQuoteRequestStarted;

  const VerifiedMarketQuotePanel({
    super.key,
    required this.symbol,
    this.repository,
    this.onOpenResearch,
    this.onOpenNews,
    this.onQuoteValidated,
    this.onCompanyQuoteValidated,
    this.onQuoteRequestStarted,
  });

  @override
  State<VerifiedMarketQuotePanel> createState() => _VerifiedMarketQuotePanelState();
}

class _VerifiedMarketQuotePanelState extends State<VerifiedMarketQuotePanel> {
  MarketDependencies? _dependencies;
  MarketQuote? _quote;
  bool _loading = false;
  bool _failed = false;
  int _generation = 0;

  @override
  void didUpdateWidget(covariant VerifiedMarketQuotePanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.symbol.trim().toUpperCase() != widget.symbol.trim().toUpperCase() ||
        !identical(oldWidget.repository, widget.repository)) {
      _generation++;
      _quote = null;
      _loading = false;
      _failed = false;
    }
  }

  @override
  void dispose() {
    _generation++;
    _dependencies?.dispose();
    super.dispose();
  }

  void _request() {
    final symbol = widget.symbol.trim().toUpperCase();
    if (symbol.isEmpty) return;
    final generation = ++_generation;
    widget.onQuoteRequestStarted?.call();
    setState(() {
      _quote = null;
      _loading = true;
      _failed = false;
    });
    _fetch(symbol, generation);
  }

  Future<void> _fetch(String symbol, int generation) async {
    try {
      final repository = widget.repository ??
          (_dependencies ??= MarketDependencies.create()).repository;
      final quote = await repository.getQuote(symbol).timeout(const Duration(seconds: 15));
      if (!mounted || generation != _generation) return;
      if (!_traceable(quote, symbol)) {
        throw const FormatException('Cotización sin identidad y procedencia válidas.');
      }
      setState(() {
        _quote = quote;
        _loading = false;
        _failed = false;
      });
      widget.onQuoteValidated?.call(symbol, quote.instrumentId);
      widget.onCompanyQuoteValidated?.call(symbol, quote.companyName);
    } catch (_) {
      if (!mounted || generation != _generation) return;
      // Never display provider errors: their text may contain credentials.
      setState(() {
        _quote = null;
        _loading = false;
        _failed = true;
      });
    }
  }

  bool _traceable(MarketQuote quote, String requested) {
    final now = DateTime.now().toUtc();
    final retrieved = quote.retrievedAt?.toUtc();
    final observed = quote.updatedAt.toUtc();
    final status = quote.canonicalIdentityStatus;
    final id = quote.instrumentId;
    final identityConsistent = status == 'matched_internal_listing'
        ? (id != null && id > 0 &&
            (quote.exchange?.trim().isNotEmpty ?? false) &&
            (quote.currency?.trim().isNotEmpty ?? false))
        : ((status == null || status == 'unresolved') && id == null);
    return identityConsistent &&
        quote.symbol.trim().toUpperCase() == requested &&
        quote.currentPrice.isFinite && quote.currentPrice > 0 &&
        hasDeclaredQuoteCurrency(quote.currency) &&
        quote.sourceProvider != null && quote.sourceProvider!.trim().isNotEmpty &&
        retrieved != null &&
        (quote.quoteMode != 'historical_daily_close_fallback' ||
            (quote.priceSessionDate?.trim().isNotEmpty ?? false)) &&
        !retrieved.isAfter(now.add(const Duration(minutes: 5))) &&
        !observed.isAfter(now.add(const Duration(minutes: 5))) &&
        !observed.isAfter(retrieved.add(const Duration(minutes: 5)));
  }

  @override
  Widget build(BuildContext context) {
    final symbol = widget.symbol.trim().toUpperCase();
    final quote = _quote;
    final dailyCloseFallback = quote?.quoteMode == 'historical_daily_close_fallback';
    final historical = quote != null &&
        (dailyCloseFallback ||
         DateTime.now().toUtc().difference(quote.updatedAt.toUtc()) > const Duration(hours: 24) ||
         DateTime.now().toUtc().difference(quote.retrievedAt!.toUtc()) > const Duration(hours: 24));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton(
            key: const Key('market-quote-request'),
            onPressed: symbol.isEmpty ? null : _request,
            child: const Text('CONSULTAR COTIZACIÓN'),
          ),
        ),
        if (_loading)
          Semantics(
            liveRegion: true,
            label: 'Consultando cotización y procedencia.',
            child: const LinearProgressIndicator(),
          ),
        if (_failed)
          Semantics(
            liveRegion: true,
            child: const Text(
              'COTIZACIÓN NO VERIFICABLE. Reintentar o consultar otra empresa.',
              key: Key('market-quote-error'),
              style: TextStyle(color: AthenaColors.danger),
            ),
          ),
        if (quote != null) ...[
          Text(
            '${quote.symbol} · ${quote.currentPrice.toStringAsFixed(2)} ${quote.currency ?? "(moneda no declarada)"}',
            key: const Key('market-quote-price'),
            style: const TextStyle(color: AthenaColors.text),
          ),
          Text(
            'Fuente declarada: ${quote.sourceProvider} · ${quote.exchange ?? "mercado no declarado"}',
            key: const Key('market-quote-source'),
            style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
          ),
          Text(
            'Marca temporal del backend: ${quote.updatedAt.toUtc().toIso8601String()} · '
            'recuperada: ${quote.retrievedAt!.toUtc().toIso8601String()}',
            key: const Key('market-quote-timestamps'),
            style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 10),
          ),
          Text(
            dailyCloseFallback
                ? 'ÚLTIMO CIERRE DIARIO DISPONIBLE · sesión ${quote.priceSessionDate}. No es un precio en tiempo real.'
                : 'Precio de proveedor: tiempo real no acreditado. Puede existir retraso.',
            key: const Key('market-quote-mode'),
            style: const TextStyle(color: Color(0xFFFFD37A), fontSize: 11),
          ),
          Text(
            quote.realTimePriceVerified == true && !dailyCloseFallback
                ? 'Tiempo real: verificación declarada por el proveedor; '
                    'no acreditada independientemente.'
                : 'Tiempo real: NO VERIFICADO. No asumir ejecución '
                    'al precio mostrado.',
            key: const Key('market-quote-realtime-verification'),
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
            ),
          ),
          Text(
            quote.historicalPointInTimeEligible == true
                ? 'Elegibilidad PIT declarada para la cotización; '
                    'NO acredita licencia, ajustes corporativos ni '
                    'histórico independiente.'
                : 'Elegibilidad PIT histórica: NO ACREDITADA. '
                    'La cotización no puede alimentar por sí sola '
                    'el análisis retrospectivo.',
            key: const Key('market-quote-pit-verification'),
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
            ),
          ),
          const Text(
            'Derechos de uso y redistribución: NO VERIFICADOS '
            'en este contrato de cotización.',
            key: Key('market-quote-license-boundary'),
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
            ),
          ),
          if (quote.instrumentId == null)
            const Text(
              'IDENTIDAD CANÓNICA NO ACREDITADA: esta cotización solo comparte símbolo con el dosier. No hay vínculo de instrumento verificado.',
              key: Key('market-quote-identity-boundary'),
              style: TextStyle(color: Color(0xFFFFD37A), fontSize: 11),
            )
          else
            Text(
              'Coincidencia exacta con registro interno ATHENA #${quote.instrumentId}. No acredita identidad externa independiente ni evidencia PIT.',
              key: const Key('market-quote-identity-match'),
              style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
            ),
          const Text(
            'La cotización consultada no es evidencia PIT del dosier ATHENA. El análisis recupera sus propias fuentes.',
            key: Key('market-quote-research-boundary'),
            style: TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
          ),
          if (widget.onOpenResearch != null)
            OutlinedButton(
              key: const Key('market-quote-open-research'),
              onPressed: () {
                if (widget.symbol.trim().toUpperCase() != quote.symbol.trim().toUpperCase()) return;
                widget.onOpenResearch!(quote.symbol.trim().toUpperCase(), quote.instrumentId);
              },
              child: const Text('ANALIZAR ESTA EMPRESA'),
            ),
          if (widget.onOpenNews != null)
            OutlinedButton(
              key: const Key('market-quote-open-news'),
              onPressed: () {
                if (widget.symbol.trim().toUpperCase() != quote.symbol.trim().toUpperCase()) return;
                widget.onOpenNews!(quote.symbol.trim().toUpperCase());
              },
              child: const Text('NOTICIAS DE ESTA EMPRESA'),
            ),
          if (historical)
            Semantics(
              liveRegion: true,
              child: const Text(
                'COTIZACIÓN HISTÓRICA: último cierre diario o marca temporal de más de 24 horas; no es un precio en tiempo real.',
                key: Key('market-quote-stale'),
                style: TextStyle(color: Color(0xFFFFD37A), fontSize: 11),
              ),
            ),
        ],
      ],
    );
  }
}
).hasMatch(currency);

/// Read-only quote preview. Provenance is declared by the backend, not
/// independently attested; missing or contradictory evidence fails closed.
class VerifiedMarketQuotePanel extends StatefulWidget {
  final String symbol;
  final MarketRepository? repository;
  final void Function(String symbol, int? instrumentId)? onOpenResearch;
  final void Function(String symbol)? onOpenNews;
  final void Function(String symbol, int? instrumentId)? onQuoteValidated;
  final void Function(String symbol, String companyName)? onCompanyQuoteValidated;
  final VoidCallback? onQuoteRequestStarted;

  const VerifiedMarketQuotePanel({
    super.key,
    required this.symbol,
    this.repository,
    this.onOpenResearch,
    this.onOpenNews,
    this.onQuoteValidated,
    this.onCompanyQuoteValidated,
    this.onQuoteRequestStarted,
  });

  @override
  State<VerifiedMarketQuotePanel> createState() => _VerifiedMarketQuotePanelState();
}

class _VerifiedMarketQuotePanelState extends State<VerifiedMarketQuotePanel> {
  MarketDependencies? _dependencies;
  MarketQuote? _quote;
  bool _loading = false;
  bool _failed = false;
  int _generation = 0;

  @override
  void didUpdateWidget(covariant VerifiedMarketQuotePanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.symbol.trim().toUpperCase() != widget.symbol.trim().toUpperCase() ||
        !identical(oldWidget.repository, widget.repository)) {
      _generation++;
      _quote = null;
      _loading = false;
      _failed = false;
    }
  }

  @override
  void dispose() {
    _generation++;
    _dependencies?.dispose();
    super.dispose();
  }

  void _request() {
    final symbol = widget.symbol.trim().toUpperCase();
    if (symbol.isEmpty) return;
    final generation = ++_generation;
    widget.onQuoteRequestStarted?.call();
    setState(() {
      _quote = null;
      _loading = true;
      _failed = false;
    });
    _fetch(symbol, generation);
  }

  Future<void> _fetch(String symbol, int generation) async {
    try {
      final repository = widget.repository ??
          (_dependencies ??= MarketDependencies.create()).repository;
      final quote = await repository.getQuote(symbol).timeout(const Duration(seconds: 15));
      if (!mounted || generation != _generation) return;
      if (!_traceable(quote, symbol)) {
        throw const FormatException('Cotización sin identidad y procedencia válidas.');
      }
      setState(() {
        _quote = quote;
        _loading = false;
        _failed = false;
      });
      widget.onQuoteValidated?.call(symbol, quote.instrumentId);
      widget.onCompanyQuoteValidated?.call(symbol, quote.companyName);
    } catch (_) {
      if (!mounted || generation != _generation) return;
      // Never display provider errors: their text may contain credentials.
      setState(() {
        _quote = null;
        _loading = false;
        _failed = true;
      });
    }
  }

  bool _traceable(MarketQuote quote, String requested) {
    final now = DateTime.now().toUtc();
    final retrieved = quote.retrievedAt?.toUtc();
    final observed = quote.updatedAt.toUtc();
    final status = quote.canonicalIdentityStatus;
    final id = quote.instrumentId;
    final identityConsistent = status == 'matched_internal_listing'
        ? (id != null && id > 0 &&
            (quote.exchange?.trim().isNotEmpty ?? false) &&
            (quote.currency?.trim().isNotEmpty ?? false))
        : ((status == null || status == 'unresolved') && id == null);
    return identityConsistent &&
        quote.symbol.trim().toUpperCase() == requested &&
        quote.currentPrice.isFinite && quote.currentPrice > 0 &&
        quote.sourceProvider != null && quote.sourceProvider!.trim().isNotEmpty &&
        retrieved != null &&
        (quote.quoteMode != 'historical_daily_close_fallback' ||
            (quote.priceSessionDate?.trim().isNotEmpty ?? false)) &&
        !retrieved.isAfter(now.add(const Duration(minutes: 5))) &&
        !observed.isAfter(now.add(const Duration(minutes: 5))) &&
        !observed.isAfter(retrieved.add(const Duration(minutes: 5)));
  }

  @override
  Widget build(BuildContext context) {
    final symbol = widget.symbol.trim().toUpperCase();
    final quote = _quote;
    final dailyCloseFallback = quote?.quoteMode == 'historical_daily_close_fallback';
    final historical = quote != null &&
        (dailyCloseFallback ||
         DateTime.now().toUtc().difference(quote.updatedAt.toUtc()) > const Duration(hours: 24) ||
         DateTime.now().toUtc().difference(quote.retrievedAt!.toUtc()) > const Duration(hours: 24));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton(
            key: const Key('market-quote-request'),
            onPressed: symbol.isEmpty ? null : _request,
            child: const Text('CONSULTAR COTIZACIÓN'),
          ),
        ),
        if (_loading)
          Semantics(
            liveRegion: true,
            label: 'Consultando cotización y procedencia.',
            child: const LinearProgressIndicator(),
          ),
        if (_failed)
          Semantics(
            liveRegion: true,
            child: const Text(
              'COTIZACIÓN NO VERIFICABLE. Reintentar o consultar otra empresa.',
              key: Key('market-quote-error'),
              style: TextStyle(color: AthenaColors.danger),
            ),
          ),
        if (quote != null) ...[
          Text(
            '${quote.symbol} · ${quote.currentPrice.toStringAsFixed(2)} ${quote.currency ?? "(moneda no declarada)"}',
            key: const Key('market-quote-price'),
            style: const TextStyle(color: AthenaColors.text),
          ),
          Text(
            'Fuente declarada: ${quote.sourceProvider} · ${quote.exchange ?? "mercado no declarado"}',
            key: const Key('market-quote-source'),
            style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
          ),
          Text(
            'Marca temporal del backend: ${quote.updatedAt.toUtc().toIso8601String()} · '
            'recuperada: ${quote.retrievedAt!.toUtc().toIso8601String()}',
            key: const Key('market-quote-timestamps'),
            style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 10),
          ),
          Text(
            dailyCloseFallback
                ? 'ÚLTIMO CIERRE DIARIO DISPONIBLE · sesión ${quote.priceSessionDate}. No es un precio en tiempo real.'
                : 'Precio de proveedor: tiempo real no acreditado. Puede existir retraso.',
            key: const Key('market-quote-mode'),
            style: const TextStyle(color: Color(0xFFFFD37A), fontSize: 11),
          ),
          Text(
            quote.realTimePriceVerified == true && !dailyCloseFallback
                ? 'Tiempo real: verificación declarada por el proveedor; '
                    'no acreditada independientemente.'
                : 'Tiempo real: NO VERIFICADO. No asumir ejecución '
                    'al precio mostrado.',
            key: const Key('market-quote-realtime-verification'),
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
            ),
          ),
          Text(
            quote.historicalPointInTimeEligible == true
                ? 'Elegibilidad PIT declarada para la cotización; '
                    'NO acredita licencia, ajustes corporativos ni '
                    'histórico independiente.'
                : 'Elegibilidad PIT histórica: NO ACREDITADA. '
                    'La cotización no puede alimentar por sí sola '
                    'el análisis retrospectivo.',
            key: const Key('market-quote-pit-verification'),
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
            ),
          ),
          const Text(
            'Derechos de uso y redistribución: NO VERIFICADOS '
            'en este contrato de cotización.',
            key: Key('market-quote-license-boundary'),
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
            ),
          ),
          if (quote.instrumentId == null)
            const Text(
              'IDENTIDAD CANÓNICA NO ACREDITADA: esta cotización solo comparte símbolo con el dosier. No hay vínculo de instrumento verificado.',
              key: Key('market-quote-identity-boundary'),
              style: TextStyle(color: Color(0xFFFFD37A), fontSize: 11),
            )
          else
            Text(
              'Coincidencia exacta con registro interno ATHENA #${quote.instrumentId}. No acredita identidad externa independiente ni evidencia PIT.',
              key: const Key('market-quote-identity-match'),
              style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
            ),
          const Text(
            'La cotización consultada no es evidencia PIT del dosier ATHENA. El análisis recupera sus propias fuentes.',
            key: Key('market-quote-research-boundary'),
            style: TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
          ),
          if (widget.onOpenResearch != null)
            OutlinedButton(
              key: const Key('market-quote-open-research'),
              onPressed: () {
                if (widget.symbol.trim().toUpperCase() != quote.symbol.trim().toUpperCase()) return;
                widget.onOpenResearch!(quote.symbol.trim().toUpperCase(), quote.instrumentId);
              },
              child: const Text('ANALIZAR ESTA EMPRESA'),
            ),
          if (widget.onOpenNews != null)
            OutlinedButton(
              key: const Key('market-quote-open-news'),
              onPressed: () {
                if (widget.symbol.trim().toUpperCase() != quote.symbol.trim().toUpperCase()) return;
                widget.onOpenNews!(quote.symbol.trim().toUpperCase());
              },
              child: const Text('NOTICIAS DE ESTA EMPRESA'),
            ),
          if (historical)
            Semantics(
              liveRegion: true,
              child: const Text(
                'COTIZACIÓN HISTÓRICA: último cierre diario o marca temporal de más de 24 horas; no es un precio en tiempo real.',
                key: Key('market-quote-stale'),
                style: TextStyle(color: Color(0xFFFFD37A), fontSize: 11),
              ),
            ),
        ],
      ],
    );
  }
}
