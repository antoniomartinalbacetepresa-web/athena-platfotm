import 'package:flutter/foundation.dart';

import '../../models/portfolio_position.dart';
import '../../services/authenticated_portfolio_sync_service.dart';

enum PortfolioCloudSyncStatus { idle, syncing, success, failure }

class PortfolioCloudSyncController extends ChangeNotifier {
  PortfolioCloudSyncController({AuthenticatedPortfolioSyncService? service})
      : _service = service ?? AuthenticatedPortfolioSyncService(),
        _ownsService = service == null;

  final AuthenticatedPortfolioSyncService _service;
  final bool _ownsService;

  PortfolioCloudSyncStatus _status = PortfolioCloudSyncStatus.idle;
  String? _message;

  PortfolioCloudSyncStatus get status => _status;
  String? get message => _message;
  bool get isSyncing => _status == PortfolioCloudSyncStatus.syncing;
  bool get hasError => _status == PortfolioCloudSyncStatus.failure;

  Future<void> sync(Iterable<PortfolioPosition> positions) async {
    if (isSyncing) return;
    final snapshot = positions.toList(growable: false);
    if (snapshot.isEmpty) {
      _status = PortfolioCloudSyncStatus.failure;
      _message = 'No hay posiciones declaradas para sincronizar.';
      notifyListeners();
      return;
    }

    _status = PortfolioCloudSyncStatus.syncing;
    _message = 'Sincronizando posiciones declaradas con tu cuenta ATHENA…';
    notifyListeners();

    try {
      final report = await _service.syncDeclaredPositions(snapshot);
      _status = PortfolioCloudSyncStatus.success;
      _message =
          'Sincronización completada: ${report.upsertedPositionCount} de '
          '${report.localPositionCount} posiciones declaradas actualizadas. '
          'ATHENA no ha enviado coste de compra, P/L ni fechas de coste y no '
          'ha eliminado posiciones remotas automáticamente.';
    } catch (_) {
      _status = PortfolioCloudSyncStatus.failure;
      _message =
          'No se pudo sincronizar la cartera autenticada. La cartera local no '
          'se ha modificado y ATHENA no aplica cambios destructivos como fallback.';
    }
    notifyListeners();
  }

  void clearMessage() {
    if (isSyncing) return;
    _status = PortfolioCloudSyncStatus.idle;
    _message = null;
    notifyListeners();
  }

  @override
  void dispose() {
    if (_ownsService) _service.dispose();
    super.dispose();
  }
}
