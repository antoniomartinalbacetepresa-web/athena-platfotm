import '../data/athena_backend_portfolio_allocation_authority_data_source.dart';
import '../data/athena_backend_portfolio_allocation_data_source.dart';
import '../data/athena_backend_portfolio_allocation_policy_data_source.dart';
import '../presentation/controllers/portfolio_allocation_controller.dart';
import '../presentation/controllers/portfolio_allocation_policy_controller.dart';

/// Construye la frontera Flutter de allocation contra un único backend ATHENA.
///
/// No selecciona política, no construye recomendaciones y no introduce
/// defaults económicos. Su única responsabilidad es garantizar que resolución
/// de autoridades, políticas persistidas y candidato de allocation compartan
/// exactamente el mismo backend configurado.
class PortfolioAllocationDependencies {
  static const String _defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  final AthenaBackendPortfolioAllocationAuthorityDataSource authorityDataSource;
  final AthenaBackendPortfolioAllocationDataSource allocationDataSource;
  final AthenaBackendPortfolioAllocationPolicyDataSource policyDataSource;
  final PortfolioAllocationController allocationController;
  final PortfolioAllocationPolicyController policyController;

  PortfolioAllocationDependencies({
    required this.authorityDataSource,
    required this.allocationDataSource,
    required this.policyDataSource,
    required this.allocationController,
    required this.policyController,
  });

  factory PortfolioAllocationDependencies.create({String? baseUrl}) {
    final effectiveBaseUrl = (baseUrl ?? _defaultBackendUrl).trim();
    if (effectiveBaseUrl.isEmpty) {
      throw StateError('ATHENA_BACKEND_URL no está configurada.');
    }
    final uri = Uri.tryParse(effectiveBaseUrl);
    if (uri == null ||
        !uri.hasScheme ||
        (uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.isEmpty) {
      throw StateError('ATHENA_BACKEND_URL no es una URL HTTP(S) válida.');
    }

    final normalizedBaseUrl = effectiveBaseUrl.endsWith('/')
        ? effectiveBaseUrl.substring(0, effectiveBaseUrl.length - 1)
        : effectiveBaseUrl;
    final authorityDataSource =
        AthenaBackendPortfolioAllocationAuthorityDataSource(
      baseUrl: normalizedBaseUrl,
    );
    final allocationDataSource = AthenaBackendPortfolioAllocationDataSource(
      baseUrl: normalizedBaseUrl,
    );
    final policyDataSource = AthenaBackendPortfolioAllocationPolicyDataSource(
      baseUrl: normalizedBaseUrl,
    );

    return PortfolioAllocationDependencies(
      authorityDataSource: authorityDataSource,
      allocationDataSource: allocationDataSource,
      policyDataSource: policyDataSource,
      allocationController: PortfolioAllocationController(
        authorityDataSource: authorityDataSource,
        allocationDataSource: allocationDataSource,
      ),
      policyController: PortfolioAllocationPolicyController(
        dataSource: policyDataSource,
      ),
    );
  }

  void dispose() {
    allocationController.dispose();
    policyController.dispose();
    authorityDataSource.dispose();
    allocationDataSource.dispose();
    policyDataSource.dispose();
  }
}
