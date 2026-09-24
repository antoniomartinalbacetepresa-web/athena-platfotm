import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../auth/services/athena_auth_account_closure.dart';

class AccountClosurePanel extends StatefulWidget {
  const AccountClosurePanel({
    super.key,
    required this.onClose,
    required this.onCancel,
    required this.onClosed,
  });

  final Future<void> Function(String currentPassword) onClose;
  final VoidCallback onCancel;
  final VoidCallback onClosed;

  @override
  State<AccountClosurePanel> createState() => _AccountClosurePanelState();
}

class _AccountClosurePanelState extends State<AccountClosurePanel> {
  static const _confirmationPhrase = 'ELIMINAR';

  final TextEditingController _passwordController = TextEditingController();
  final TextEditingController _confirmationController = TextEditingController();
  String _password = '';
  String _confirmation = '';
  bool _busy = false;
  String? _error;

  bool get _canSubmit =>
      !_busy &&
      _password.isNotEmpty &&
      _confirmation.trim() == _confirmationPhrase;

  @override
  void dispose() {
    _passwordController.dispose();
    _confirmationController.dispose();
    super.dispose();
  }

  void _passwordChanged(String value) {
    setState(() => _password = value);
  }

  void _confirmationChanged(String value) {
    setState(() => _confirmation = value);
  }

  Future<void> _submit() async {
    if (!_canSubmit) return;
    final currentPassword = _password;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.onClose(currentPassword);
      if (!mounted) return;
      widget.onClosed();
    } on AccountClosureRejectedException {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error =
            'La contraseña actual no es correcta. La cuenta sigue abierta y la sesión se conserva.';
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error =
            'No se pudo confirmar el cierre de la cuenta. Vuelve a intentarlo cuando el servicio esté disponible.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('account-closure-panel'),
      constraints: const BoxConstraints(maxWidth: 620),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.redAccent.withValues(alpha: 0.45)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            container: true,
            header: true,
            label: 'Cerrar cuenta',
            child: const Row(
              children: [
                Icon(Icons.warning_amber_rounded, color: Colors.redAccent),
                SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Cerrar cuenta',
                    style: TextStyle(
                      color: AthenaColors.text,
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
          Semantics(
            container: true,
            label:
                'Acción irreversible. El cierre revoca la sesión, anonimiza la identidad y elimina preferencias protegidas y posiciones actuales asociadas a la cuenta.',
            child: const Text(
              'Esta acción es irreversible. El backend revocará la sesión, anonimizará la identidad y eliminará las preferencias protegidas y las posiciones actuales asociadas a la cuenta.',
              key: Key('account-closure-irreversible-note'),
              style: TextStyle(color: AthenaColors.textSecondary, height: 1.4),
            ),
          ),
          const SizedBox(height: 8),
          Semantics(
            container: true,
            label:
                'La evidencia histórica y las copias de seguridad pueden conservarse según la política de retención y no se consideran borradas inmediatamente.',
            child: const Text(
              'La evidencia histórica append-only y las copias de seguridad pueden estar sujetas a una política de retención y no se presentan como borradas inmediatamente.',
              key: Key('account-closure-retention-note'),
              style: TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 12,
                height: 1.4,
              ),
            ),
          ),
          const SizedBox(height: 18),
          TextField(
            key: const Key('account-closure-password'),
            controller: _passwordController,
            enabled: !_busy,
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            onChanged: _passwordChanged,
            decoration: const InputDecoration(
              labelText: 'Contraseña actual',
              helperText: 'Se usa para reautenticar el cierre en el backend.',
            ),
          ),
          const SizedBox(height: 14),
          TextField(
            key: const Key('account-closure-confirmation'),
            controller: _confirmationController,
            enabled: !_busy,
            autocorrect: false,
            enableSuggestions: false,
            textCapitalization: TextCapitalization.characters,
            onChanged: _confirmationChanged,
            decoration: const InputDecoration(
              labelText: 'Escribe ELIMINAR para confirmar',
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Semantics(
              container: true,
              liveRegion: true,
              label: _error,
              child: Text(
                _error!,
                key: const Key('account-closure-error'),
                style: const TextStyle(color: Colors.redAccent, height: 1.35),
              ),
            ),
          ],
          const SizedBox(height: 18),
          if (_busy)
            Semantics(
              container: true,
              liveRegion: true,
              label: 'Cerrando cuenta. Esperando confirmación del servidor.',
              child: const SizedBox.shrink(
                key: Key('account-closure-busy-announcement'),
              ),
            ),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              ElevatedButton.icon(
                key: const Key('account-closure-submit'),
                onPressed: _canSubmit ? _submit : null,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.redAccent,
                  foregroundColor: Colors.white,
                ),
                icon: _busy
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.delete_forever_outlined),
                label: Text(_busy ? 'CERRANDO…' : 'ELIMINAR CUENTA'),
              ),
              TextButton(
                key: const Key('account-closure-cancel'),
                onPressed: _busy ? null : widget.onCancel,
                child: const Text('CANCELAR'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
