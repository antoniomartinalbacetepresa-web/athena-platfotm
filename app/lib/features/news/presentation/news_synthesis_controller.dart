import 'package:flutter/foundation.dart';

import '../models/verified_news_synthesis.dart';
import '../services/athena_backend_news_synthesis_service.dart';

class NewsSynthesisController extends ChangeNotifier {
  final AthenaBackendNewsSynthesisService service;

  NewsSynthesisController({required this.service});

  VerifiedNewsSynthesis? synthesis;
  Object? error;
  bool loading = false;
  int _requestVersion = 0;
  bool _disposed = false;

  Future<void> load() async {
    if (_disposed || loading) return;
    final requestVersion = ++_requestVersion;
    loading = true;
    error = null;
    synthesis = null;
    notifyListeners();
    try {
      final nextSynthesis = await service.getLatest();
      if (!_disposed && requestVersion == _requestVersion) {
        synthesis = nextSynthesis;
      }
    } catch (caught) {
      if (!_disposed && requestVersion == _requestVersion) {
        synthesis = null;
        error = caught;
      }
    } finally {
      if (!_disposed && requestVersion == _requestVersion) {
        loading = false;
        notifyListeners();
      }
    }
  }

  Future<void> retry() => load();

  /// Invalidate outstanding requests before changing the News data boundary.
  void clear() {
    if (_disposed) return;
    _requestVersion++;
    synthesis = null;
    error = null;
    loading = false;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _requestVersion++;
    super.dispose();
  }
}
