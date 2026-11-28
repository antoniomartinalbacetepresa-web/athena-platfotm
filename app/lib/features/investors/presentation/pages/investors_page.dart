import 'package:flutter/foundation.dart' show listEquals;
import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../models/sec_cik_identity.dart';
import '../../../dashboard/presentation/widgets/relevant_investors_panel.dart';

/// Session-only SEC 13F exploration; never a trading or weighting authority.
/// The entered CIKs are not persisted or copied into an owner profile.
class InvestorsPage extends StatefulWidget {
  const InvestorsPage({super.key, this.configuredCiks, this.loader});

  final List<String>? configuredCiks;
  final RelevantInvestorActivityLoader? loader;

  @override
  State<InvestorsPage> createState() => _InvestorsPageState();
}

class _InvestorsPageState extends State<InvestorsPage> {
  static const int _maxCiksPerQuery = 5;

  late final TextEditingController _cikInput;
  List<String>? _selectedCiks;
  String? _validationError;
  int _queryGeneration = 0;

  @override
  void initState() {
    super.initState();
    _selectedCiks = widget.configuredCiks == null
        ? null
        : List<String>.unmodifiable(widget.configuredCiks!);
    _cikInput = TextEditingController(
      text: widget.configuredCiks?.join(', ') ?? '',
    );
  }

  @override
  void didUpdateWidget(covariant InvestorsPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (listEquals(oldWidget.configuredCiks, widget.configuredCiks)) return;
    _selectedCiks = widget.configuredCiks == null
        ? null
        : List<String>.unmodifiable(widget.configuredCiks!);
    _cikInput.text = widget.configuredCiks?.join(', ') ?? '';
    _validationError = null;
    _queryGeneration++;
  }

  void _submitCiks() {
    final raw = _cikInput.text.trim();
    final entries = raw.isEmpty
        ? <String>[]
        : raw.split(',').map((entry) => entry.trim()).toList();
    final normalized = <String>[];
    try {
      if (entries.length > _maxCiksPerQuery) {
        throw const FormatException('Demasiados CIKs SEC.');
      }
      for (final entry in entries) {
        normalized.add(normalizeSecCik(entry));
      }
    } on FormatException {
      // Invalid input revokes the previous cohort immediately. Never leave
      // older institutional evidence visible under a different query.
      setState(() {
        _selectedCiks = const [];
        _validationError =
            'Introduce entre 1 y 5 CIKs SEC de 1 a 10 dígitos, separados por comas.';
        _queryGeneration++;
      });
      return;
    }

    setState(() {
      _selectedCiks = List<String>.unmodifiable(normalized.toSet());
      _validationError = null;
      // A repeated query is an explicit refresh, not a cached result.
      _queryGeneration++;
    });
  }

  void _clearCiks() {
    _cikInput.clear();
    setState(() {
      _selectedCiks = const [];
      _validationError = null;
      _queryGeneration++;
    });
  }

  Widget _queryControls(double width) {
    final input = TextField(
      key: const Key('investors-cik-input'),
      controller: _cikInput,
      maxLength: 64,
      textInputAction: TextInputAction.search,
      onSubmitted: (_) => _submitCiks(),
      decoration: const InputDecoration(
        labelText: 'CIKs SEC 13F',
        hintText: 'Ej. 1067983, 1350694',
        helperText: 'Máximo 5 CIKs por consulta. Solo durante esta sesión.',
      ),
    );
    final actions = Wrap(
      spacing: 8,
      children: [
        FilledButton(
          key: const Key('investors-cik-submit'),
          onPressed: _submitCiks,
          child: const Text('CONSULTAR'),
        ),
        TextButton(
          key: const Key('investors-cik-clear'),
          onPressed: _clearCiks,
          child: const Text('Limpiar'),
        ),
      ],
    );
    if (width < 560) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          input,
          Align(alignment: Alignment.centerLeft, child: actions),
        ],
      );
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Expanded(child: input),
        const SizedBox(width: 12),
        actions,
      ],
    );
  }

  @override
  void dispose() {
    _cikInput.dispose();
    super.dispose();
  }

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
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  LayoutBuilder(
                    builder: (context, constraints) =>
                        _queryControls(constraints.maxWidth),
                  ),
                  if (_validationError != null)
                    Semantics(
                      liveRegion: true,
                      child: Text(
                        _validationError!,
                        key: const Key('investors-cik-validation-error'),
                        style: const TextStyle(color: AthenaColors.danger),
                      ),
                    ),
                  const SizedBox(height: 12),
                  Expanded(
                    child: RelevantInvestorsPanel(
                      key: ValueKey('investors-session-$_queryGeneration'),
                      configuredCiks: _selectedCiks,
                      loader: widget.loader,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
