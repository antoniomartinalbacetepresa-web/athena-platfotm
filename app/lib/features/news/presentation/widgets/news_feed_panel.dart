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
  });

  final int limit;
  /// True when embedded in a vertically scrolling page rather than a
  /// height-constrained dashboard card.
  final bool shrinkWrap;
  final Future<VerifiedNewsFeed> Function(int limit)? loadFeed;

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
    _feedFuture = _load();
  }

  Future<VerifiedNewsFeed> _load() =>
      widget.loadFeed?.call(widget.limit) ??
      _service.getFeed(limit: widget.limit);

  @override
  void didUpdateWidget(covariant NewsFeedPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.limit != widget.limit ||
        !identical(oldWidget.loadFeed, widget.loadFeed)) {
      // A replaced future cannot publish a stale result from an old source.
      _feedFuture = _load();
    }
  }

  @override
  void dispose() {
    _service.dispose();
    super.dispose();
  }

  void _reload() {
    setState(() => _feedFuture = _load());
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Expanded(
              child: Semantics(
                header: true,
                child: Text(
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
                return const Semantics(
                  liveRegion: true,
                  label: 'Consultando noticias verificadas.',
                  child: Center(child: CircularProgressIndicator()),
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