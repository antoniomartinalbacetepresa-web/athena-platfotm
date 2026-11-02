import 'package:flutter/material.dart';

import '../../../../core/routing/app_routes.dart';
import '../../../../core/theme/athena_colors.dart';
import '../../controllers/global_market_context_controller.dart';
import '../../repositories/market_repository.dart';
import '../widgets/global_market_panel.dart';
import '../widgets/verified_market_quote_panel.dart';

class MarketPage extends StatefulWidget {
  final GlobalMarketContextController? controller;
  final MarketRepository? quoteRepository;

  const MarketPage({super.key, this.controller, this.quoteRepository});

  @override
  State<MarketPage> createState() => _MarketPageState();
}

class _MarketPageState extends State<MarketPage> {
  final _symbolController = TextEditingController();

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
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Expanded(child: GlobalMarketPanel(controller: widget.controller)),
            ],
          ),
        ),
      ),
    );
  }
}
