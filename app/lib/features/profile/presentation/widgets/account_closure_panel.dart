import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';

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
  bool _busy = false;
  String? _error;

  bool get _canSubmit =>
      !_busy &&
      _passwordController.text.isNotEmpty &&
      _confirmationController.text.trim() == _confirmationPhrase;

  @override
  void dispose() {
    _passwordController.dispose();
    _confirmationController.dispose();
    super.dispose();
  }

  void _changed(String _) => setState(() {});

  Future<void> _submit() async {
    if (!_canSubmit) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.onClose(_passwordController.text);
      if (!mounted) return;
      widget.onClosed();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error =
            'No se pudo cerrar la cuenta. Comprueba la contraseña actual y vuelve a intentarlo.';
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
          const Row(
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
          const SizedBox(height: 10),
          const Text(
            'Esta acción es irreversible. El backend revocará la sesión, anonimizará la identidad y eliminará las preferencias protegidas y las posiciones actuales asociadas a la cuenta.',
            style: TextStyle(color: AthenaColors.textSecondary, height: 1.4),
          ),
          const SizedBox(height: 8),
          const Text(
            'La evidencia histórica append-only y las copias de seguridad pueden estar sujetas a una política de retención y no se presentan como borradas inmediatamente.',
            key: Key('account-closure-retention-note'),
            style: TextStyle(
              color: AthenaColors.textSecondary,
              fontSize: 12,
              height: 1.4,
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
            onChanged: _changed,
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
            onChanged: _changed,
            decoration: const InputDecoration(
              labelText: 'Escribe ELIMINAR para confirmar',
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(
              _error!,
              key: const Key('account-closure-error'),
              style: const TextStyle(color: Colors.redAccent, height: 1.35),
            ),
          ],
          const SizedBox(height: 18),
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
