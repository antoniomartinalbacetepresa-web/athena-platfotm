import 'package:flutter/material.dart';

import '../../../auth/services/auth_session.dart';
import '../../services/private_research_history_service.dart';
import '../../services/rebound25_artifact_review_service.dart';
import '../../services/rebound25_artifact_service.dart';

/// Human-authored research only. Never modifies positions or enables orders.
class Rebound25ArtifactReviewForm extends StatefulWidget {
  const Rebound25ArtifactReviewForm({
    super.key,
    required this.artifact,
    this.service,
  });
  final Rebound25Artifact artifact;
  final Rebound25ArtifactReviewService? service;
  @override
  State<Rebound25ArtifactReviewForm> createState() => _ReviewState();
}

class _ReviewState extends State<Rebound25ArtifactReviewForm> {
  final _thesis = TextEditingController();
  final _objection = TextEditingController();
  Rebound25ArtifactReviewService? _owned;
  Rebound25ArtifactReviewDraft? _draft;
  PrivateResearchCycleDetail? _result;
  bool _confirmed = false, _busy = false, _failed = false;
  int _generation = 0;
  int _authority = AuthSession.instance.authorityVersion;
  Rebound25ArtifactReviewService get _service =>
      widget.service ?? (_owned ??= Rebound25ArtifactReviewService());

  @override
  void initState() {
    super.initState();
    AuthSession.instance.addListener(_sessionChanged);
  }

  void _clear() {
    _generation++;
    _thesis.clear();
    _objection.clear();
    _draft = null;
    _result = null;
    _confirmed = _busy = _failed = false;
  }

  void _sessionChanged() {
    if (_authority == AuthSession.instance.authorityVersion) {
      return;
    }
    _authority = AuthSession.instance.authorityVersion;
    if (mounted) {
      setState(_clear);
    }
  }

  @override
  void didUpdateWidget(covariant Rebound25ArtifactReviewForm oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.artifact.artifactHash != widget.artifact.artifactHash ||
        oldWidget.service != widget.service) {
      _owned?.dispose();
      _owned = null;
      _clear();
    }
  }

  Future<void> _submit() async {
    if (_busy ||
        _result != null ||
        !_confirmed ||
        !AuthSession.instance.isAuthenticated) {
      return;
    }
    final generation = _generation;
    try {
      // Retain the identical journal identity, timestamps and text after failure.
      _draft ??= Rebound25ArtifactReviewDraft(
        artifact: widget.artifact,
        thesis: _thesis.text,
        objection: _objection.text,
        authoredAt: DateTime.now().toUtc(),
      );
      setState(() {
        _busy = true;
        _failed = false;
      });
      final result = await _service.create(_draft!);
      if (!mounted || generation != _generation) {
        return;
      }
      setState(() {
        _busy = false;
        _result = result;
      });
    } catch (_) {
      if (!mounted || generation != _generation) {
        return;
      }
      setState(() {
        _busy = false;
        _failed = true;
      });
    }
  }

  @override
  void dispose() {
    _generation++;
    AuthSession.instance.removeListener(_sessionChanged);
    _owned?.dispose();
    _thesis.dispose();
    _objection.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final editable = !_busy && _draft == null && _result == null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Revisión humana para ATHENA, Radar y Journal'),
        const Text(
          'Referencia a un cálculo artificial disponible ahora. No constituye evidencia bursátil real ni activa órdenes.',
        ),
        TextField(
          key: const Key('rebound25-review-thesis'),
          controller: _thesis,
          enabled: editable,
          maxLength: 4000,
          maxLines: 3,
          decoration: const InputDecoration(
            labelText: 'Hipótesis o pregunta de investigación',
          ),
        ),
        TextField(
          key: const Key('rebound25-review-objection'),
          controller: _objection,
          enabled: editable,
          maxLength: 4000,
          maxLines: 3,
          decoration: const InputDecoration(
            labelText: 'Objeción material o explicación alternativa',
          ),
        ),
        CheckboxListTile(
          key: const Key('rebound25-review-confirm'),
          value: _confirmed,
          onChanged: editable
              ? (value) => setState(() => _confirmed = value ?? false)
              : null,
          title: const Text(
            'He revisado el cálculo y sus limitaciones; la hipótesis y objeción son mías.',
          ),
        ),
        if (!AuthSession.instance.isAuthenticated)
          const Text('Inicia sesión para registrar tu revisión.'),
        FilledButton(
          key: const Key('rebound25-review-submit'),
          onPressed:
              _busy ||
                  !_confirmed ||
                  _result != null ||
                  !AuthSession.instance.isAuthenticated
              ? null
              : _submit,
          child: Text(
            _draft != null && _failed
                ? 'REINTENTAR EL MISMO BORRADOR'
                : 'REGISTRAR REVISIÓN PRIVADA',
          ),
        ),
        if (_busy)
          const LinearProgressIndicator(key: Key('rebound25-review-busy')),
        if (_failed)
          const Text(
            'No se pudo verificar la revisión. Conservamos el mismo borrador para reintentar.',
            key: Key('rebound25-review-error'),
          ),
        if (_result != null)
          SelectableText(
            'Revisión privada verificada: ${_result!.cycleHash}',
            key: const Key('rebound25-review-result'),
          ),
      ],
    );
  }
}
