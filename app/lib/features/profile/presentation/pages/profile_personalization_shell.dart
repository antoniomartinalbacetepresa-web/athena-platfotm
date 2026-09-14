import 'package:flutter/material.dart';

import '../../../../core/routing/app_routes.dart';
import '../../../auth/services/account_lifecycle_service.dart';
import '../../../auth/services/athena_auth_service.dart';
import '../../../auth/services/auth_session.dart';
import '../../models/user_personalization.dart';
import '../../services/user_preferences_service.dart';
import '../widgets/account_closure_panel.dart';
import '../widgets/user_personalization_panel.dart';
import 'profile_page.dart';

class ProfilePersonalizationShell extends StatelessWidget {
  const ProfilePersonalizationShell({
    super.key,
    this.service,
    this.session,
    this.accountLifecycleAuthService,
    this.child,
  });

  final UserPreferencesService? service;
  final AuthSession? session;
  final AthenaAuthService? accountLifecycleAuthService;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final activeSession = session ?? AuthSession.instance;
    return Stack(
      children: [
        child ?? const ProfilePage(),
        if (activeSession.isAuthenticated)
          Positioned(
            right: 16,
            bottom: 16,
            child: SafeArea(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  FloatingActionButton.extended(
                    key: const Key('open-account-lifecycle'),
                    heroTag: 'profile-account-lifecycle',
                    onPressed: () => _openAccountClosure(context, activeSession),
                    icon: const Icon(Icons.manage_accounts_outlined),
                    label: const Text('CUENTA'),
                  ),
                  const SizedBox(height: 10),
                  FloatingActionButton.extended(
                    key: const Key('open-profile-personalization'),
                    heroTag: 'profile-personalization',
                    onPressed: () => _openPersonalization(context, activeSession),
                    icon: const Icon(Icons.auto_awesome_outlined),
                    label: const Text('PERSONALIZACIÓN'),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }

  Future<void> _openAccountClosure(
    BuildContext context,
    AuthSession activeSession,
  ) async {
    if (!activeSession.isAuthenticated) return;
    final ownsAuthService = accountLifecycleAuthService == null;
    final authService = accountLifecycleAuthService ?? AthenaAuthService();
    final lifecycle = AccountLifecycleService(
      authService: authService,
      session: activeSession,
    );
    try {
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        isDismissible: false,
        enableDrag: false,
        builder: (sheetContext) => SafeArea(
          child: Padding(
            padding: EdgeInsets.fromLTRB(
              16,
              16,
              16,
              16 + MediaQuery.viewInsetsOf(sheetContext).bottom,
            ),
            child: SingleChildScrollView(
              child: AccountClosurePanel(
                onClose: (password) => lifecycle.closeCurrentAccount(
                  currentPassword: password,
                ),
                onCancel: () => Navigator.of(sheetContext).pop(),
                onClosed: () {
                  if (!sheetContext.mounted || !context.mounted) return;
                  Navigator.of(sheetContext).pop();
                  Navigator.of(context).pushNamedAndRemoveUntil(
                    AppRoutes.welcome,
                    (route) => false,
                  );
                },
              ),
            ),
          ),
        ),
      );
    } finally {
      if (ownsAuthService) authService.dispose();
    }
  }

  Future<void> _openPersonalization(
    BuildContext context,
    AuthSession activeSession,
  ) async {
    if (!activeSession.isAuthenticated) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => ProfilePersonalizationSheet(
        service: service,
        session: activeSession,
      ),
    );
  }
}

class ProfilePersonalizationSheet extends StatefulWidget {
  const ProfilePersonalizationSheet({
    super.key,
    this.service,
    this.session,
  });

  final UserPreferencesService? service;
  final AuthSession? session;

  @override
  State<ProfilePersonalizationSheet> createState() =>
      _ProfilePersonalizationSheetState();
}

class _ProfilePersonalizationSheetState
    extends State<ProfilePersonalizationSheet> {
  late final UserPreferencesService _service;
  late final bool _ownsService;
  UserPersonalization? _personalization;
  bool _busy = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _ownsService = widget.service == null;
    _service = widget.service ??
        UserPreferencesService(session: widget.session ?? AuthSession.instance);
    _load();
  }

  @override
  void dispose() {
    if (_ownsService) _service.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    if (mounted) {
      setState(() {
        _busy = true;
        _error = null;
        _personalization = null;
      });
    }
    try {
      final value = await _service.loadPersonalization();
      if (!mounted) return;
      setState(() => _personalization = value);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _personalization = null;
        _error =
            'No se pudo validar la personalización protegida. No se aplicará ninguna adaptación local.';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          16,
          16,
          16,
          16 + MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: SingleChildScrollView(
          child: UserPersonalizationPanel(
            personalization: _personalization,
            busy: _busy,
            error: _error,
            onReload: _load,
          ),
        ),
      ),
    );
  }
}
