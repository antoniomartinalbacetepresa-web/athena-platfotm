import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../investors/data/athena_backend_relevant_investor_data_source.dart';
import '../../../investors/models/relevant_investor_activity.dart';
import 'base/athena_card.dart';

typedef RelevantInvestorActivityLoader = Future<RelevantInvestorActivity>
    Function(String cik);

class RelevantInvestorsPanel extends StatefulWidget {
  static const String _configuredCiksRaw = String.fromEnvironment(
    'ATHENA_RELEVANT_INVESTOR_CIKS',
    defaultValue: '',
  );
  static const String _backendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  final List<String>? configuredCiks;
  final RelevantInvestorActivityLoader? loader;

  const RelevantInvestorsPanel({
    super.key,
    this.configuredCiks,
    this.loader,
  });

  @override
  State<RelevantInvestorsPanel> createState() => _RelevantInvestorsPanelState();
}

class _RelevantInvestorsPanelState extends State<RelevantInvestorsPanel> {
  AthenaBackendRelevantInvestorDataSource? _dataSource;
  String? _configurationError;
  late final List<String> _ciks;
  late final RelevantInvestorActivityLoader _loader;
  late Future<List<RelevantInvestorActivity>> _activitiesFuture;

  @override
  void initState() {
    super.initState();
    _ciks = _normalizeCiks(
      widget.configuredCiks ??
          RelevantInvestorsPanel._configuredCiksRaw.split(','),
    );
    if (widget.loader != null) {
      _loader = widget.loader!;
    } else {
      _dataSource = AthenaBackendRelevantInvestorDataSource(
        baseUrl: RelevantInvestorsPanel._backendUrl,
      );
      _loader = (cik) =>
          _dataSource!.getLatestInstitutionalHoldings(cik: cik);
    }
    _activitiesFuture = _loadActivities();
  }

  @override
  void dispose() {
    _dataSource?.dispose();
    super.dispose();
  }

  List<String> _normalizeCiks(Iterable<String> values) {
    final seen = <String>{};
    final result = <String>[];
    for (final raw in values) {
      final cik = raw.trim();
      if (cik.isEmpty) continue;
      if (!RegExp(r'^\d{1,10}$').hasMatch(cik)) {
        _configurationError =
            'ATHENA_RELEVANT_INVESTOR_CIKS contiene un CIK inválido.';
        return const [];
      }
      if (seen.add(cik)) result.add(cik);
    }
    return List.unmodifiable(result);
  }

  Future<List<RelevantInvestorActivity>> _loadActivities() async {
    if (_configurationError != null || _ciks.isEmpty) return const [];
    final activities = await Future.wait(_ciks.map(_loader));
    return List.unmodifiable(activities);
  }

  void _reload() {
    setState(() {
      _activitiesFuture = _loadActivities();
    });
  }

  @override
  Widget build(BuildContext context) {
    return AthenaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  'ACTIVIDAD DE INVERSORES RELEVANTES',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: AthenaColors.text,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              IconButton(
                tooltip: 'Actualizar actividad SEC 13F',
                onPressed:
                    _configurationError == null && _ciks.isNotEmpty ? _reload : null,
                icon: const Icon(
                  Icons.refresh,
                  color: AthenaColors.textSecondary,
                  size: 20,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Expanded(
            child: FutureBuilder<List<RelevantInvestorActivity>>(
              future: _activitiesFuture,
              builder: (context, snapshot) {
                if (_configurationError != null) {
                  return const _InvestorState(
                    icon: Icons.gpp_bad_outlined,
                    title: 'Configuración institucional inválida',
                    detail:
                        'ATHENA bloqueó la consulta porque la lista de CIKs no es verificable.',
                  );
                }
                if (_ciks.isEmpty) {
                  return const _InvestorState(
                    icon: Icons.account_balance_outlined,
                    title: 'Sin inversores configurados',
                    detail:
                        'Configura CIKs SEC explícitos para consultar evidencia 13F real.',
                  );
                }
                if (snapshot.connectionState == ConnectionState.waiting) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return _InvestorState(
                    icon: Icons.cloud_off_outlined,
                    title: 'Actividad no disponible',
                    detail:
                        'ATHENA no mostrará 13F si falla su provenance o validación.',
                    actionLabel: 'Reintentar',
                    onAction: _reload,
                  );
                }
                final activities = snapshot.data;
                if (activities == null || activities.length != _ciks.length) {
                  return _InvestorState(
                    icon: Icons.gpp_bad_outlined,
                    title: 'Evidencia incompleta',
                    detail:
                        'La consulta institucional no superó la validación completa.',
                    actionLabel: 'Reintentar',
                    onAction: _reload,
                  );
                }

                return ListView.separated(
                  padding: EdgeInsets.zero,
                  itemCount: activities.length,
                  separatorBuilder: (_, __) => const Divider(
                    height: 20,
                    color: AthenaColors.border,
                  ),
                  itemBuilder: (context, index) =>
                      _InvestorActivityItem(activity: activities[index]),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _InvestorActivityItem extends StatelessWidget {
  final RelevantInvestorActivity activity;

  const _InvestorActivityItem({required this.activity});

  @override
  Widget build(BuildContext context) {
    final sample = activity.holdings.take(2).toList(growable: false);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'CIK ${activity.cik} · ${activity.form} · '
          '${activity.holdings.length} posiciones',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: AthenaColors.text,
            fontSize: 13,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 5),
        Text(
          'Posición ${_formatDate(activity.positionDate)} · '
          'filing ${_formatDate(activity.filingDate)}',
          style: const TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 11,
          ),
        ),
        const SizedBox(height: 3),
        Text(
          'Publicado ${_formatUtc(activity.publicationDateTime)} UTC · '
          'recuperado ${_formatUtc(activity.retrievedAt)} UTC',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 11,
          ),
        ),
        const SizedBox(height: 5),
        for (final holding in sample)
          Padding(
            padding: const EdgeInsets.only(bottom: 2),
            child: Text(
              '${holding.issuerName} · CUSIP ${holding.cusip} · '
              '\$${holding.valueThousandsUsd}k reportados',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: AthenaColors.text,
                fontSize: 11,
              ),
            ),
          ),
        const SizedBox(height: 4),
        Text(
          '${activity.sourceProvider} · evidencia separada; no altera el score ATHENA',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: AthenaColors.textSecondary,
            fontSize: 10,
          ),
        ),
      ],
    );
  }
}

class _InvestorState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String detail;
  final String? actionLabel;
  final VoidCallback? onAction;

  const _InvestorState({
    required this.icon,
    required this.title,
    required this.detail,
    this.actionLabel,
    this.onAction,
  });

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
            if (actionLabel != null && onAction != null) ...[
              const SizedBox(height: 8),
              TextButton(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ],
        ),
      ),
    );
  }
}

String _formatDate(DateTime value) {
  final utc = value.toUtc();
  final month = utc.month.toString().padLeft(2, '0');
  final day = utc.day.toString().padLeft(2, '0');
  return '${utc.year}-$month-$day';
}

String _formatUtc(DateTime value) {
  final utc = value.toUtc();
  final month = utc.month.toString().padLeft(2, '0');
  final day = utc.day.toString().padLeft(2, '0');
  final hour = utc.hour.toString().padLeft(2, '0');
  final minute = utc.minute.toString().padLeft(2, '0');
  return '${utc.year}-$month-$day $hour:$minute';
}
