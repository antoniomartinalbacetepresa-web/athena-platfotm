import 'package:flutter/material.dart';

import '../../../core/theme/athena_colors.dart';
import '../../../core/theme/athena_radius.dart';
import '../../../core/theme/athena_spacing.dart';

class AddPositionDialog extends StatefulWidget {
  const AddPositionDialog({
    super.key,
  });

  @override
  State<AddPositionDialog> createState() =>
      _AddPositionDialogState();
}

class _AddPositionDialogState
    extends State<AddPositionDialog> {
  final _formKey = GlobalKey<FormState>();

  final _symbolController = TextEditingController();
  final _companyController = TextEditingController();
  final _sharesController = TextEditingController();
  final _averagePriceController = TextEditingController();
  final _currentPriceController = TextEditingController();

  @override
  void dispose() {
    _symbolController.dispose();
    _companyController.dispose();
    _sharesController.dispose();
    _averagePriceController.dispose();
    _currentPriceController.dispose();
    super.dispose();
  }

  void _save() {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    final shares = double.parse(
      _sharesController.text.trim().replaceAll(',', '.'),
    );

    final averagePrice = double.parse(
      _averagePriceController.text
          .trim()
          .replaceAll(',', '.'),
    );

    final currentPrice = double.parse(
      _currentPriceController.text
          .trim()
          .replaceAll(',', '.'),
    );

    Navigator.of(context).pop(
      AddPositionResult(
        symbol: _symbolController.text
            .trim()
            .toUpperCase(),
        companyName: _companyController.text.trim(),
        shares: shares,
        averagePrice: averagePrice,
        currentPrice: currentPrice,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AthenaColors.card,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(
          AthenaRadius.lg,
        ),
      ),
      title: const Text(
        'Añadir posición',
        style: TextStyle(
          color: AthenaColors.text,
          fontSize: 22,
          fontWeight: FontWeight.bold,
        ),
      ),
      content: SizedBox(
        width: 430,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _field(
                  controller: _symbolController,
                  label: 'Ticker',
                  hint: 'Ej. MSFT',
                  validator: (value) {
                    if (value == null ||
                        value.trim().isEmpty) {
                      return 'Introduce el ticker';
                    }

                    return null;
                  },
                ),

                const SizedBox(
                  height: AthenaSpacing.md,
                ),

                _field(
                  controller: _companyController,
                  label: 'Empresa',
                  hint: 'Ej. Microsoft',
                  validator: (value) {
                    if (value == null ||
                        value.trim().isEmpty) {
                      return 'Introduce el nombre de la empresa';
                    }

                    return null;
                  },
                ),

                const SizedBox(
                  height: AthenaSpacing.md,
                ),

                _field(
                  controller: _sharesController,
                  label: 'Número de acciones',
                  hint: 'Ej. 15',
                  keyboardType:
                      const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  validator: _validateNumber,
                ),

                const SizedBox(
                  height: AthenaSpacing.md,
                ),

                _field(
                  controller: _averagePriceController,
                  label: 'Precio medio de compra',
                  hint: 'Ej. 350',
                  keyboardType:
                      const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  validator: _validateNumber,
                ),

                const SizedBox(
                  height: AthenaSpacing.md,
                ),

                _field(
                  controller: _currentPriceController,
                  label: 'Precio actual',
                  hint: 'Ej. 420',
                  keyboardType:
                      const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  validator: _validateNumber,
                ),
              ],
            ),
          ),
        ),
      ),
      actionsPadding: const EdgeInsets.fromLTRB(
        AthenaSpacing.lg,
        0,
        AthenaSpacing.lg,
        AthenaSpacing.lg,
      ),
      actions: [
        TextButton(
          onPressed: () {
            Navigator.of(context).pop();
          },
          child: const Text(
            'Cancelar',
          ),
        ),
        ElevatedButton(
          onPressed: _save,
          child: const Text(
            'Guardar posición',
          ),
        ),
      ],
    );
  }

  Widget _field({
    required TextEditingController controller,
    required String label,
    required String hint,
    TextInputType? keyboardType,
    String? Function(String?)? validator,
  }) {
    return TextFormField(
      controller: controller,
      keyboardType: keyboardType,
      style: const TextStyle(
        color: AthenaColors.text,
      ),
      validator: validator,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        labelStyle: const TextStyle(
          color: AthenaColors.textSecondary,
        ),
        hintStyle: const TextStyle(
          color: AthenaColors.textSecondary,
        ),
        filled: true,
        fillColor: AthenaColors.background,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.all(
            Radius.circular(AthenaRadius.md),
          ),
        ),
      ),
    );
  }

  String? _validateNumber(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Introduce un valor';
    }

    final number = double.tryParse(
      value.trim().replaceAll(',', '.'),
    );

    if (number == null) {
      return 'Introduce un número válido';
    }

    if (number <= 0) {
      return 'El valor debe ser mayor que 0';
    }

    return null;
  }
}

class AddPositionResult {
  final String symbol;
  final String companyName;
  final double shares;
  final double averagePrice;
  final double currentPrice;

  const AddPositionResult({
    required this.symbol,
    required this.companyName,
    required this.shares,
    required this.averagePrice,
    required this.currentPrice,
  });
}