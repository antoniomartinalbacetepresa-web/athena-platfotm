# Trazabilidad maestra inicial — 27 de noviembre de 2026

Base inspeccionada: `c60508a75e486e630905299864c546242497951e`, rama
`dev/real-market-backend`. Documento aditivo: conserva los canónicos, el contrato
horario y todo requisito histórico, incluso cuando no tenga aún una fila propia.
Incorpora las 17 áreas del contrato maestro aportado por el propietario el
27-11-2026 y las ampliaciones históricas localizadas. **Cobertura todavía parcial;
porcentaje no certificable.** No constituye aceptación operativa ni habilitación
de órdenes, conexión de cuentas, uso de credenciales reales o adquisición de datos.

## Evidencia y precedencia

Se inspeccionaron AGENTS, los cinco documentos canónicos, el registro de fuentes,
el modelo de datos, arquitectura Dashboard, ATHENA OS, inventarios MD/JSON,
registro de aceptación, auditoría XTrend y evaluación Capital.com. Se localizaron
los archivos de código/API/UI/pruebas citados y se leyeron los contratos de los
componentes principales de Market, ciclo, Radar y patrones. No se ejecutaron
pruebas nuevas en esta revisión documental. La existencia de un archivo de test
no acredita que pase; la entrega funcional y su CI exact-SHA se registran por
separado en el informe de ejecución. Los ejemplos de código son puntos de
entrada, no una auditoría de todas sus ramas ni de los miles de pruebas.

Estados usados: **En desarrollo** = componentes localizados pero flujo completo
pendiente; **Bloqueada** = necesita una dependencia externa o evidencia operativa;
**Pendiente de localizar/verificar** = esta revisión no demuestra implementación
ni ausencia. Ninguna fila de esta matriz se eleva a **Aceptada**. Los estados
históricos `implemented_ci` del JSON se conservan como afirmaciones de su SHA
original, sin trasladarlos automáticamente al HEAD actual.

Fuentes: `docs/MASTER_PROJECT.md`, `docs/ROADMAP.md`,
`docs/HOURLY_EXECUTION_2026_12_31.md`, `docs/DELIVERY_EXECUTION_2027.md`,
`docs/ACCEPTANCE_INVENTORY.md`, `docs/ACCEPTANCE_INVENTORY.json`,
`docs/ACCEPTANCE_EVIDENCE_REGISTER.md`, `docs/API_SOURCES.md`, `docs/DATA_MODEL.md`,
`docs/dashboard_v2_architecture.md`, `docs/XTREND_LITE_GAP_AUDIT.md`,
`docs/providers/CAPITAL_COM_EVALUATION.md` y contrato maestro del 27-11.
El objetivo vigente es 31-12-2026; los requisitos ajenos a la fecha del contrato
de entrega previo siguen vigentes. Los nuevos requisitos de ejecución futura no
autorizan activación real ni rebajan los controles actuales de investigación.

## Matriz por área obligatoria

Los códigos T01–T17 son referencias de esta revisión, no nuevos criterios
ponderados. Las referencias CORE/PRODUCT de esta tabla pertenecen únicamente a
`docs/ACCEPTANCE_INVENTORY.md`; los identificadores JSON se indican por separado.

| Ref. y alcance preservado | Implementación y contrato localizados | Consumidor UI / prueba localizada | Estado y aceptación que falta |
| --- | --- | --- | --- |
| T01 Market: identidad, acciones/ETF/índices/materias primas/FX/cripto, OHLCV diario/intradía, Twelve Data, 365 días, PIT, ajustes, calendario, liquidez, calidad, caché, comparadores | `backend/app/services/twelve_data_history_service.py`; `backend/app/services/persisted_market_history_service.py`; `backend/app/repositories/market_observation_repository.py`; `backend/app/api/market.py` (`/api/v1/market/history/persisted`); `backend/app/repositories/fx_rate_repository.py` | `app/lib/features/market/data/providers/athena_backend_market_data_provider.dart`; `app/lib/features/market/presentation/pages/market_page.dart`; `backend/tests/test_twelve_data_history_service.py`; `backend/tests/test_persisted_market_history_api.py`; `app/test/features/market/persisted_market_history_test.dart` | En desarrollo; datos reales bloqueados. CORE-001/006/007/008/012, PRODUCT-001/007; JSON HIST-PIT/HIST-365/HIST-CORP/DATA-LICENSE. Transporte persistido existe; calendario acreditado, fuente secundaria, derechos por activo, intradía, ajustes y cobertura real no quedan aceptados. |
| T02 News: RSS, economía/empresa/sector/macro, deduplicación, emisor, sentimiento, credibilidad, catalizadores, síntesis, alertas y trazabilidad | `backend/app/services/google_news_service.py`; `backend/app/services/recommendation_news_synthesis_service.py`; `backend/app/api/news.py` (`/api/v1/news/feed`, `/company-evidence`) | `app/lib/features/news/presentation/pages/news_page.dart`; `app/lib/features/news/services/athena_backend_news_synthesis_service.dart`; `app/test/features/news/verified_news_synthesis_acceptance_test.dart`; `backend/tests/test_recommendation_news_synthesis_cycle_api.py` | En desarrollo; CORE-014, PRODUCT-008; JSON NEWS-FEED/NEWS-SYNTH/NEWS-REAL. Faltan derechos, corroboración real y recorrido desplegado; alertas completas no auditadas. |
| T03 Investors: inversores/gestores/instituciones, posiciones publicadas, estrategias, calidad y antigüedad | `backend/app/services/sec_13f_filing_service.py`; `backend/app/services/sec_13f_information_table_service.py`; `backend/app/api/sec.py` (`institutional-filings`, `institutional-holdings/latest`, `insider-filings`); `backend/app/api/recommendation_investors_synthesis.py` | `app/lib/features/investors/presentation/pages/investors_page.dart`; `backend/tests/test_sec_13f_api.py`; `app/test/features/investors/investors_page_acceptance_test.dart` | En desarrollo; CORE-014, PRODUCT-002/026; JSON INVEST-13F. Un 13F es una divulgación retrasada, nunca ejecución en tiempo real. Faltan corroboración, derechos y aceptación transversal real. |
| T04 Núcleo ATHENA: técnico/fundamental/macro/noticias, oportunidades, anomalías, valoración/escenarios, confianza, contradicciones, abstención, ciclo idempotente | `backend/app/services/recommendation_professional_research_cycle_service.py`; `backend/app/repositories/recommendation_professional_research_cycle_repository.py`; `backend/app/api/recommendation_professional_research_cycle.py` (`research-cycle`, recuperación por hash); `backend/app/api/recommendation_latest_athena_synthesis.py` | `app/lib/features/recommendations/presentation/pages/athena_ai_page.dart`; `app/lib/features/recommendations/presentation/athena_synthesis_panel.dart`; `backend/tests/test_recommendation_professional_research_cycle_persistence.py` | En desarrollo; CORE-002/003/008/009/010/014; JSON AI-CYCLE/AI-OLLAMA/AI-REAL. Falta cadena real licenciada y evaluación prospectiva. Ollama sigue opt-in y explicativo; ninguna salida del modelo constituye autoridad de orden. |
| T05 Estrategias: técnico/fundamental, momentum, tendencia, reversión, rupturas, rebotes, RVOL, liquidez, volatilidad, noticias, scalping/intradía/horas-días/swing y combinaciones; mínimo previo de 25 sesiones | `backend/app/services/opportunity_exit_pattern_service.py`; `app/lib/features/analysis/domain/services/technical_analysis_calculator.dart`; `backend/app/api/market.py` | `app/lib/features/market/presentation/widgets/market_pattern_readiness_panel.dart`; `backend/tests/test_opportunity_exit_pattern_service.py`; `app/test/features/analysis/domain/services/technical_analysis_calculator_test.dart` | En desarrollo; CORE-004/012, PRODUCT-024. El patrón leído usa 20 sesiones previas y es descriptivo: **no demuestra** la estrategia de mínimo de 25 sesiones, reglas ejecutables/versionadas, salidas, costes ni rentabilidad OOS. La biblioteca completa de estrategias queda pendiente de descomposición y prueba. |
| T06 Radar: escaneo, movimientos/volumen/rupturas/rebotes/volatilidad/catalizadores, filtros, seguimiento, alertas y explicación | `backend/app/services/recommendation_athena_radar_service.py`; `backend/app/api/recommendation_athena_radar.py` (`athena-radar`) | Consumidor dentro del ciclo profesional; `backend/tests/test_recommendation_athena_radar.py`; `backend/tests/test_recommendation_professional_research_cycle_radar_boundary.py` | En desarrollo; CORE-004, PRODUCT-018/019; JSON RADAR. La cola de urgencia investigadora localizada no equivale a un escáner operativo completo ni a clasificación de rentabilidad. Interfaz dedicada, listas, alertas y E2E pendientes de verificar. |
| T07 Portfolio: posiciones, rentabilidad, capital/liquidez, exposición/concentración, costes/drawdown/benchmark, historial, riesgo y conciliación | `backend/app/api/user_portfolio.py`; `backend/app/api/recommendation_portfolio_event_ledger.py`; `backend/app/api/recommendation_portfolio_performance_attribution.py`; `backend/app/services/recommendation_portfolio_performance_attribution_service.py` | `app/lib/features/portfolio/presentation/pages/authenticated_portfolio_page.dart`; `app/lib/features/portfolio/presentation/widgets/authenticated_portfolio_history_panel.dart`; `backend/tests/test_user_portfolio_api.py`; `backend/tests/test_recommendation_portfolio_event_ledger_api.py` | En desarrollo; PRODUCT-003/009/022/027; JSON PORT-OWNER/PORT-FX/PORT-DEPLOY. Separar carteras simuladas/reales; los fixtures `broker_statement` no prueban conexión ni conciliación con un bróker. Faltan aceptación operativa y gestión de claves. |
| T08 Journal: decisiones, razones, señales/contexto/riesgos, resultados/errores, expectativas y auditoría | `backend/app/services/recommendation_investment_journal_service.py`; `backend/app/repositories/recommendation_investment_journal_repository.py`; `backend/app/api/recommendation_investment_journal.py` | Ciclo privado y transporte histórico; `backend/tests/test_recommendation_investment_journal_persistence.py` | En desarrollo; CORE-009; JSON JOURNAL. Revisión histórica, navegación dedicada y aprendizaje vinculado a resultados reales pendientes de aceptación. |
| T09 Devil's Advocate: objeciones, sesgos, contradicciones, escenarios adversos, insuficiencia de datos y bloqueo objetivo antes de ejecución | `backend/app/services/recommendation_devils_advocate_service.py`; `backend/app/api/recommendation_devils_advocate.py` (`devils-advocate`) | Ciclo profesional; `backend/tests/test_recommendation_devils_advocate.py` | En desarrollo; CORE-009, PRODUCT-028; JSON DEVILS. Revisión investigadora localizada; no se acredita un bloqueo determinista conectado a un motor de órdenes. |
| T10 Backtesting: simulación reproducible, OOS/walk-forward, sesgos, comisiones/spread/slippage/liquidez/latencia/financiación, estrés y benchmark | `backend/app/services/recommendation_shadow_walk_forward_service.py`; `backend/app/services/recommendation_shadow_temporal_split_service.py`; `backend/app/api/recommendation_research_forecast_evaluation.py`; `backend/app/api/recommendation_shadow_operations.py` | `backend/tests/test_recommendation_shadow_walk_forward_service.py`; `backend/tests/test_recommendation_shadow_walk_forward_macro_integration.py` | En desarrollo; CORE-005/007/011, PRODUCT-020/024; JSON LEARN-OOS. Infraestructura shadow no acredita simulador completo de órdenes ni tratamiento completo de sesgos/costes. Validación longitudinal real bloqueada. |
| T11 Aprendizaje: resultados, regímenes, degradación, calibración, falsos positivos, propuestas, versiones/promoción/rollback | `backend/app/services/recommendation_calibration_service.py`; `backend/app/services/recommendation_learning_status_service.py`; `backend/app/services/governed_forecast_error_oos_service.py` | `app/lib/features/recommendations/controllers/recommendation_learning_controller.dart`; `backend/tests/test_recommendation_learning_governance_integration.py`; `backend/tests/test_recommendation_calibration_service.py` | En desarrollo; CORE-005/011/013, PRODUCT-012; JSON LEARN-ENGINE/LEARN-OOS/ML-OWN. Faltan observaciones longitudinales y promoción/rollback operativos; límites de riesgo y permisos no son modificables por aprendizaje. |
| T12 Ejecución autónoma futura: propuestas, compras/ventas, gestión de posiciones/salidas, conciliación, idempotencia, supervisión y registro | No se localizó un motor de órdenes o adaptador de ejecución en la búsqueda focalizada de código/API de esta revisión. Los recibos `recommendation_research_model_execution_receipt_service.py` corresponden a ejecución de modelos de investigación. | No se localizó prueba de ejecución de órdenes en esta revisión. Los estados/ledger de cartera no sustituyen un adaptador operativo. | Pendiente de localizar/verificar e implementar donde falte; PRODUCT-005/016. Arquitectura desacoplada y fases 1–6 obligatorias. La preparación técnica para dinero real debe permanecer deshabilitada por defecto. |
| T13 Capital.com prioritario para evaluación; conservar IBKR, contratos/API/Spain/instrumentos/autenticación/límites/sesiones/órdenes/costes/datos | `docs/providers/CAPITAL_COM_EVALUATION.md`; `docs/API_SOURCES.md`; registros PRODUCT-005/016 | No se localizó adaptador Capital.com/IBKR en la búsqueda focalizada. No se consultaron cuentas ni documentación oficial remota en esta revisión. | Bloqueada para conexión operativa; pendiente evaluación oficial actual. La nota histórica es de proveedor secundario y no se modifica retrospectivamente. El nuevo contrato prioriza la evaluación operativa Capital.com sin designar unilateralmente el bróker definitivo ni confundir CFDs y acciones. |
| T14 Riesgo integral: capital/tamaño/exposición/pérdida diaria/drawdown/concentración/liquidez/frecuencia, duplicados, precios obsoletos, desconexión, kill switch y reinicios | `backend/app/services/recommendation_factor_risk_service.py`; `backend/app/api/recommendation_factor_risk.py`; componentes de políticas/autoridad en `backend/app/api/portfolio_allocation_policy.py` y `backend/app/api/portfolio_allocation_authority.py` | `backend/tests/test_recommendation_factor_risk_service.py`; componentes Portfolio existentes | En desarrollo; CORE-003/010, PRODUCT-016. Riesgo analítico y política de cartera no prueban controles preorden/postorden, kill switch ni pérdida diaria en un motor automático. Límites monetarios finales y activación requieren aprobación independiente. |
| T15 Flutter: Dashboard, Market, News, Investors, ATHENA, Radar/Portfolio/Journal/Advocate, estrategias/backtest/alertas, supervisor/riesgo/conexiones, accesibilidad, rendimiento, navegación y despliegues | `app/lib/features/market/presentation/pages/market_page.dart`; `app/lib/features/news/presentation/pages/news_page.dart`; `app/lib/features/investors/presentation/pages/investors_page.dart`; páginas Portfolio/Profile/ATHENA citadas arriba | `app/test/features/market/market_page_integration_test.dart`; `.github/workflows/validate.yml`; pruebas de aceptación por superficie | En desarrollo; PRODUCT-001/002/006/010/011/012/014/015. No se equipara existencia de pantallas principales con cobertura de todas las pantallas requeridas. Faltan auditoría de navegación completa, ventanas/teclado, rendimiento y Windows operativo. |
| T16 Backend/API/persistencia: contratos versionados, transacciones/idempotencia/migraciones, errores/concurrencia/recuperación, integración/observabilidad/auditoría/backups | `backend/app/main.py`; `backend/app/database/athena_database_v9.py`; repositorio del ciclo y `market_observation_repository.py`; `backend/app/services/database_backup_service.py` | `backend/tests/test_recommendation_professional_research_cycle_persistence.py`; `backend/tests/test_database_backup_service.py`; `.github/workflows/validate.yml` | En desarrollo; CORE-002, PRODUCT-004/015; JSON ARCH-API/ARCH-PERSIST/OPS-DEPLOY. Falta aceptación desplegada de concurrencia/recuperación, operación programada de backups, observabilidad y trazabilidad de todos los contratos. |
| T17 Seguridad/privacidad: secretos/autorización/cifrado/mínimo privilegio, dependencias/instrucciones externas, aislamiento investigación-ejecución, auditoría/incidentes | `backend/app/api/auth.py`; `backend/app/api/user_profile.py`; `backend/app/security/portfolio_owner_context.py`; `backend/app/services/deployment_security_readiness_service.py`; `docs/SECURITY_THREAT_MODEL.md`; `docs/INCIDENT_RESPONSE_OPERATIONS.md` | `backend/tests/test_auth_api.py`; `backend/tests/test_encrypted_user_profile_key_rotation.py`; `backend/tests/test_auth_password_recovery_lifecycle_e2e.py` | En desarrollo; PRODUCT-003/004; JSON SEC-BOUND/SEC-OPS/PROFILE-SMTP. Faltan custodia/rotación y recuperación reales, auditoría de dependencias/despliegue y validación de aislamiento del futuro motor de ejecución. |

## Ampliaciones históricas que siguen abiertas

Esta sección impide que los requisitos menos visibles desaparezcan al concentrar
el desarrollo en Market. No añade crédito ponderado a las filas anteriores.

| Alcance histórico | Referencias de aceptación MD | Cobertura/brecha de esta revisión |
| --- | --- | --- |
| Dossier único, screener, alertas explicables, calendario económico/corporativo | PRODUCT-017/018/019/021, PRODUCT-008 | `docs/XTREND_LITE_GAP_AUDIT.md` conserva criterios. Componentes Market/News/ciclo localizados; recorrido completo, configuración de alertas y calendario no aceptados. |
| Simulador de riesgo, laboratorio de estrategias, comparación con benchmarks y estrategias fallidas | PRODUCT-020/024, CORE-005/007/012 | Infraestructura shadow y cartera localizada; falta demostrar reglas precomprometidas de cada estrategia y simulador integrado con costes. |
| Analítica de cartera, peer comparator, heatmap/rotación sectorial, insiders oficiales | PRODUCT-022/023/025/026 | Atribución/riesgo/SEC localizados; comparador y heatmap dedicados pendientes de localizar/verificar. |
| Descomposición precio/dividendo/FX/costes y fiscalidad española verificada | PRODUCT-027 | `backend/app/services/dividend_total_return_service.py` y `portfolio_dividend_return_evidence_service.py` localizados. No acreditan asesoría fiscal, normas españolas actuales ni pantalla integral. |
| Contradicciones, expectativas, valoración inversa, escenarios asimétricos, catalizadores, invalidación, riesgo factorial y atribución | CORE-009/010, PRODUCT-028; JSON GAP-EXPECT/VAL-REVERSE/ASYM-SCEN/CAT-EVID/THESIS-INV/RISK-FACTOR/ATTR-PERF | Núcleo profesional con servicios/API; falta consolidar evidencia operativa por subcriterio, no aceptar todo el grupo por un único test. |
| Idiomas: español y futuros inglés/francés/portugués/italiano/alemán/ruso/otros; personalización cifrada | PRODUCT-003/010, JSON MULTILANG/PERS-ENCRYPT/PERS-OPS | Profile y cifrado localizados; traducción completa y aceptación por idioma/operación de claves pendientes. |
| Welcome, onboarding, comunidad/comparación de inversores, ML propio | PRODUCT-006/013, CORE-013; JSON COMMUNITY/ML-OWN | Preservados pese a tensiones con `docs/ATHENA_OS.md` ("no será una red social"). Falta descomponer alcance comunitario con consentimiento/moderación/privacidad; no inferir eliminación. |
| Windows portátil, Linux/servidor autorizado, offline, límites CPU/RAM, Ollama opcional | PRODUCT-014/015; JSON OPS-DEPLOY | Mantener despliegues históricos; falta medición operativa y recuperación en equipos autorizados. No contratar recursos automáticamente. |

## Brechas del propio inventario

1. `docs/ACCEPTANCE_INVENTORY.json` tiene 54 criterios y declara
   `scopeMappingReviewed.core=false` y `product=false`. Usa otro esquema de IDs
   (por ejemplo HIST-PIT, HIST-365, DATA-LICENSE). No se han reconciliado sus pesos
   y niveles con el MD; no pueden sumarse para obtener porcentaje.
2. `docs/ACCEPTANCE_EVIDENCE_REGISTER.md` reutiliza CORE/PRODUCT con otros
   significados: su CORE-001 es identidad; el CORE-001 del inventario MD exige
   historia legal/PIT. Toda evidencia debe calificarse por archivo además de ID
   hasta crear un crosswalk revisado; se conserva cada registro original.
3. `docs/DECISIONS.md` y `app/docs/ARCHITECTURE.md` están vacíos en la base
   inspeccionada. No se encontró backlog dedicado por nombre. No se interpretan
   como ausencia de decisiones: las secciones del plan horario, auditoría XTrend,
   documentación de aceptación y el contrato del propietario siguen conservando
   obligaciones. Falta reconstruir un historial completo verificable.
4. El registro `connected` de `docs/API_SOURCES.md` describe una integración, no
   licencia de uso/retención/redistribución ni disponibilidad PIT histórica.
5. Una búsqueda focalizada no demuestra ausencia absoluta: ejecución de órdenes,
   intradía/scalping, calendario/alertas/heatmap y traducciones requieren una
   auditoría específica antes de clasificarlos como no iniciados o implementados.
6. No hay horas de esfuerzo restantes ni velocidad efectiva suficiente en esta
   revisión para una previsión cuantificada fiable. Los hitos 30-11, 21-12 y
   31-12 siguen siendo objetivos, no compromisos garantizados. Medición pendiente.

## Fases y límites de activación

| Fase contractual | Evidencia requerida para su cierre | Estado de esta revisión |
| --- | --- | --- |
| 1 Investigación/desarrollo/pruebas sintéticas | Código, pruebas reproducibles, CI del SHA y límites no-order | Componentes y pruebas localizados; el informe de entrega debe acreditar ejecución. |
| 2 Validación histórica autorizada | Derechos de datos, PIT, ajustes, cobertura y pruebas reales | Bloqueada por evidencias de proveedor no acreditadas aquí. |
| 3 Simulación/paper | Reglas versionadas, órdenes simuladas, costes, reconciliación y kill switch | Infraestructura shadow no equivale por sí sola a cierre de esta fase. |
| 4 Demostración del bróker | Documentación oficial, permiso cuando corresponda, credenciales demo y contrato validado | Sin conexión ni autorización de pruebas de cuenta en esta revisión. |
| 5 Preparación técnica real deshabilitada | Adaptador real, pruebas autorizadas, controles deterministas independientes y auditoría de seguridad | Pendiente de localizar/verificar e implementar; debe quedar deshabilitada por defecto. |
| 6 Activación real | Autorización expresa separada, contrato/regulación, validación operativa y límites aprobados | No autorizada por el contrato maestro; alcanzar 100 % de código no la activa. |

Capital.com se evalúa primero conforme al contrato nuevo, usando documentación
oficial actual para API, residencia española, automatización, instrumento,
demo/autenticación/sesión, órdenes/posiciones, límites, costes y derechos de datos.
No se da por hecho que ofrezca acciones al contado adecuadas. Ningún CFD,
apalancamiento o derivado sustituye automáticamente acciones. Conservar IBKR y
su alcance paper histórico; si Capital.com es incompatible, registrar la razón y
plantear una alternativa aprobada sin cambiar unilateralmente el bróker final.

## Cola recuperable para las siguientes 24 horas

Cola preparada por dependencia y criterio observable; no certifica que haya un
ejecutor horario asociado ni promete completar estas tareas en una jornada.

| Prioridad | Dependencia / responsable | Archivos o capacidad a retomar | Cierre observable |
| --- | --- | --- | --- |
| 1 | HEAD/CI vigente; automatización | Market page, proveedor backend, modelo de histórico persistido y pruebas de widgets | Seleccionar instrumento/fuente/corte temporal muestra histórico persistido o estados carga/vacío/truncado/error; sin datos sintéticos en producción ni fallback oculto. |
| 2 | Proveedor; propietario/tercero para derechos | Twelve Data y evidencia PIT/almacenamiento | Términos/permiso documentados, calendario/identidad/volumen/ajustes y cobertura real >=365 días; hasta entonces continuar fixtures explícitos. Escalar antes del 30-11. |
| 3 | Fila 1 y contrato del ciclo; automatización | API `research-cycle`, persistencia y consumidores ATHENA/News | Prueba integrada de evidencia seleccionada -> ciclo idempotente recuperable, con errores y límites de procedencia. |
| 4 | Datos y sesiones; automatización | Contrato versionado de mínimo de las 25 sesiones previas | Pruebas sin look-ahead, separación de ventana/entrada/salida, costes/invalidación; sin declarar rentabilidad ni operación real. |
| 5 | Configuración del producto; propietario/plataforma si herramientas no exponen asociación | Única automatización horaria existente | Run programado identificable ejecuta pruebas y publica un commit funcional con SHA/CI; un commit manual Work no acredita esta vinculación. |
| 6 | Auditoría de fuentes y fases anteriores; automatización/propietario según gate | Crosswalk MD/JSON/registro; evaluación oficial Capital.com/IBKR; motor desacoplado | Requisitos atómicos sin duplicar pesos, evidencia por SHA, contratos de ejecución deshabilitados y bloqueos con responsable; no consumir credenciales reales. |

El siguiente checkpoint debe indicar HEAD inicial/final, archivos, comandos y
resultados reales de pruebas, CI push/PR por evento/SHA/URL, criterios afectados,
bloqueos, siguiente tarea y productividad observada. Las métricas 90 % de ciclos
útiles o 1–3 commits son objetivos condicionados, nunca resultados inferidos.

## Checkpoint de continuidad — separación sintética y puente de histórico

Actualización aditiva durante la continuación del 27-11-2026. No cambia pesos,
estados operativos ni requisitos históricos de las tablas anteriores.

- Base reanudada: `7c6bfae1ac2a2fa50d9c90f0193fbf48fe92db3b`. Su
  [CI push 45989546364](https://github.com/antoniomartinalbacetepresa-web/athena-platfotm/actions/runs/45989546364)
  pasó backend, Flutter, Chrome, build Web y release gate. API/Flutter distinguen
  `synthetic_fixture` de `unverified`, sin acreditar origen real por nombre.
- Puente publicado: `ab22ed9ff012208dbde03c0fd95bfc9dc0ecfeb0`; 71 pruebas
  focalizadas de ciclo/noticias/persistencia superadas. Su
  [CI push 46056042157](https://github.com/antoniomartinalbacetepresa-web/athena-platfotm/actions/runs/46056042157)
  estaba en curso al preparar este checkpoint: recuperar conclusión por SHA.
  Contrato y cola de 24 h: `market_history_research_bridge.md`.
- Contrato numérico Twelve Data: `twelve_data_numeric_contract.md`; 176 pruebas
  focalizadas superadas. Conserva la negativa PIT/almacenamiento del adaptador.
  Obtener el SHA de publicación y su CI desde el historial de la rama; este
  documento no certifica anticipadamente un commit o run posterior.
- IDs afectados: CORE-001/CORE-002/CORE-012 y PRODUCT-001 del inventario MD.
  Son incrementos de implementación/regresión con fixtures, no aceptación con
  datos reales. Permanecen abiertas licencia, cobertura, OOS y operación.
- Siguiente lote: validar los SHA publicados, añadir transporte/revisión Flutter
  autenticada para el puente con corte estable y contexto humano, y continuar
  unión de referencias Market/News/Investors. Preparar después la hipótesis de
  rebote de 25 sesiones; conservar el motor de ejecución deshabilitado.

Las fuentes reales requieren derechos acreditados. La automatización horaria no
se modifica ni duplica y su asociación a Work no se deduce de estos commits.

### Continuación de integración Flutter — 27/11/2026

El puente `ab22ed9ff012208dbde03c0fd95bfc9dc0ecfeb0` ya tiene CI push
46056042157 **success**, comprobada por SHA. El contrato numérico se publicó en
`1c1fd67d4cc782947a48e8faffa627559b8e6cab` (CI 46056342692 pendiente al
preparar esta ampliación).

Se corrige un desajuste real: el lector Flutter de detalle privado esperaba
`package.symbol/asOf`, mientras FastAPI entrega `package.cycle.symbol/asOf`.
Se valida también `cycle.integrity.algorithm/cycleHash` frente a la selección
privada; campos planos no sustituyen al ciclo canónico. Se actualizan fixtures y
se añaden regresiones de paquete plano, ciclo ausente/tipo inválido, símbolo,
hash y algoritmo contradictorios. Servicio y panel privados se incluyen en la
aceptación Chrome obligatoria. Esto no ejecuta modelos ni acredita datos reales.

El SDK local puede analizar sintaxis mediante Dart format, pero su caché de
paquetes está incompleta: las pruebas Flutter de este lote deben verificarse en
Actions antes de considerarlo probado. Recuperar SHA y conclusión desde la rama.
La siguiente tarea sigue siendo la creación autenticada del puente desde Flutter,
con revisión humana y corte estable; después referencias News/Investors y la
estrategia reproducible de 25 sesiones. No se cambia la programación horaria.
