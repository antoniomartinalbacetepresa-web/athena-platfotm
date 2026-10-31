import 'package:flutter/foundation.dart';

import '../../../auth/services/athena_auth_service.dart';
import '../../models/portfolio_position.dart';
import '../../services/authenticated_portfolio_service.dart';
import '../../services/authenticated_portfolio_sync_service.dart';

enum PortfolioCloudSyncStatus {
  idle,
  syncing,
  success,
  failure,
  sessionRejected,
  authorityChanged,
}

class PortfolioCloudSyncController extends ChangeNotifier {
  PortfolioCloudSyncController({AuthenticatedPortfolioSyncService? service})
      : _service = service ?? AuthenticatedPortfolioSyncService(),
        _ownsService = service == null;

  final AuthenticatedPortfolioSyncService _service;
  final bool _ownsService;

  PortfolioCloudSyncStatus _status = PortfolioCloudSyncStatus.idle;
  String? _message;
  int _syncGeneration = 0;
  bool _inFlight = false;
  bool _disposed = false;

  PortfolioCloudSyncStatus get status => _status;
  String? get message => _message;
  bool get isSyncing => _inFlight;
  bool get hasError =>
      _status == PortfolioCloudSyncStatus.failure ||
      _status == PortfolioCloudSyncStatus.sessionRejected ||
      _status == PortfolioCloudSyncStatus.authorityChanged;
  bool get sessionRejected => _status == PortfolioCloudSyncStatus.sessionRejected;
  bool get authorityChanged => _status == PortfolioCloudSyncStatus.authorityChanged;

  /// Drop presentation state immediately when the authenticated authority changes.
  /// A previous request may finish later, but it cannot publish its result to
  /// the replacement owner's screen. In-flight work remains serialized.
  void invalidateAuthority() {
    if (_disposed) return;
    _syncGeneration += 1;
    _status = PortfolioCloudSyncStatus.idle;
    _message = null;
    notifyListeners();
  }

  Future<void> sync(Iterable<PortfolioPosition> positions) async {
    if (_disposed || _inFlight) return;
    final snapshot = positions.toList(growable: false);
    if (snapshot.isEmpty) {
      _status = PortfolioCloudSyncStatus.failure;
      _message = 'No hay posiciones declaradas para sincronizar.';
      notifyListeners();
      return;
    }

    final generation = ++_syncGeneration;
    _inFlight = true;
    _status = PortfolioCloudSyncStatus.syncing;
    _message = 'Sincronizando posiciones declaradas con tu cuenta ATHENA…';
    notifyListeners();

    try {
      final report = await _service.syncDeclaredPositions(snapshot);
      if (_disposed || generation != _syncGeneration) return;
      _status = PortfolioCloudSyncStatus.success;
      _message =
          'Sincronización completada: ${report.upsertedPositionCount} de '
          '${report.localPositionCount} posiciones declaradas actualizadas. '
          'ATHENA ha enviado símbolo, mercado, cantidad y precio medio de '
          'compra declarado a tu cuenta; el precio medio se almacena cifrado en el backend. '
          'No se han enviado P/L ni fechas de coste, y no se han eliminado '
          'posiciones remotas automáticamente.';
    } on AuthSessionRejectedException {
      if (_disposed || generation != _syncGeneration) return;
      _status = PortfolioCloudSyncStatus.sessionRejected;
      _message =
          'Tu sesión ATHENA ya no es válida. Inicia sesión de nuevo antes de sincronizar.';
    } on AuthenticatedPortfolioAuthorityChangedException {
      if (_disposed || generation != _syncGeneration) return;
      _status = PortfolioCloudSyncStatus.authorityChanged;
      _message =
          'La cuenta ATHENA cambió durante la sincronización. No se continuará '
          'con datos de la cuenta anterior; revisa la cartera antes de reintentar.';
    } catch (_) {
      if (_disposed || generation != _syncGeneration) return;
      _status = PortfolioCloudSyncStatus.failure;
      _message =
          'No se pudo sincronizar la cartera autenticada. La cartera local no '
          'se ha modificado y ATHENA no aplica cambios destructivos como fallback.';
    } finally {
      _inFlight = false;
      if (!_disposed) notifyListeners();
    }
  }

  void clearMessage() {
    if (_disposed || isSyncing) return;
    _status = PortfolioCloudSyncStatus.idle;
    _message = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _syncGeneration += 1;
    if (_ownsService) _service.dispose();
    super.dispose();
  }
}
