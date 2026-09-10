import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../models/verified_news_feed.dart';
import '../../services/athena_backend_news_service.dart';

class NewsFeedPanel extends StatefulWidget {
  const NewsFeedPanel({super.key, this.limit = 8});

  final int limit;

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
    _feedFuture = _service.getFeed(limit: widget.limit);
  }

  @override
  void dispose() {
    _service.dispose();
    super.dispose();
  }

  void _reload() {
    setState(() => _feedFuture = _service.getFeed(limit: widget.limit));
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Expanded(
              child: Text(
                'NOTICIAS',
                style: TextStyle(
                  color: AthenaColors.text,
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
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
        Expanded(
          child: FutureBuilder<VerifiedNewsFeed>(
            future: _feedFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.hasError) {
                return _NewsState(
                  icon: Icons.cloud_off_outlined,
                  title: 'Noticias no disponibles',
                  detail: 'ATHENA no mostrará titulares sin un feed verificable.',
                  actionLabel: 'Reintentar',
                  onAction: _reload,
                );
              }

              final feed = snapshot.data;
              if (feed == null || feed.items.isEmpty) {
                return _NewsState(
                  icon: Icons.article_outlined,
                  title: 'Sin noticias verificadas',
                  detail: 'El proveedor real no devolvió artículos válidos en esta consulta.',
                  actionLabel: 'Actualizar',
                  onAction: _reload,
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
                  Expanded(
                    child: ListView.separated(
                      padding: EdgeInsets.zero,
                      itemCount: feed.items.length,
                      separatorBuilder: (_, __) => const Divider(
                        height: 18,
                        color: AthenaColors.border,
                      ),
                      itemBuilder: (context, index) => _NewsItem(item: feed.items[index]),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ],
    );
  }
}

class _NewsItem extends StatelessWidget {
  const _NewsItem({required this.item});

  final VerifiedNewsItem item;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: item.articleUrl,
      child: Column(
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
        ],
      ),
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
