import 'package:flutter/material.dart';

import '../../../../core/routing/app_routes.dart';
import '../../../../core/theme/athena_colors.dart';
import '../../controllers/global_market_context_controller.dart';
import '../../../news/models/verified_news_feed.dart';
import '../../../recommendations/data/datasources/athena_backend_professional_dossier_data_source.dart';
import '../../../news/presentation/widgets/news_feed_panel.dart';
import '../../repositories/market_repository.dart';
import '../widgets/global_market_panel.dart';
import '../widgets/market_research_preview.dart';
import '../widgets/verified_market_quote_panel.dart';

class MarketPage extends StatefulWidget {
  final GlobalMarketContextController? controller;
  final MarketRepository? quoteRepository;
  final Future<VerifiedNewsFeed> Function(int limit)? newsFeedLoader;
  final Future<ProfessionalDossier> Function(String symbol, int? instrumentId)? researchLoader;

  const MarketPage({super.key, this.controller, this.quoteRepository, this.newsFeedLoader, this.researchLoader});

  @override
  State<MarketPage> createState() => _MarketPageState();
}

class _MarketPageState extends State<MarketPage> {
  final _symbolController = TextEditingController();
  String? _newsSymbol;
  int? _newsInstrumentId;
  bool _showContextNews = true;
  bool _showContextResearch = false;

  void _clearQuoteContext() {
    if (_newsSymbol == null && _newsInstrumentId == null) return;
    setState(() {
      _newsSymbol = null;
      _newsInstrumentId = null;
      _showContextResearch = false;
    });
  }

  void _onQuoteValidated(String symbol, int? instrumentId) {
    if (!mounted || symbol != _symbolController.text.trim().toUpperCase()) return;
    setState(() {
      _newsSymbol = symbol;
      _newsInstrumentId = instrumentId;
      _showContextNews = true;
      _showContextResearch = false;
    });
  }

  @override
  void dispose() {
    _symbolController.dispose();
    super.dispose();
  }

  void _openResearch() => _openResearchForSymbol(_symbolController.text);

  void _openResearchForSymbol(String requestedSymbol, {int? instrumentId}) {
    final symbol = requestedSymbol.trim().toUpperCase();
    if (symbol.isEmpty || symbol != _symbolController.text.trim().toUpperCase()) return;
    final query = 'symbol=${Uri.encodeQueryComponent(symbol)}'
        '${instrumentId != null ? '&instrumentId=$instrumentId' : ''}';
    Navigator.of(context).pushNamed(
      '${AppRoutes.stockResearch}?$query',
    );
  }

  void _openNewsForSymbol(String requestedSymbol) {
    final symbol = requestedSymbol.trim().toUpperCase();
    if (symbol.isEmpty || symbol != _symbolController.text.trim().toUpperCase()) return;
    Navigator.of(context).pushNamed(
      '${AppRoutes.news}?symbol=${Uri.encodeQueryComponent(symbol)}',
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AthenaColors.background,
      appBar: AppBar(
        backgroundColor: AthenaColors.background,
        foregroundColor: AthenaColors.text,
        elevation: 0,
        title: Semantics(
          header: true,
          child: const Text('MERCADO'),
        ),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Semantics(
                container: true,
                label:
                    'Contexto de mercado informativo. Los datos pueden cambiar y no constituyen una recomendación ni ejecutan operaciones.',
                child: const ExcludeSemantics(
                  child: Text(
                    'Contexto informativo: los datos pueden cambiar; no constituye una recomendación ni ejecuta operaciones.',
                    key: Key('market-information-boundary'),
                    style: TextStyle(color: AthenaColors.textSecondary),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Semantics(
                container: true,
                label: 'Abrir análisis profesional de una empresa por símbolo bursátil.',
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _symbolController,
                        onChanged: (_) => _clearQuoteContext(),
                        textCapitalization: TextCapitalization.characters,
                        textInputAction: TextInputAction.search,
                        onSubmitted: (_) => _openResearch(),
                        decoration: const InputDecoration(
                          labelText: 'Símbolo',
                          hintText: 'Ej. AAPL',
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    ValueListenableBuilder<TextEditingValue>(
                      valueListenable: _symbolController,
                      builder: (context, value, _) {
                        final canAnalyze = value.text.trim().isNotEmpty;
                        return FilledButton(
                          key: const Key('market-open-professional-research'),
                          onPressed: canAnalyze ? _openResearch : null,
                          child: const Text('ANALIZAR'),
                        );
                      },
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              ValueListenableBuilder<TextEditingValue>(
                valueListenable: _symbolController,
                builder: (context, value, _) => ConstrainedBox(
                  constraints: const BoxConstraints(maxHeight: 160),
                  child: SingleChildScrollView(
                    child: VerifiedMarketQuotePanel(
                      symbol: value.text,
                      repository: widget.quoteRepository,
                      onOpenResearch: (symbol, instrumentId) =>
                          _openResearchForSymbol(symbol, instrumentId: instrumentId),
                      onOpenNews: _openNewsForSymbol,
                      onQuoteValidated: _onQuoteValidated,
                      onQuoteRequestStarted: _clearQuoteContext,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              if (_newsSymbol != null) ...[
                Semantics(
                  container: true,
                  child: Text(
                    'NOTICIAS RELACIONADAS CON $_newsSymbol: búsqueda textual, '
                    'no identidad de emisor ni evidencia PIT acreditadas. '
                    'Las cotizaciones y las noticias tienen fuentes y fechas independientes.',
                    key: const Key('market-context-news-boundary'),
                    style: const TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
                  ),
                ),
                Wrap(
                  spacing: 8,
                  children: [
                    TextButton(
                      key: const Key('market-context-news-toggle'),
                      onPressed: () => setState(() {
                        _showContextResearch = false;
                        _showContextNews = !_showContextNews;
                      }),
                      child: Text(_showContextNews ? 'VER MERCADO GLOBAL' : 'VER NOTICIAS RELACIONADAS'),
                    ),
                    TextButton(
                      key: const Key('market-context-research-toggle'),
                      onPressed: () => setState(() {
                        _showContextResearch = !_showContextResearch;
                        if (_showContextResearch) _showContextNews = true;
                      }),
                      child: Text(_showContextResearch ? 'VOLVER A NOTICIAS' : 'VER RESUMEN ATHENA'),
                    ),
                  ],
                ),
              ],
              Expanded(
                child: _newsSymbol != null && _showContextResearch
                    ? MarketResearchPreview(
                        key: ValueKey('market-context-research-$_newsSymbol-$_newsInstrumentId'),
                        symbol: _newsSymbol!,
                        instrumentId: _newsInstrumentId,
                        loadDossier: widget.researchLoader,
                        onOpenFullResearch: () => _openResearchForSymbol(
                          _newsSymbol!, instrumentId: _newsInstrumentId,
                        ),
                      )
                    : _newsSymbol != null && _showContextNews
                    ? NewsFeedPanel(
                        key: ValueKey('market-context-news-$_newsSymbol'),
                        limit: 5,
                        query: '"$_newsSymbol" stock earnings',
                        loadFeed: widget.newsFeedLoader,
                      )
                    : GlobalMarketPanel(controller: widget.controller),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
