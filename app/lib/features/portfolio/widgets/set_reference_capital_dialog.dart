import 'package:flutter/material.dart';

import '../../../core/theme/athena_colors.dart';
import '../../../core/theme/athena_radius.dart';
import '../../../core/theme/athena_spacing.dart';

class SetReferenceCapitalDialog extends StatefulWidget {
  final double? currentValue;

  const SetReferenceCapitalDialog({
    super.key,
    this.currentValue,
  });

  @override
  State<SetReferenceCapitalDialog> createState() =>
      _SetReferenceCapitalDialogState();
}

class _SetReferenceCapitalDialogState
    extends State<SetReferenceCapitalDialog> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    final current = widget.currentValue;
    _controller = TextEditingController(
      text: current != null && current > 0
          ? current.toStringAsFixed(2)
          : '',
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _save() {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    final value = double.parse(
      _controller.text.trim().replaceAll(',', '.'),
    );
    Navigator.of(context).pop(value);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AthenaColors.card,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
      ),
      title: const Text(
        'Capital de referencia',
        style: TextStyle(
          color: AthenaColors.text,
          fontWeight: FontWeight.bold,
        ),
      ),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Indica el capital total que quieres usar como referencia para '
                'la planificación de cartera. ATHENA no ejecutará operaciones '
                'ni generará asignaciones productivas mientras el motor siga '
                'en validación.',
                style: TextStyle(
                  color: AthenaColors.textSecondary,
                  fontSize: 13,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: AthenaSpacing.lg),
              TextFormField(
                controller: _controller,
                autofocus: true,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                style: const TextStyle(color: AthenaColors.text),
                decoration: const InputDecoration(
                  labelText: 'Capital (€)',
                  hintText: 'Ej. 10000',
                  labelStyle: TextStyle(color: AthenaColors.textSecondary),
                  hintStyle: TextStyle(color: AthenaColors.textSecondary),
                ),
                validator: (value) {
                  if (value == null || value.trim().isEmpty) {
                    return 'Introduce un capital de referencia';
                  }
                  final number = double.tryParse(
                    value.trim().replaceAll(',', '.'),
                  );
                  if (number == null || !number.isFinite) {
                    return 'Introduce un número válido';
                  }
                  if (number < 0) {
                    return 'El capital no puede ser negativo';
                  }
                  return null;
                },
                onFieldSubmitted: (_) => _save(),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        ElevatedButton(
          onPressed: _save,
          child: const Text('Guardar'),
        ),
      ],
    );
  }
}
