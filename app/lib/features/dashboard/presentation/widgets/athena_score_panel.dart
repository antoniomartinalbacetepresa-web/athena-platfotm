import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/typography/athena_text.dart';
import '../../../recommendations/controllers/recommendation_learning_controller.dart';
import '../../../recommendations/di/recommendation_dependencies.dart';
import '../../../recommendations/models/recommendation_learning_status.dart';
import '../../../recommendations/services/recommendation_learning_status_provider.dart';
import 'base/athena_card.dart';

class AthenaScorePanel extends StatefulWidget {
  final RecommendationLearningStatusProvider? learningStatusProvider;

  const AthenaScorePanel({
    super.key,
    this.learningStatusProvider,
  });

  @override
  State<AthenaScorePanel> createState() => _AthenaScorePanelState();
}

class _AthenaScorePanelState extends State<AthenaScorePanel> {
  RecommendationDependencies? _dependencies;
  late final RecommendationLearningController _controller;

  @override
  void initState() {
    super.initState();

    final injectedProvider = widget.learningStatusProvider;
    if (injectedProvider != null) {
      _controller = RecommendationLearningController(provider: injectedProvider);
    } else {
      _dependencies = RecommendationDependencies.create();
      _controller = _dependencies!.learningController;
    }

    _controller.addListener(_onControllerChanged);
    _controller.load();
  }

  void _onControllerChanged() {
    if (mounted) {
      setState(() {});
    }
  }

  @override
  void dispose() {
    _controller.removeListener(_onControllerChanged);
    if (_dependencies != null) {
      _dependencies!.dispose();
    } else {
      _controller.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AthenaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('ATHENA SCORE', style: AthenaText.h3),
          const SizedBox(height: 12),
          Expanded(child: _buildBody()),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_controller.isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_controller.error != null) {
      return const _UnavailableState(
        icon: Icons.cloud_off_outlined,
        title: 'SIN DATOS',
        message:
            'No se pudo consultar el estado real del motor. ATHENA no sustituye '
            'esa información por una calificación estimada.',
      );
    }

    final status = _controller.status;
    if (status == null) {
      return const _UnavailableState(
        icon: Icons.hourglass_empty_rounded,
        title: 'SIN CALIFICAR',
        message:
            'El motor todavía no dispone de un estado de aprendizaje válido.',
      );
    }

    return _buildLearningState(status);
  }

  Widget _buildLearningState(RecommendationLearningStatus status) {
    final evaluated = _int(status.performance['sampleCount']) ?? 0;
    final pending = _int(status.evaluationSchedule['dueCount']) ?? 0;
    final drift = status.drift?['status']?.toString().trim();

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Center(
            child: _ScorePlaceholder(),
          ),
          const SizedBox(height: 12),
          const Center(
            child: Text('SIN CALIFICAR', style: AthenaText.title),
          ),
          const SizedBox(height: 8),
          const Text(
            'No existe todavía un ATHENA Score de producción. El panel muestra '
            'únicamente el estado real de validación recibido del backend.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 12,
              height: 1.35,
            ),
          ),
          const SizedBox(height: 14),
          const Divider(),
          const SizedBox(height: 8),
          _StatusRow(label: 'Resultados evaluados', value: '$evaluated'),
          const SizedBox(height: 6),
          _StatusRow(label: 'Evaluaciones pendientes', value: '$pending'),
          const SizedBox(height: 6),
          _StatusRow(
            label: 'Deriva',
            value: drift == null || drift.isEmpty
                ? 'Sin muestra'
                : drift.toUpperCase(),
          ),
          const SizedBox(height: 6),
          const _StatusRow(label: 'Producción', value: 'BLOQUEADA'),
          const SizedBox(height: 8),
          Text(
            status.isDiagnosticOnly
                ? 'Estado: diagnóstico y aprendizaje.'
                : 'Estado no reconocido: producción bloqueada por seguridad.',
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  int? _int(dynamic value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    if (value is String) {
      return int.tryParse(value.trim());
    }
    return null;
  }
}

class _ScorePlaceholder extends StatelessWidget {
  const _ScorePlaceholder();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 88,
      height: 88,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: AthenaColors.cardSecondary,
        shape: BoxShape.circle,
        border: Border.all(color: AthenaColors.border),
      ),
      child: const Icon(
        Icons.hourglass_top_rounded,
        color: AthenaColors.textSecondary,
        size: 34,
      ),
    );
  }
}

class _UnavailableState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String message;

  const _UnavailableState({
    required this.icon,
    required this.title,
    required this.message,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: AthenaColors.textSecondary, size: 40),
            const SizedBox(height: 12),
            Text(title, style: AthenaText.title),
            const SizedBox(height: 8),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 12,
                height: 1.35,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusRow extends StatelessWidget {
  final String label;
  final String value;

  const _StatusRow({
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: Text(label, style: AthenaText.caption)),
        const SizedBox(width: 8),
        Flexible(
          child: Text(
            value,
            textAlign: TextAlign.right,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: AthenaColors.textSecondary,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    );
  }
}
