import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../models/verified_news_feed.dart';
import '../../services/athena_backend_news_service.dart';

class NewsFeedPanel extends StatefulWidget {
  const NewsFeedPanel({
    super.key,
    this.limit = 8,
    this.shrinkWrap = false,
    this.loadFeed,
    this.query,
  });

  final int limit;
  /// True when embedded in a vertically scrolling page rather than a
  /// height-constrained dashboard card.
  final bool shrinkWrap;
  final Future<VerifiedNewsFeed> Function(int limit)? loadFeed;
  /// Exact backend query expected when browsing a specific symbol.
  final String? query;

  @override
  State<NewsFeedPanel> createState() => _NewsFeedPanelState();
}

class _NewsFeedPanelState extends State<NewsFeedPanel> {
  late final AthenaBackendNewsService _service;
  late Future<VerifiedNewsFeed> _feedFuture;

  @override
  void initState() {
    super.initState();
    _service = AthenaBackendNewsService();
    // A supplied loader can throw before returning a Future. Convert that
    // failure into the same fail-closed UI state as an asynchronous failure.
    _feedFuture = Future<VerifiedNewsFeed>.sync(_load);
  }

  Future<VerifiedNewsFeed> _load() async {
    final feed = await (widget.loadFeed?.call(widget.limit) ??
        _service.getFeed(limit: widget.limit, query: widget.query));
    // An HTTP 200 with a different query must not be shown as symbol news.
    if (widget.query != null && feed.query != widget.query) {
      throw const FormatException('La consulta de noticias no coincide con el símbolo solicitado.');
    }
    return feed;
  }

  @override
  void didUpdateWidget(covariant NewsFeedPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.limit != widget.limit ||
        oldWidget.query != widget.query ||
        !identical(oldWidget.loadFeed, widget.loadFeed)) {
      // A replaced future cannot publish a stale result from an old source.
      // A synchronous failure in the replacement must not retain old articles.
      _feedFuture = Future<VerifiedNewsFeed>.sync(_load);
    }
  }

  @override
  void dispose() {
    _service.dispose();
    super.dispose();
  }

  void _reload() {
    // Never return a Future from setState. Normalize synchronous loader
    // failures into the same fail-closed FutureBuilder error state.
    final next = Future<VerifiedNewsFeed>.sync(_load);
    setState(() {
      _feedFuture = next;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Semantics(
                header: true,
                child: const Text(
                  'NOTICIAS',
                  style: TextStyle(
                    color: AthenaColors.text,
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
            IconButton(
              tooltip: 'Actualizar noticias',
              onPressed: _reload,
              icon: const Icon(
                Icons.refresh,
                color: AthenaColors.textSecondary,
                size: 20,
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        if (widget.shrinkWrap)
          _buildFeed()
        else
          Expanded(child: _buildFeed()),
      ],
    );
  }

  Widget _buildFeed() {
    return FutureBuilder<VerifiedNewsFeed>(
            future: _feedFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return Semantics(
                  liveRegion: true,
                  label: 'Consultando noticias verificadas.',
                  child: const Center(child: CircularProgressIndicator()),
                );
              }
              if (snapshot.hasError) {
                return Semantics(
                  liveRegion: true,
                  label: 'Noticias verificadas no disponibles.',
                  child: _NewsState(
                    icon: Icons.cloud_off_outlined,
                    title: 'Noticias no disponibles',
                    detail: 'ATHENA no mostrará titulares sin un feed verificable.',
                    actionLabel: 'Reintentar',
                    onAction: _reload,
                  ),
                );
              }

              final feed = snapshot.data;
              // A provider timestamp in the future is not reliable evidence.
              // Allow minor clock skew, but never present impossible provenance
              // as a current verified feed.
              if (feed != null &&
                  feed.retrievedAt.isAfter(
                    DateTime.now().toUtc().add(const Duration(minutes: 5)),
                  )) {
                return Semantics(
                  liveRegion: true,
                  label: 'Fecha de recuperación de noticias inválida.',
                  child: _NewsState(
                    icon: Icons.warning_amber_outlined,
                    title: 'Fecha de noticias inválida',
                    detail: 'La fecha del proveedor está adelantada. '
                        'No se muestran artículos hasta verificar el reloj.',
                    actionLabel: 'Reintentar',
                    onAction: _reload,
                  ),
                );
              }
              if (feed == null || feed.items.isEmpty) {
                return Semantics(
                  liveRegion: true,
                  label: 'Sin noticias verificadas en la consulta.',
                  child: _NewsState(
                    icon: Icons.article_outlined,
                    title: 'Sin noticias verificadas',
                    detail: 'El proveedor real no devolvió artículos válidos en esta consulta.',
                    actionLabel: 'Actualizar',
                    onAction: _reload,
                  ),
                );
              }

              final isStale = DateTime.now().toUtc()
                      .difference(feed.retrievedAt) >
                  const Duration(hours: 24);
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${feed.items.length} artículos · ${feed.sourceProvider} · '
                    'recuperado ${_formatUtc(feed.retrievedAt)} UTC',
                    style: const TextStyle(
                      color: AthenaColors.textSecondary,
                      fontSize: 11,
                    ),
                  ),
                  if (isStale) ...[
                    const SizedBox(height: 6),
                    Semantics(
                      liveRegion: true,
                      label: 'Noticias antiguas: recuperación hace más de 24 horas.',
                      child: Text(
                        'Datos antiguos (más de 24 h). Actualiza antes de '
                        'analizar el mercado.',
                        key: Key('news-feed-stale-warning'),
                        style: TextStyle(
                          color: AthenaColors.textSecondary,
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                  const SizedBox(height: 8),
                  if (widget.shrinkWrap)
                    _buildItems(feed)
                  else
                    Expanded(child: _buildItems(feed)),
                ],
              );
            },
    );
  }

  Widget _buildItems(VerifiedNewsFeed feed) {
    return ListView.separated(
      padding: EdgeInsets.zero,
      shrinkWrap: widget.shrinkWrap,
      physics: widget.shrinkWrap
          ? const NeverScrollableScrollPhysics()
          : null,
      itemCount: feed.items.length,
      separatorBuilder: (_, _) => const Divider(
        height: 18,
        color: AthenaColors.border,
      ),
      itemBuilder: (context, index) => _NewsItem(item: feed.items[index]),
    );
  }
}

class _NewsItem extends StatelessWidget {
  const _NewsItem({required this.item});

  final VerifiedNewsItem item;

  Future<void> _copySource(BuildContext context) async {
    // The feed contract already rejects non-HTTPS and credential-bearing URLs.
    // Copying a source is presentation-only: it never authorizes a trade.
    await Clipboard.setData(ClipboardData(text: item.articleUrl));
    if (context.mounted) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text('Enlace de noticia copiado')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          item.title,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: AthenaColors.text,
            fontSize: 13,
            fontWeight: FontWeight.w600,
            height: 1.3,
          ),
        ),
        const SizedBox(height: 5),
        Text(
          '${item.publisher} · publicado ${_formatUtc(item.publishedAt)} UTC',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 11,
          ),
        ),
        Row(
          children: [
            Expanded(
              child: Semantics(
                label: 'Enlace HTTPS de la noticia: ${item.articleUrl}',
                child: ExcludeSemantics(
                  child: Text(
                    item.articleUrl,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AthenaColors.textSecondary,
                      fontSize: 11,
                    ),
                  ),
                ),
              ),
            ),
            IconButton(
              tooltip: 'Copiar enlace de ${item.title}',
              onPressed: () => _copySource(context),
              icon: const Icon(
                Icons.copy_outlined,
                color: AthenaColors.textSecondary,
                size: 18,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _NewsState extends StatelessWidget {
  const _NewsState({
    required this.icon,
    required this.title,
    required this.detail,
    required this.actionLabel,
    required this.onAction,
  });

  final IconData icon;
  final String title;
  final String detail;
  final String actionLabel;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: AthenaColors.textSecondary, size: 34),
            const SizedBox(height: 10),
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AthenaColors.text,
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              detail,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 11,
                height: 1.35,
              ),
            ),
            const SizedBox(height: 8),
            TextButton(onPressed: onAction, child: Text(actionLabel)),
          ],
        ),
      ),
    );
  }
}

String _formatUtc(DateTime value) {
  final utc = value.toUtc();
  final month = utc.month.toString().padLeft(2, '0');
  final day = utc.day.toString().padLeft(2, '0');
  final hour = utc.hour.toString().padLeft(2, '0');
  final minute = utc.minute.toString().padLeft(2, '0');
  return '${utc.year}-$month-$day $hour:$minute';
}