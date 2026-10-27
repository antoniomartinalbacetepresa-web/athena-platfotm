import 'package:flutter/foundation.dart' show listEquals;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

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
  late List<String> _ciks;
  late RelevantInvestorActivityLoader _loader;
  late Future<List<RelevantInvestorActivity>> _activitiesFuture;

  @override
  void initState() {
    super.initState();
    _ciks = _normalizeCiks(
      widget.configuredCiks ??
          RelevantInvestorsPanel._configuredCiksRaw.split(','),
    );
    _setLoader(widget.loader);
    _activitiesFuture = _loadActivities();
  }

  void _setLoader(RelevantInvestorActivityLoader? supplied) {
    _dataSource?.dispose();
    _dataSource = null;
    if (supplied != null) {
      _loader = supplied;
      return;
    }
    final source = AthenaBackendRelevantInvestorDataSource(
      baseUrl: RelevantInvestorsPanel._backendUrl,
    );
    _dataSource = source;
    // In-flight requests retain their original source after a rebind.
    _loader = (cik) => source.getLatestInstitutionalHoldings(cik: cik);
  }

  @override
  void didUpdateWidget(covariant RelevantInvestorsPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    final previousCiks = _ciks;
    final previousError = _configurationError;
    _configurationError = null;
    final updatedCiks = _normalizeCiks(
      widget.configuredCiks ??
          RelevantInvestorsPanel._configuredCiksRaw.split(','),
    );
    final loaderChanged = !identical(oldWidget.loader, widget.loader);
    if (!loaderChanged &&
        previousError == _configurationError &&
        listEquals(previousCiks, updatedCiks)) {
      return;
    }
    _ciks = updatedCiks;
    if (loaderChanged) _setLoader(widget.loader);
    // Replacing the future prevents stale 13F data from being presented.
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
    final requestedCiks = _ciks;
    final loader = _loader;
    // Normalize synchronous provider exceptions before aggregating results.
    // One unverified filing invalidates the entire configured cohort.
    final activities = await Future.wait(
      requestedCiks.map(
        (cik) => Future<RelevantInvestorActivity>.sync(() => loader(cik)),
      ),
    );
    for (var i = 0; i < activities.length; i++) {
      if (activities[i].cik != requestedCiks[i]) {
        throw const FormatException(
          'La identidad del inversor no coincide con el CIK solicitado.',
        );
      }
    }
    return List.unmodifiable(activities);
  }

  void _reload() {
    // Start the request outside setState; synchronous provider failures must
    // be represented by the FutureBuilder's error state, not escape the tap.
    final next = Future<List<RelevantInvestorActivity>>.sync(_loadActivities);
    setState(() {
      _activitiesFuture = next;
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
              Expanded(
                child: Semantics(
                  header: true,
                  child: const Text(
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
          const SizedBox(height: 4),
          Semantics(
            container: true,
            label:
                'Evidencia institucional point-in-time de SEC 13F. Es informativa y separada: no altera el score ATHENA, no genera recomendaciones y no ejecuta órdenes.',
            child: const ExcludeSemantics(
              child: Text(
                'Evidencia SEC 13F separada · sin autoridad sobre score, recomendaciones u órdenes.',
                style: TextStyle(
                  color: AthenaColors.textSecondary,
                  fontSize: 10,
                ),
              ),
            ),
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
                  return Semantics(
                    liveRegion: true,
                    label: 'Consultando actividad institucional SEC 13F.',
                    child: const Center(child: CircularProgressIndicator()),
                  );
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
                  separatorBuilder: (_, _) => const Divider(
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

  Future<void> _copyFilingSource(BuildContext context) async {
    // SEC provenance is informational and never authorizes an order.
    await Clipboard.setData(ClipboardData(text: activity.sourceUrl));
    if (context.mounted) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text('Enlace SEC 13F copiado')),
      );
    }
  }

  void _showHoldings(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _InvestorHoldingsSheet(activity: activity),
    );
  }

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
        Row(
          children: [
            Expanded(
              child: Semantics(
                label: 'Fuente SEC 13F verificada: ${activity.sourceUrl}',
                child: ExcludeSemantics(
                  child: Text(
                    activity.sourceUrl,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AthenaColors.textSecondary,
                      fontSize: 10,
                    ),
                  ),
                ),
              ),
            ),
            IconButton(
              key: Key('investor-copy-filing-${activity.cik}'),
              tooltip: 'Copiar enlace SEC 13F de CIK ${activity.cik}',
              onPressed: () => _copyFilingSource(context),
              icon: const Icon(
                Icons.copy_outlined,
                color: AthenaColors.textSecondary,
                size: 18,
              ),
            ),
          ],
        ),
        TextButton(
          key: Key('investor-holdings-detail-${activity.cik}'),
          onPressed: () => _showHoldings(context),
          child: Text('Ver todas las posiciones (${activity.holdings.length})'),
        ),
      ],
    );
  }
}

/// Read-only exploration of every holding in one verified SEC filing.
/// Search and ordering affect presentation only, never canonical identity,
/// ATHENA scores, recommendations or portfolio weights.
class _InvestorHoldingsSheet extends StatefulWidget {
  const _InvestorHoldingsSheet({required this.activity});

  final RelevantInvestorActivity activity;

  @override
  State<_InvestorHoldingsSheet> createState() => _InvestorHoldingsSheetState();
}

class _InvestorHoldingsSheetState extends State<_InvestorHoldingsSheet> {
  final TextEditingController _searchController = TextEditingController();
  String _query = '';
  bool _sortByReportedValue = false;

  Future<void> _showFilingSummary() async {
    final activity = widget.activity;
    final summary = _ReportedFilingSummary.fromHoldings(activity.holdings);
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Resumen del expediente SEC 13F'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('CIK ${activity.cik} · ${activity.form} · '
                  'posición ${_formatDate(activity.positionDate)}'),
              const SizedBox(height: 8),
              Text('Suma de valores declarados: ${summary.total} miles USD',
                  key: const Key('investor-filing-reported-total')),
              Text('Sin opción: ${summary.ordinary} miles USD'),
              Text('PUT: ${summary.put} miles USD'),
              Text('CALL: ${summary.call} miles USD'),
              if (summary.unclassified != BigInt.zero)
                Text('Opciones sin clasificar: ${summary.unclassified} miles USD'),
              const SizedBox(height: 8),
              const Text(
                'Son sumas de filas de este documento, no una cartera completa '
                'verificada, una exposición económica comparable ni un valor '
                'actual. No generan score, recomendaciones ni órdenes.',
              ),
              if (activity.form == '13F-HR/A') ...[
                const SizedBox(height: 8),
                const Text(
                  'Enmienda 13F-HR/A: puede modificar solo parte de la '
                  'declaración original. No se interpreta como cartera completa.',
                ),
              ],
              const SizedBox(height: 8),
              Text('Fuente: ${activity.sourceUrl}'),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Cerrar resumen'),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  List<MapEntry<int, RelevantInvestorHolding>> _visibleHoldings() {
    final matches = widget.activity.holdings
        .asMap()
        .entries
        .where((entry) {
          if (_query.isEmpty) return true;
          final holding = entry.value;
          return holding.issuerName.toLowerCase().contains(_query) ||
              holding.cusip.toLowerCase().contains(_query);
        })
        .toList(growable: false);

    if (_sortByReportedValue) {
      // Keep the SEC document order for equal values.
      matches.sort((a, b) {
        final byValue = b.value.valueThousandsUsd
            .compareTo(a.value.valueThousandsUsd);
        return byValue != 0 ? byValue : a.key.compareTo(b.key);
      });
    }
    return matches;
  }

  @override
  Widget build(BuildContext context) {
    final activity = widget.activity;
    final matches = _visibleHoldings();
    return SafeArea(
      top: false,
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.85,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Semantics(
                      header: true,
                      child: Text(
                        'Detalle SEC 13F · CIK ${activity.cik}',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                    ),
                  ),
                  IconButton(
                    key: const Key('investor-filing-summary'),
                    tooltip: 'Resumen de valores declarados SEC 13F',
                    onPressed: _showFilingSummary,
                    icon: const Icon(Icons.assessment_outlined),
                  ),
                  IconButton(
                    tooltip: 'Cerrar detalle 13F',
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
              Text(
                'Posición ${_formatDate(activity.positionDate)} · '
                'presentación ${_formatDate(activity.filingDate)} · '
                'publicado ${_formatUtc(activity.publicationDateTime)} UTC',
              ),
              const SizedBox(height: 8),
              Text(
                activity.form == '13F-HR/A'
                    ? 'Enmienda SEC 13F-HR/A: puede contener solo parte de la '
                      'declaración original. Sus filas no representan una '
                      'cartera completa ni posiciones actuales; no implican '
                      'recomendaciones, score u órdenes.'
                    : 'Declaraciones históricas SEC 13F: no representan '
                      'posiciones actuales ni implican recomendaciones, '
                      'score u órdenes.',
              ),
              const SizedBox(height: 8),
              Text(
                '${activity.sourceProvider} · expediente ${activity.accessionNumber} · '
                '${activity.holdings.length} posiciones declaradas',
              ),
              const SizedBox(height: 8),
              TextField(
                key: const Key('investor-holdings-search'),
                controller: _searchController,
                onChanged: (value) =>
                    setState(() => _query = value.trim().toLowerCase()),
                decoration: InputDecoration(
                  labelText: 'Buscar emisor o CUSIP',
                  isDense: true,
                  border: const OutlineInputBorder(),
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: _query.isEmpty
                      ? null
                      : IconButton(
                          tooltip: 'Limpiar búsqueda 13F',
                          onPressed: () {
                            _searchController.clear();
                            setState(() => _query = '');
                          },
                          icon: const Icon(Icons.clear),
                        ),
                ),
              ),
              Wrap(
                spacing: 12,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Semantics(
                    liveRegion: true,
                    child: Text(
                      '${matches.length} de ${activity.holdings.length} posiciones',
                      key: const Key('investor-holdings-result-count'),
                    ),
                  ),
                  TextButton.icon(
                    key: const Key('investor-holdings-sort'),
                    onPressed: () => setState(
                      () => _sortByReportedValue = !_sortByReportedValue,
                    ),
                    icon: const Icon(Icons.sort),
                    label: Text(
                      _sortByReportedValue
                          ? 'Orden: valor declarado ↓'
                          : 'Orden: documento SEC',
                    ),
                  ),
                ],
              ),
              Expanded(
                child: matches.isEmpty
                    ? const Center(
                        child: Text('Sin coincidencias en este expediente 13F'),
                      )
                    : ListView.builder(
                        key: const Key('investor-holdings-detail-list'),
                        itemCount: matches.length,
                        itemBuilder: (context, index) {
                          final holding = matches[index].value;
                          return ListTile(
                            title: Text(holding.issuerName),
                            subtitle: Text(
                              '${holding.titleOfClass} · CUSIP ${holding.cusip}\n'
                              '${holding.shareOrPrincipalAmount} '
                              '${holding.shareOrPrincipalType} · '
                              '${holding.investmentDiscretion} · '
                              '${holding.valueThousandsUsd} miles USD declarados',
                            ),
                          );
                        },
                      ),
              ),
              const SizedBox(height: 8),
              SelectableText(
                activity.sourceUrl,
                style: const TextStyle(fontSize: 11),
              ),
            ],
          ),
        ),
      ),
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
    return Semantics(
      liveRegion: true,
      label: '$title. $detail',
      child: Center(
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
 
/// Exact sums of reported 13F row values. Never used as market weights or
/// economic exposure; options are kept separate from ordinary securities.
class _ReportedFilingSummary {
  final BigInt total;
  final BigInt ordinary;
  final BigInt put;
  final BigInt call;
  final BigInt unclassified;

  const _ReportedFilingSummary({
    required this.total,
    required this.ordinary,
    required this.put,
    required this.call,
    required this.unclassified,
  });

  factory _ReportedFilingSummary.fromHoldings(
    List<RelevantInvestorHolding> holdings,
  ) {
    var total = BigInt.zero;
    var ordinary = BigInt.zero;
    var put = BigInt.zero;
    var call = BigInt.zero;
    var unclassified = BigInt.zero;
    for (final holding in holdings) {
      final reported = BigInt.from(holding.valueThousandsUsd);
      total += reported;
      switch (holding.putCall?.trim().toUpperCase()) {
        case null:
        case '':
          ordinary += reported;
        case 'PUT':
          put += reported;
        case 'CALL':
          call += reported;
        default:
          unclassified += reported;
      }
    }
    return _ReportedFilingSummary(
      total: total,
      ordinary: ordinary,
      put: put,
      call: call,
      unclassified: unclassified,
    );
  }
}
