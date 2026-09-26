import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../analysis/models/operational_readiness.dart';
import '../../../analysis/services/athena_readiness_service.dart';
import 'base/athena_card.dart';

class SystemReadinessPanel extends StatefulWidget {
  const SystemReadinessPanel({super.key});

  @override
  State<SystemReadinessPanel> createState() => _SystemReadinessPanelState();
}

class _SystemReadinessPanelState extends State<SystemReadinessPanel> {
  late final AthenaReadinessService _service;
  late Future<AthenaReadinessReport> _future;

  @override
  void initState() {
    super.initState();
    _service = AthenaReadinessService();
    _future = _service.getReport();
  }

  @override
  void dispose() {
    _service.dispose();
    super.dispose();
  }

  void _reload() {
    setState(() => _future = _service.getReport());
  }

  @override
  Widget build(BuildContext context) {
    return AthenaCard(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      child: FutureBuilder<AthenaReadinessReport>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: LinearProgressIndicator());
          }
          if (snapshot.hasError || snapshot.data == null) {
            return Row(
              children: [
                const Expanded(
                  child: Text(
                    'READINESS OPERATIVO NO DISPONIBLE',
                    style: TextStyle(
                      color: AthenaColors.textSecondary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                IconButton(
                  tooltip: 'Reintentar',
                  onPressed: _reload,
                  icon: const Icon(Icons.refresh, color: AthenaColors.textSecondary),
                ),
              ],
            );
          }

          final readiness = snapshot.data!.operationalReadiness;
          final percent = readiness.completionPercent.clamp(0, 100).toDouble();
          return Row(
            children: [
              SizedBox(
                width: 88,
                child: Text(
                  '${percent.toStringAsFixed(0)}%',
                  style: TextStyle(
                    color: readiness.ready ? AthenaColors.success : AthenaColors.primary,
                    fontSize: 28,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              Expanded(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'READINESS OPERATIVO',
                      style: TextStyle(
                        color: AthenaColors.text,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 6),
                    LinearProgressIndicator(value: percent / 100),
                    const SizedBox(height: 6),
                    Text(
                      '${readiness.passedGateCount}/${readiness.totalGateCount} puertas superadas'
                      '${readiness.blockers.isEmpty ? '' : ' · ${readiness.blockers.length} bloqueos'}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AthenaColors.textSecondary,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: 'Actualizar readiness',
                onPressed: _reload,
                icon: const Icon(Icons.refresh, color: AthenaColors.textSecondary),
              ),
            ],
          );
        },
      ),
    );
  }
}
