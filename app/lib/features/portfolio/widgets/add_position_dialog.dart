import 'package:flutter/material.dart';

import '../../../core/theme/athena_colors.dart';
import '../../../core/theme/athena_radius.dart';
import '../../../core/theme/athena_spacing.dart';
import '../../market/di/market_dependencies.dart';
import '../../market/repositories/market_repository.dart';

class AddPositionDialog extends StatefulWidget {
  final MarketRepository? marketRepository;

  const AddPositionDialog({
    super.key,
    this.marketRepository,
  });

  @override
  State<AddPositionDialog> createState() => _AddPositionDialogState();
}

class _AddPositionDialogState extends State<AddPositionDialog> {
  final _formKey = GlobalKey<FormState>();

  final _symbolController = TextEditingController();
  final _companyController = TextEditingController();
  final _sharesController = TextEditingController();
  final _averagePriceController = TextEditingController();

  MarketDependencies? _marketDependencies;
  late final MarketRepository _marketRepository;

  bool _isSaving = false;
  String? _quoteError;

  @override
  void initState() {
    super.initState();

    final injectedRepository = widget.marketRepository;
    if (injectedRepository != null) {
      _marketRepository = injectedRepository;
    } else {
      _marketDependencies = MarketDependencies.create();
      _marketRepository = _marketDependencies!.repository;
    }
  }

  @override
  void dispose() {
    _symbolController.dispose();
    _companyController.dispose();
    _sharesController.dispose();
    _averagePriceController.dispose();
    _marketDependencies?.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_isSaving || !_formKey.currentState!.validate()) {
      return;
    }

    final symbol = _symbolController.text.trim().toUpperCase();
    final shares = _parseNumber(_sharesController.text);
    final averagePrice = _parseNumber(_averagePriceController.text);

    setState(() {
      _isSaving = true;
      _quoteError = null;
    });

    try {
      final quote = await _marketRepository.getQuote(symbol);
      final currentPrice = quote.currentPrice;

      if (!currentPrice.isFinite || currentPrice <= 0) {
        throw StateError(
          'La fuente de mercado no devolvió un precio actual válido.',
        );
      }

      if (!mounted) {
        return;
      }

      Navigator.of(context).pop(
        AddPositionResult(
          symbol: symbol,
          companyName: _companyController.text.trim(),
          shares: shares,
          averagePrice: averagePrice,
          currentPrice: currentPrice,
          currentPriceUpdatedAt: quote.updatedAt,
        ),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }

      setState(() {
        _isSaving = false;
        _quoteError =
            'No se pudo verificar el precio actual con el backend de ATHENA. '
            'La posición no se guardará con un precio manual o estimado.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AthenaColors.card,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AthenaRadius.lg),
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
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _field(
                  controller: _symbolController,
                  label: 'Ticker',
                  hint: 'Ej. MSFT',
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'Introduce el ticker';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: AthenaSpacing.md),
                _field(
                  controller: _companyController,
                  label: 'Empresa',
                  hint: 'Ej. Microsoft',
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'Introduce el nombre de la empresa';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: AthenaSpacing.md),
                _field(
                  controller: _sharesController,
                  label: 'Número de acciones',
                  hint: 'Ej. 15',
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  validator: _validateNumber,
                ),
                const SizedBox(height: AthenaSpacing.md),
                _field(
                  controller: _averagePriceController,
                  label: 'Precio medio de compra',
                  hint: 'Ej. 350',
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  validator: _validateNumber,
                ),
                const SizedBox(height: AthenaSpacing.md),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(AthenaSpacing.md),
                  decoration: BoxDecoration(
                    color: AthenaColors.cardSecondary,
                    borderRadius: BorderRadius.circular(AthenaRadius.md),
                    border: Border.all(color: AthenaColors.border),
                  ),
                  child: const Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(
                        Icons.cloud_done_outlined,
                        color: AthenaColors.textSecondary,
                        size: 20,
                      ),
                      SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'El precio actual se obtiene del backend de ATHENA al '
                          'guardar. No se aceptan precios actuales introducidos '
                          'manualmente.',
                          style: TextStyle(
                            color: AthenaColors.textSecondary,
                            fontSize: 12,
                            height: 1.35,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                if (_quoteError != null) ...[
                  const SizedBox(height: AthenaSpacing.md),
                  Text(
                    _quoteError!,
                    style: const TextStyle(
                      color: Color(0xFFFF6B6B),
                      fontSize: 12,
                      height: 1.35,
                    ),
                  ),
                ],
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
          onPressed: _isSaving ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        ElevatedButton(
          onPressed: _isSaving ? null : _save,
          child: _isSaving
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Guardar posición'),
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
      enabled: !_isSaving,
      keyboardType: keyboardType,
      style: const TextStyle(color: AthenaColors.text),
      validator: validator,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        labelStyle: const TextStyle(color: AthenaColors.textSecondary),
        hintStyle: const TextStyle(color: AthenaColors.textSecondary),
        filled: true,
        fillColor: AthenaColors.background,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.all(Radius.circular(AthenaRadius.md)),
        ),
      ),
    );
  }

  String? _validateNumber(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Introduce un valor';
    }

    final number = double.tryParse(value.trim().replaceAll(',', '.'));
    if (number == null || !number.isFinite) {
      return 'Introduce un número válido';
    }

    if (number <= 0) {
      return 'El valor debe ser mayor que 0';
    }

    return null;
  }

  double _parseNumber(String value) {
    return double.parse(value.trim().replaceAll(',', '.'));
  }
}

class AddPositionResult {
  final String symbol;
  final String companyName;
  final double shares;
  final double averagePrice;
  final double currentPrice;
  final DateTime currentPriceUpdatedAt;

  const AddPositionResult({
    required this.symbol,
    required this.companyName,
    required this.shares,
    required this.averagePrice,
    required this.currentPrice,
    required this.currentPriceUpdatedAt,
  });
}
