import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../controllers/athena_synthesis_controller.dart';
import '../../data/datasources/athena_backend_synthesis_data_source.dart';
import '../athena_synthesis_panel.dart';

/// Read-only, canonical ATHENA AI synthesis; never an order or weighting authority.
class AthenaAiPage extends StatefulWidget {
  const AthenaAiPage({super.key, this.controller});

  /// Optional controller for cross-surface acceptance tests.
  final AthenaSynthesisController? controller;

  @override
  State<AthenaAiPage> createState() => _AthenaAiPageState();
}

class _AthenaAiPageState extends State<AthenaAiPage> {
  static const _backendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
  AthenaBackendSynthesisDataSource? _ownedSource;
  late AthenaSynthesisController _controller;
  late bool _ownsController;

  void _bindController() {
    _ownsController = widget.controller == null;
    if (_ownsController) {
      _ownedSource = AthenaBackendSynthesisDataSource(baseUrl: _backendUrl);
      _controller = AthenaSynthesisController(dataSource: _ownedSource!);
    } else {
      _ownedSource = null;
      _controller = widget.controller!;
      // Never reuse a previous screen's in-flight response.
      _controller.clear();
    }
    _controller.loadLatest();
  }

  void _refresh() {
    // loadLatest alone ignores refresh while loading; clear first so late
    // responses from the previous generation cannot become authoritative.
    _controller.clear();
    _controller.loadLatest();
  }

  @override
  void initState() {
    super.initState();
    _bindController();
  }

  @override
  void didUpdateWidget(covariant AthenaAiPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (identical(oldWidget.controller, widget.controller)) return;
    final previousController = _controller;
    final previousSource = _ownedSource;
    final previouslyOwned = _ownsController;
    _bindController();
    if (previouslyOwned) {
      previousController.dispose();
      previousSource?.dispose();
    }
  }

  @override
  void dispose() {
    if (_ownsController) {
      _controller.dispose();
      _ownedSource?.dispose();
    }
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
          child: const Text('ATHENA AI', key: Key('athena-ai-page-heading')),
        ),
        actions: [
          IconButton(
            key: const Key('athena-ai-page-refresh'),
            tooltip: 'Actualizar síntesis ATHENA verificada',
            onPressed: _refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
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
                  Semantics(
                    container: true,
                    label: 'ATHENA AI muestra solo síntesis canónicas verificadas. '
                        'No autoriza recomendaciones, ponderaciones ni operaciones.',
                    child: const ExcludeSemantics(
                      child: Text(
                        'Investigación informativa y verificable. '
                        'Sin recomendaciones automáticas ni órdenes.',
                        key: Key('athena-ai-page-boundary'),
                        style: TextStyle(color: AthenaColors.textSecondary),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Expanded(child: AthenaSynthesisPanel(controller: _controller)),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
