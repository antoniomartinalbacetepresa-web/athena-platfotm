import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_spacing.dart';
import '../../../auth/services/auth_session.dart';
import '../../../profile/models/user_personalization.dart';
import '../../../profile/services/user_preferences_service.dart';
import 'base/athena_card.dart';

typedef DashboardPersonalizationLoader = Future<UserPersonalization?> Function();

class PersonalizedExplanationPanel extends StatefulWidget {
  const PersonalizedExplanationPanel({
    super.key,
    this.loadPersonalization,
    this.session,
  });

  final DashboardPersonalizationLoader? loadPersonalization;
  final AuthSession? session;

  @override
  State<PersonalizedExplanationPanel> createState() =>
      _PersonalizedExplanationPanelState();
}

class _PersonalizedExplanationPanelState
    extends State<PersonalizedExplanationPanel> {
  UserPreferencesService? _ownedService;
  UserPersonalization? _personalization;
  _PersonalizationLoadState _state = _PersonalizationLoadState.loading;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final injectedLoader = widget.loadPersonalization;
    final session = widget.session ?? AuthSession.instance;

    if (injectedLoader == null && !session.isAuthenticated) {
      if (!mounted) return;
      setState(() => _state = _PersonalizationLoadState.guest);
      return;
    }

    try {
      final DashboardPersonalizationLoader loader;
      if (injectedLoader != null) {
        loader = injectedLoader;
      } else {
        final service = UserPreferencesService(session: session);
        _ownedService = service;
        loader = service.loadPersonalization;
      }

      final personalization = await loader();
      if (!mounted) return;
      setState(() {
        _personalization = personalization;
        _state = personalization == null
            ? _PersonalizationLoadState.notConfigured
            : _PersonalizationLoadState.configured;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _state = _PersonalizationLoadState.error);
    }
  }

  @override
  void dispose() {
    _ownedService?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AthenaCard(
      padding: const EdgeInsets.all(AthenaSpacing.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(
            Icons.auto_awesome_outlined,
            color: AthenaColors.primary,
            size: 20,
          ),
          const SizedBox(width: AthenaSpacing.sm),
          Expanded(child: _buildContent()),
        ],
      ),
    );
  }

  Widget _buildContent() {
    switch (_state) {
      case _PersonalizationLoadState.loading:
        return const Row(
          children: [
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            SizedBox(width: AthenaSpacing.sm),
            Expanded(
              child: Text('Verificando tu contexto de explicación…'),
            ),
          ],
        );
      case _PersonalizationLoadState.guest:
        return const _ExplanationCopy(
          title: 'Explicación estándar',
          body:
              'Inicia sesión para que ATHENA adapte cómo presenta la evidencia a tu perfil.',
        );
      case _PersonalizationLoadState.notConfigured:
        return const _ExplanationCopy(
          title: 'Explicación estándar',
          body:
              'Configura tu perfil para adaptar el nivel de detalle, el horizonte y el énfasis de riesgo.',
        );
      case _PersonalizationLoadState.error:
        return const _ExplanationCopy(
          title: 'Explicación estándar',
          body:
              'No se pudo verificar de forma segura tu personalización. ATHENA mantiene la explicación estándar.',
        );
      case _PersonalizationLoadState.configured:
        final personalization = _personalization;
        if (personalization == null) {
          return const _ExplanationCopy(
            title: 'Explicación estándar',
            body: 'ATHENA mantiene la explicación estándar.',
          );
        }
        return _ExplanationCopy(
          title: 'Tu contexto de explicación',
          body: _personalizedCopy(personalization.presentation),
          footer:
              'Solo cambia cómo se explica la evidencia: no modifica puntuaciones, recomendaciones, ponderaciones, aprendizaje ni ejecuta operaciones.',
        );
    }
  }

  String _personalizedCopy(UserPersonalizationPresentation presentation) {
    final detail = switch (presentation.detailLevel) {
      'guided' => 'paso a paso',
      'technical' => 'con detalle técnico',
      _ => 'con detalle equilibrado',
    };
    final style = switch (presentation.explanationStyle) {
      'plain_language' => 'en lenguaje claro',
      'analytical' => 'con enfoque analítico',
      _ => 'con lenguaje equilibrado',
    };
    final risk = switch (presentation.riskEmphasis) {
      'high' => 'priorizando riesgos y escenarios adversos',
      'low' => 'sin sobrerrepresentar el riesgo',
      _ => 'con riesgo y oportunidad en equilibrio',
    };
    final horizon = switch (presentation.horizonEmphasis) {
      'short_term' => 'horizonte corto',
      'long_term' => 'horizonte largo',
      _ => 'horizonte medio',
    };
    final objective = switch (presentation.objectiveFocus) {
      'capital_preservation' => 'preservación de capital',
      'income' => 'generación de ingresos',
      'long_term_growth' => 'crecimiento a largo plazo',
      _ => 'crecimiento equilibrado',
    };

    return 'ATHENA te explicará la evidencia $detail, $style, $risk, con foco en $horizon y $objective.';
  }
}

class _ExplanationCopy extends StatelessWidget {
  const _ExplanationCopy({
    required this.title,
    required this.body,
    this.footer,
  });

  final String title;
  final String body;
  final String? footer;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          title,
          style: theme.textTheme.titleSmall?.copyWith(
            color: AthenaColors.text,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          body,
          style: theme.textTheme.bodySmall?.copyWith(
            color: AthenaColors.textSecondary,
          ),
        ),
        if (footer != null) ...[
          const SizedBox(height: 4),
          Text(
            footer!,
            style: theme.textTheme.labelSmall?.copyWith(
              color: AthenaColors.textSecondary,
            ),
          ),
        ],
      ],
    );
  }
}

enum _PersonalizationLoadState {
  loading,
  guest,
  notConfigured,
  configured,
  error,
}
