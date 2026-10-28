import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../dashboard/presentation/widgets/relevant_investors_panel.dart';

/// Read-only SEC 13F evidence, never a trading or weighting authority.
class InvestorsPage extends StatelessWidget {
  const InvestorsPage({super.key, this.configuredCiks, this.loader});

  final List<String>? configuredCiks;
  final RelevantInvestorActivityLoader? loader;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AthenaColors.background,
      appBar: AppBar(
        backgroundColor: AthenaColors.background,
        foregroundColor: AthenaColors.text,
        title: Semantics(
          header: true,
          child: const Text('INVERSORES', key: Key('investors-page-heading')),
        ),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1100),
              child: SizedBox.expand(
                child: RelevantInvestorsPanel(
                  configuredCiks: configuredCiks,
                  loader: loader,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
