import 'package:flutter/foundation.dart';

import '../data/datasources/athena_backend_synthesis_data_source.dart';

class AthenaSynthesisController extends ChangeNotifier {
  final AthenaBackendSynthesisDataSource dataSource;

  AthenaSynthesisView? _synthesis;
  bool _isLoading = false;
  String? _error;
  String? _cycleHash;

  AthenaSynthesisController({required this.dataSource});

  AthenaSynthesisView? get synthesis => _synthesis;
  bool get isLoading => _isLoading;
  String? get error => _error;
  String? get cycleHash => _cycleHash;
  bool get hasData => _synthesis != null;

  Future<void> load(String cycleHash) async {
    if (_isLoading) return;

    final requestedCycle = cycleHash.trim().toLowerCase();
    _isLoading = true;
    _error = null;
    _cycleHash = requestedCycle;
    notifyListeners();

    try {
      final result = await dataSource.getForResearchCycle(requestedCycle);
      if (_cycleHash != requestedCycle) return;
      _synthesis = result;
    } catch (error, stackTrace) {
      debugPrint('ERROR AL OBTENER LA SÍNTESIS CANÓNICA DE ATHENA:');
      debugPrint(error.toString());
      debugPrint(stackTrace.toString());
      if (_cycleHash == requestedCycle) {
        _synthesis = null;
        _error = 'No se pudo verificar la síntesis ATHENA: ${error.toString()}';
      }
    } finally {
      if (_cycleHash == requestedCycle) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  Future<void> retry() async {
    final current = _cycleHash;
    if (current == null || current.isEmpty || _isLoading) return;
    await load(current);
  }

  void clear() {
    _cycleHash = null;
    _synthesis = null;
    _isLoading = false;
    _error = null;
    notifyListeners();
  }
}
