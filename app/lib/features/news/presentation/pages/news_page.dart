import 'package:flutter/material.dart';

import '../../../../core/routing/app_routes.dart';
import '../../../../core/theme/athena_colors.dart';
import '../../models/verified_news_feed.dart';
import '../../models/company_news_evidence.dart';
import '../../services/athena_backend_news_synthesis_service.dart';
import '../news_synthesis_controller.dart';
import '../widgets/news_feed_panel.dart';
import '../widgets/company_news_evidence_panel.dart';
import '../widgets/news_synthesis_panel.dart';

class NewsPage extends StatefulWidget {
  final NewsSynthesisController? synthesisController;
  final Widget? newsFeed;
  final Future<VerifiedNewsFeed> Function(int limit)? feedLoader;
  /// Optional symbol for a textual news search, not a verified issuer binding.
  final String? symbol;
  final String? companyName;
  final Future<CompanyNewsEvidence> Function(String symbol, String companyName)? companyEvidenceLoader;

  const NewsPage({
    super.key,
    this.synthesisController,
    this.newsFeed,
    this.feedLoader,
    this.symbol,
    this.companyName,
    this.companyEvidenceLoader,
  });

  @override
  State<NewsPage> createState() => _NewsPageState();
}

class _NewsPageState extends State<NewsPage> {
  AthenaBackendNewsSynthesisService? _ownedSynthesisService;
  late NewsSynthesisController _synthesisController;
  late bool _ownsSynthesisController;
  int _feedRefreshEpoch = 0;

  void _refreshAllEvidence() {
    if (!mounted) return;
    // News synthesis and the independently verified feed are different sources.
    // Invalidate both; neither a late synthesis nor a late feed may survive.
    _synthesisController.clear();
    _synthesisController.load();
    setState(() => _feedRefreshEpoch++);
  }

  @override
  void initState() {
    super.initState();
    _ownsSynthesisController = widget.synthesisController == null;
    if (_ownsSynthesisController) {
      _ownedSynthesisService = AthenaBackendNewsSynthesisService();
      _synthesisController = NewsSynthesisController(
        service: _ownedSynthesisService!,
      );
    } else {
      _synthesisController = widget.synthesisController!;
    }
    // A reused controller may still be loading for a previous screen. Do not
    // inherit that request as authoritative evidence for this new News page.
    if (!_ownsSynthesisController) _synthesisController.clear();
    _synthesisController.load();
  }

  @override
  void didUpdateWidget(covariant NewsPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.synthesisController == widget.synthesisController) return;

    final previousController = _synthesisController;
    final previousService = _ownedSynthesisService;
    final previouslyOwned = _ownsSynthesisController;

    _ownsSynthesisController = widget.synthesisController == null;
    if (_ownsSynthesisController) {
      _ownedSynthesisService = AthenaBackendNewsSynthesisService();
      _synthesisController = NewsSynthesisController(
        service: _ownedSynthesisService!,
      );
    } else {
      _ownedSynthesisService = null;
      _synthesisController = widget.synthesisController!;
    }

    // The injected controller may still have a request from a prior mount.
    // Clear its request generation before loading for this News page; a plain
    // load() would return early and allow the old response to become visible.
    _synthesisController.clear();
    _synthesisController.load();
    if (previouslyOwned) {
      previousController.dispose();
      previousService?.dispose();
    }
  }

  @override
  void dispose() {
    if (_ownsSynthesisController) {
      _synthesisController.dispose();
      _ownedSynthesisService?.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final symbol = widget.symbol?.trim().toUpperCase();
    final contextual = widget.symbol != null;
    final validSymbol = symbol != null &&
        RegExp(r'^[A-Z0-9][A-Z0-9.^-]{0,19}$').hasMatch(symbol);
    final newsQuery = validSymbol ? '"$symbol" stock earnings' : null;
    final companyName = widget.companyName?.trim();
    final validCompanyName = validSymbol && companyName != null &&
        companyName.isNotEmpty && companyName.length <= 100 &&
        !companyName.contains('"') &&
        !companyName.runes.any((code) => code < 32);
    return Scaffold(
      backgroundColor: AthenaColors.background,
      appBar: AppBar(
        backgroundColor: AthenaColors.background,
        foregroundColor: AthenaColors.text,
        elevation: 0,
        title: Semantics(
          header: true,
          child: Text('NOTICIAS', key: Key('news-page-heading')),
        ),
        actions: [
          IconButton(
            key: const Key('news-page-refresh-all'),
            tooltip: 'Actualizar noticias y análisis ATHENA',
            onPressed: _refreshAllEvidence,
            icon: const Icon(Icons.sync),
          ),
          IconButton(
            key: const Key('news-page-refresh-synthesis'),
            tooltip: 'Actualizar análisis ATHENA de noticias',
            onPressed: () {
              // Invalidate a pending synthesis before requesting fresh evidence.
              _synthesisController.clear();
              _synthesisController.load();
            },
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (contextual) ...[
                Text(
                  validSymbol
                      ? 'BÚSQUEDA DE NOTICIAS: $symbol. Coincidencia textual, no identidad de emisor verificada ni evidencia PIT. El análisis ATHENA siguiente es global, no específico de esta empresa.'
                      : 'SÍMBOLO INVÁLIDO: no se consultarán noticias para esta entrada.',
                  key: const Key('news-symbol-search-boundary'),
                  style: const TextStyle(color: AthenaColors.textSecondary),
                ),
                const SizedBox(height: 16),
              ],
              if (validCompanyName) ...[
                CompanyNewsEvidencePanel(
                  key: ValueKey('news-company-evidence-$symbol-$companyName-$_feedRefreshEpoch'),
                  symbol: symbol,
                  companyName: companyName,
                  loadEvidence: widget.companyEvidenceLoader,
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  key: const Key('news-open-company-research'),
                  onPressed: () => Navigator.of(context).pushNamed(
                    '${AppRoutes.stockResearch}?symbol=${Uri.encodeQueryComponent(symbol)}',
                  ),
                  icon: const Icon(Icons.analytics_outlined),
                  label: const Text('Abrir dosier ATHENA por símbolo'),
                ),
                const Text(
                  'El dosier se consulta por símbolo, sin identidad canónica '
                  'acreditada desde News. Los titulares no se adjuntan ni '
                  'persisten automáticamente en ATHENA.',
                  key: Key('news-research-navigation-boundary'),
                  style: TextStyle(color: AthenaColors.textSecondary, fontSize: 11),
                ),
                const SizedBox(height: 24),
              ],
              NewsSynthesisPanel(controller: _synthesisController),
              const SizedBox(height: 24),
              if (!contextual || validSymbol)
                widget.newsFeed ?? NewsFeedPanel(
                key: ValueKey('news-page-feed-$_feedRefreshEpoch-$newsQuery'),
                limit: 20,
                shrinkWrap: true,
                query: newsQuery,
                loadFeed: widget.feedLoader,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
