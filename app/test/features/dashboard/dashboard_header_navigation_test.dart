import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/dashboard/presentation/widgets/dashboard_header.dart';
import 'package:app/features/news/presentation/news_synthesis_controller.dart';
import 'package:app/features/news/presentation/pages/news_page.dart';
import 'package:app/features/news/services/athena_backend_news_synthesis_service.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('dashboard header uses compact navigation on narrow screens', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(500, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: DashboardHeader()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byIcon(Icons.menu_rounded), findsOneWidget);
    expect(find.byTooltip('Mercado'), findsNothing);
  });

  testWidgets('dashboard header exposes direct navigation on wide screens', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: DashboardHeader()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byTooltip('Mercado'), findsOneWidget);
    expect(find.byTooltip('Noticias'), findsOneWidget);
    expect(find.byTooltip('Inversores'), findsOneWidget);
    expect(find.byTooltip('Cartera'), findsOneWidget);
    expect(find.byTooltip('Perfil'), findsOneWidget);
  });

  testWidgets('wide dashboard navigation reaches every primary product route', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final visited = <String>[];
    await tester.pumpWidget(
      MaterialApp(
        home: const Scaffold(body: DashboardHeader()),
        onGenerateRoute: (settings) {
          visited.add(settings.name!);
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => Text('route:${settings.name}'),
          );
        },
      ),
    );

    for (final entry in const <String, String>{
      'Mercado': AppRoutes.market,
      'Noticias': AppRoutes.news,
      'Inversores': AppRoutes.investors,
      'Cartera': AppRoutes.portfolio,
      'Perfil': AppRoutes.profile,
    }.entries) {
      await tester.tap(find.byTooltip(entry.key));
      await tester.pumpAndSettle();
      expect(visited.last, entry.value);
      expect(find.text('route:${entry.value}'), findsOneWidget);
      Navigator.of(tester.element(find.text('route:${entry.value}'))).pop();
      await tester.pumpAndSettle();
    }
  });

  testWidgets('compact dashboard menu reaches every primary product route', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(500, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final visited = <String>[];
    await tester.pumpWidget(
      MaterialApp(
        home: const Scaffold(body: DashboardHeader()),
        onGenerateRoute: (settings) {
          visited.add(settings.name!);
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => Text('route:${settings.name}'),
          );
        },
      ),
    );

    for (final entry in const <String, String>{
      'Mercado': AppRoutes.market,
      'Noticias': AppRoutes.news,
      'Inversores': AppRoutes.investors,
      'Cartera': AppRoutes.portfolio,
      'Perfil': AppRoutes.profile,
    }.entries) {
      await tester.tap(find.byTooltip('Navegación'));
      await tester.pumpAndSettle();
      await tester.tap(find.text(entry.key));
      await tester.pumpAndSettle();
      expect(visited.last, entry.value);
      Navigator.of(tester.element(find.text('route:${entry.value}'))).pop();
      await tester.pumpAndSettle();
    }
  });

  testWidgets('wide Profile return refreshes owner projections only after pop',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final returned = <String>[];
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: DashboardHeader(onReturnFromRoute: returned.add),
      ),
      onGenerateRoute: (settings) => MaterialPageRoute<void>(
        settings: settings,
        builder: (_) => const Scaffold(body: Text('Profile is open')),
      ),
    ));

    await tester.tap(find.byTooltip('Perfil'));
    await tester.pumpAndSettle();
    expect(returned, isEmpty);
    Navigator.of(tester.element(find.text('Profile is open'))).pop();
    await tester.pumpAndSettle();
    expect(returned, [AppRoutes.profile]);
  });

  testWidgets('compact Portfolio return refreshes owner projections after pop',
      (tester) async {
    tester.view.physicalSize = const Size(500, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final returned = <String>[];
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: DashboardHeader(onReturnFromRoute: returned.add),
      ),
      onGenerateRoute: (settings) => MaterialPageRoute<void>(
        settings: settings,
        builder: (_) => const Scaffold(body: Text('Portfolio is open')),
      ),
    ));

    await tester.tap(find.byTooltip('Navegación'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cartera'));
    await tester.pumpAndSettle();
    expect(returned, isEmpty);
    Navigator.of(tester.element(find.text('Portfolio is open'))).pop();
    await tester.pumpAndSettle();
    expect(returned, [AppRoutes.portfolio]);
  });

  testWidgets(
    'dashboard to News is a real cross-surface route with fail-closed synthesis',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      var synthesisRequests = 0;
      final service = AthenaBackendNewsSynthesisService(
        baseUrl: 'http://athena.local',
        client: MockClient((request) async {
          synthesisRequests += 1;
          expect(
            request.url.path,
            '/api/v1/recommendations/professional-research/news-synthesis/latest',
          );
          return http.Response('{"detail":"unavailable"}', 503);
        }),
      );
      final controller = NewsSynthesisController(service: service);
      addTearDown(controller.dispose);
      addTearDown(service.dispose);

      await tester.pumpWidget(
        MaterialApp(
          home: const Scaffold(body: DashboardHeader()),
          onGenerateRoute: (settings) {
            if (settings.name == AppRoutes.news) {
              return MaterialPageRoute<void>(
                settings: settings,
                builder: (_) => NewsPage(
                  synthesisController: controller,
                  newsFeed: const SizedBox.shrink(),
                ),
              );
            }
            return null;
          },
        ),
      );

      await tester.tap(find.byTooltip('Noticias'));
      await tester.pump();
      await tester.pump();

      expect(
        ModalRoute.of(tester.element(find.text('NOTICIAS')))!.settings.name,
        AppRoutes.news,
      );
      expect(synthesisRequests, 1);
      expect(find.text('Reintentar'), findsOneWidget);
      expect(find.textContaining('ANÁLISIS ATHENA'), findsNothing);
    },
  );


  testWidgets('Dashboard refresh is accessible in wide and compact navigation',
      (tester) async {
    var refreshes = 0;
    await tester.binding.setSurfaceSize(const Size(1200, 800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: DashboardHeader(onRefresh: () => refreshes++),
      ),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Actualizar paneles del Dashboard'));
    expect(refreshes, 1);

    await tester.binding.setSurfaceSize(const Size(500, 800));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Navegación'), findsOneWidget);
    await tester.tap(find.byKey(const Key('dashboard-refresh-all')));
    expect(refreshes, 2);
  });

}
