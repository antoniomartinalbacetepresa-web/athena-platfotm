import 'package:flutter/foundation.dart';

import '../data/datasources/athena_backend_synthesis_data_source.dart';

class AthenaSynthesisController extends ChangeNotifier {
  final AthenaBackendSynthesisDataSource dataSource;

  AthenaSynthesisView? _synthesis;
  bool _isLoading = false;
  String? _error;
  String? _cycleHash;
  bool _latestRequested = false;
  int _requestVersion = 0;
  bool _disposed = false;

  AthenaSynthesisController({required this.dataSource});

  AthenaSynthesisView? get synthesis => _synthesis;
  bool get isLoading => _isLoading;
  String? get error => _error;
  String? get cycleHash => _cycleHash;
  bool get hasData => _synthesis != null;

  Future<void> loadLatest() async {
    if (_disposed || _isLoading) return;
    final requestVersion = ++_requestVersion;
    _latestRequested = true;
    _cycleHash = null;
    _synthesis = null;
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final result = await dataSource.getLatest();
      if (_disposed || requestVersion != _requestVersion || !_latestRequested) return;
      _synthesis = result;
    } catch (error, stackTrace) {
      debugPrint('ERROR AL OBTENER LA ÚLTIMA SÍNTESIS CANÓNICA DE ATHENA:');
      debugPrint(error.toString());
      debugPrint(stackTrace.toString());
      if (!_disposed && requestVersion == _requestVersion && _latestRequested) {
        _synthesis = null;
        _error = 'No se pudo verificar la síntesis ATHENA: ${error.toString()}';
      }
    } finally {
      if (!_disposed && requestVersion == _requestVersion && _latestRequested) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  Future<void> load(String cycleHash) async {
    if (_disposed || _isLoading) return;

    final requestVersion = ++_requestVersion;
    final requestedCycle = cycleHash.trim().toLowerCase();
    _latestRequested = false;
    _synthesis = null;
    _isLoading = true;
    _error = null;
    _cycleHash = requestedCycle;
    notifyListeners();

    try {
      final result = await dataSource.getForResearchCycle(requestedCycle);
      if (_disposed || requestVersion != _requestVersion ||
          _cycleHash != requestedCycle || _latestRequested) {
        return;
      }
      _synthesis = result;
    } catch (error, stackTrace) {
      debugPrint('ERROR AL OBTENER LA SÍNTESIS CANÓNICA DE ATHENA:');
      debugPrint(error.toString());
      debugPrint(stackTrace.toString());
      if (!_disposed && requestVersion == _requestVersion &&
          _cycleHash == requestedCycle && !_latestRequested) {
        _synthesis = null;
        _error = 'No se pudo verificar la síntesis ATHENA: ${error.toString()}';
      }
    } finally {
      if (!_disposed && requestVersion == _requestVersion &&
          _cycleHash == requestedCycle && !_latestRequested) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  Future<void> retry() async {
    if (_disposed || _isLoading) return;
    if (_latestRequested) {
      await loadLatest();
      return;
    }
    final current = _cycleHash;
    if (current == null || current.isEmpty) return;
    await load(current);
  }

  void clear() {
    if (_disposed) return;
    _requestVersion++;
    _latestRequested = false;
    _cycleHash = null;
    _synthesis = null;
    _isLoading = false;
    _error = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _requestVersion++;
    _synthesis = null;
    _isLoading = false;
    _error = null;
    _cycleHash = null;
    _latestRequested = false;
    super.dispose();
  }
}
