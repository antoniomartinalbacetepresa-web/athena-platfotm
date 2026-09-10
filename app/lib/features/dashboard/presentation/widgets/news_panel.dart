import 'package:flutter/material.dart';

import '../../../news/presentation/widgets/news_feed_panel.dart';
import 'base/athena_card.dart';

class NewsPanel extends StatelessWidget {
  const NewsPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return const AthenaCard(
      child: NewsFeedPanel(limit: 8),
    );
  }
}
