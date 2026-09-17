import 'package:flutter/foundation.dart';

import '../models/verified_news_synthesis.dart';
import '../services/athena_backend_news_synthesis_service.dart';

class NewsSynthesisController extends ChangeNotifier {
  final AthenaBackendNewsSynthesisService service;

  NewsSynthesisController({required this.service});

  VerifiedNewsSynthesis? synthesis;
  Object? error;
  bool loading = false;

  Future<void> load() async {
    if (loading) return;
    loading = true;
    error = null;
    synthesis = null;
    notifyListeners();
    try {
      synthesis = await service.getLatest();
    } catch (caught) {
      synthesis = null;
      error = caught;
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> retry() => load();
}
