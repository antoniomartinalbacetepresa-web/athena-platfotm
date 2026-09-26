import 'package:flutter/foundation.dart';

import '../models/recommendation_learning_status.dart';
import '../services/recommendation_learning_status_provider.dart';

class RecommendationLearningController extends ChangeNotifier {
  final RecommendationLearningStatusProvider provider;

  RecommendationLearningStatus? _status;
  bool _isLoading = false;
  String? _error;

  RecommendationLearningController({
    required this.provider,
  });

  RecommendationLearningStatus? get status => _status;

  bool get isLoading => _isLoading;

  String? get error => _error;

  Future<void> load({
    DateTime? asOf,
    String? modelVersion,
    int? horizonDays,
  }) async {
    if (_isLoading) {
      return;
    }

    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _status = await provider.getStatus(
        asOf: asOf,
        modelVersion: modelVersion,
        horizonDays: horizonDays,
      );
    } catch (error, stackTrace) {
      debugPrint('ERROR AL OBTENER EL ESTADO DE APRENDIZAJE DE ATHENA:');
      debugPrint(error.toString());
      debugPrint(stackTrace.toString());
      _status = null;
      _error = 'Error: ${error.toString()}';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  void clear() {
    _status = null;
    _isLoading = false;
    _error = null;
    notifyListeners();
  }
}
