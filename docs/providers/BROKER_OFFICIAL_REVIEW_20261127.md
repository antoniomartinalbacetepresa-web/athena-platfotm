# Evaluación oficial de interfaces de bróker — 27-11-2026

Revisión documental aditiva para el contrato maestro de ATHENA TYCHE.
Capital.com conserva prioridad de evaluación; IBKR conserva su alcance histórico.
No sustituye `CAPITAL_COM_EVALUATION.md`, no designa un bróker definitivo y no
autoriza cuentas, credenciales, datos, contratación ni órdenes. Todas las fases
de ejecución permanecen deshabilitadas. Referencias de alcance: PRODUCT-005/016
en `docs/ACCEPTANCE_INVENTORY.md`; no cambia aceptación ni porcentaje.

## Hechos, límites e incertidumbres

Las fuentes siguientes se abrieron el 27-11-2026. La documentación pública no
acredita los permisos, entidad contractual, producto o tarifas aplicables a una
cuenta particular. No se han enviado solicitudes a los endpoints de los brókeres.

| Requisito | Capital.com | IBKR | Consecuencia para ATHENA |
| --- | --- | --- | --- |
| API e instrumentos | La ayuda española del 08-10 menciona CFD/apuestas UK [S2]; la inglesa del 23-11 añade **acciones reales en la UE** [S11]. Existe una discrepancia de traducción/actualización. | Tiene Web API y TWS API utilizables con cuentas paper [S7]. Publica tarifas de negociación de acciones [S9]. La identidad y permiso de cada contrato deben verificarse. | No concluir CFD-only ni disponibilidad de acciones para España a partir de una sola versión. Conservar tipo, proveedor, ID nativo, mercado, moneda y semántica del precio. |
| España y entidad | El portal europeo identifica entidades chipriotas reguladas y restricciones de distribución [S3]. Esta revisión no confirma alta, entidad asignada ni habilitación API para este propietario residente en España. | España aparece en la lista oficial de países disponibles [S5]; no garantiza aprobación individual, productos ni permiso de automatización. | La residencia y el contrato del cliente son gates separados de la existencia técnica de una API. |
| Demo y autenticación | URL demo separada; 2FA/API key, `POST /session`, sesión de 10 minutos y tokens `CST`/`X-SECURITY-TOKEN` [S1]. | El flujo Web individual documenta cuenta Pro abierta/financiada y configuración según método [S6]; los FAQ también permiten pruebas Free Trial o cuentas de test [S12/S13]. TWS trial tiene restricciones de datos [S12]. | No generalizar requisitos de un flujo a todas las API/demo ni asumir acceso anónimo o sesiones cloud indefinidas. No abrir ni financiar cuentas automáticamente. |
| Sesiones y pacing | Documenta máximo 10 solicitudes/s/usuario, `POST /session` 1/s/API key, hasta 40 instrumentos WebSocket y 1000 creaciones de posiciones/órdenes por hora en demo [S1]. | Web API: límite global de 10 solicitudes/s por usuario autenticado, límites adicionales por endpoint y respuesta 429 al excederlos [S6]. | Adaptador con presupuesto por endpoint, backoff acotado y bloqueo; nunca reintentar una mutación a ciegas. Estos límites no son equivalentes al TWS API. |
| Posiciones, órdenes e historial | Documenta posiciones/órdenes y confirmación por referencia. Advierte limitación de stop-loss/take-profit en acciones reales y ausencia de API keys read-only [S1]. | La documentación Trading describe gestión de operaciones, cartera y datos. Un usuario solo puede mantener una sesión de brokerage activa entre plataformas [S10]. | Contratos desacoplados para propuesta, validación, envío y conciliación. Verificar protección de salidas por producto y aislar credenciales con autoridad de trading. |
| Costes | La página internacional consultada presenta spread dinámico, financiación condicional, conversión FX y prima de stop garantizado; comisión de trading indicada como cero [S4]. La localización observada es internacional/México: no certifica tarifas españolas. | El FAQ indica uso API sin tarifa para clientes Pro abiertos/financiados, con posibles diferencias de comisión en órdenes API [S7]. La tarifa de acciones depende de mercado/routing y mínimos [S9]. | No etiquetar una integración como gratuita por carecer de tarifa API. Costes de cuenta, datos, órdenes, FX y financiación deben presupuestarse por separado y confirmarse para la entidad. |
| Datos y derechos | REST/streaming e históricos documentados [S1] no acreditan retención, caché, redistribución, PIT ni datos oficiales de bolsa para acciones al contado. | Las licencias API/off-platform varían por proveedor/suscripción; puede requerirse suscripción adicional o no estar permitido un feed [S8]. | Ninguna fuente de esta revisión permite declarar derechos de almacenamiento/redistribución ni cobertura OHLCV/PIT aceptados. |

## Decisión técnica provisional

**Compatibilidad Capital.com: NO VERIFICADA para acciones reales de este usuario
en España.** La página inglesa más reciente afirma soporte de acciones reales
en la UE y la API contiene una nota específica sobre sus órdenes; la versión
española anterior tiene un alcance más estrecho. No es correcto descartar
Capital.com como exclusivamente CFD ni dar por habilitadas acciones para toda
cuenta UE. Resolver producto, entidad, elegibilidad española, API y derechos
antes de elegir. Ni un CFD 1:1 ni un precio derivado equivalen a una acción real.

IBKR permanece como alternativa histórica a evaluar para acciones y paper; esta
revisión no lo activa ni cambia unilateralmente la plataforma elegida. Hay una
dependencia operativa importante: distinguir el flujo Web individual, paper
asociado, Free Trial y cuentas de test. Los FAQ de pruebas no acreditan datos
gratuitos ni un entorno cloud anónimo y siempre conectado.
No trasladar condiciones de Web API a TWS ni de una entidad/región a otra.

## Trabajo de ingeniería autorizado que puede continuar

1. Definir un contrato neutral de ejecución con identificadores de instrumento
   tipados y modo explícito `synthetic`, `paper`, `demo` o `live_disabled`.
   La capacidad real debe seguir separada de su activación.
2. Probar localmente mediante transportes sintéticos: expiración de sesión,
   429/timeout, confirmación pendiente, doble envío, desconexión, reinicio y
   conciliación. Simular compras/ventas no demuestra aceptación de un bróker.
3. Exigir controles deterministas independientes antes de todo envío: límites
   aprobados, antigüedad/precio, moneda/producto, exposición, frecuencia,
   idempotencia y kill switch. El modelo no recibe autoridad de envío.
4. Mantener los adaptadores sin conexión por defecto. La primera validación de
   cuenta demo/paper requerirá permisos y términos aplicables. Producción exige
   autorización separada, contrato/regulación, límites monetarios y evidencia
   operativa; no la habilita completar código.

## Evidencia pendiente y responsable

| Gate | Evidencia pendiente | Responsable |
| --- | --- | --- |
| Capital.com / acciones al contado | Resolver versiones ES/EN y acreditar entidad/cuenta/producto/API para España; la mención UE no basta para este usuario | Proveedor; evaluación técnica por automatización |
| Elegibilidad de cuenta | Entidad contractual, residencia, permisos y condiciones de uso automatizado específicos | Propietario/proveedor, sin secretos por chat |
| Datos | Uso, almacenamiento/caché, derivados, visualización/redistribución, timestamp/PIT y ajustes por instrumento | Proveedor/bolsa; revisión antes de persistir datos reales |
| Costes | Tarifa vigente por entidad/producto/routing, FX, datos y mantenimiento de posiciones | Proveedor/propietario antes de contratar |
| Operación | Contrato de adaptador, pruebas sintéticas, demo autorizada, errores/conciliación y riesgos | Automatización, con gates de activación independientes |

## Fuentes oficiales abiertas

- **S1:** [Capital.com Public API](https://open-api.capital.com/). General information, Authentication, FAQ, positions/orders y Important Notice. Las referencias REST/demo son documentación; no se han usado para conectarse.
- **S2:** [Capital.com: instrumentos compatibles con la API](https://help.capital.com/hc/es/articles/4415165718290--La-API-es-compatible-con-todos-los-instrumentos). Actualización indicada: 08-10-2026.
- **S3:** [Capital.com EU: terms and policies](https://capital.com/en-eu/terms-and-policies). La licencia de una entidad no demuestra aprobación del usuario ni cubre automáticamente el uso propuesto.
- **S4:** [Capital.com: cargos y tarifas, versión internacional](https://capital.com/es-int/ways-to-trade/fees-and-charges). No se certifican tasas españolas a partir de esta página.
- **S5:** [IBKR: países y territorios disponibles](https://portal.interactivebrokers.com/en/accounts/open-account-country-list.php). España figura en la lista.
- **S6:** [IBKR Web API Documentation](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/). Secciones de acceso individual, autenticación y pacing. El acceso de terceros requiere revisión adicional.
- **S7:** [IBKR: API con cuenta paper](https://www.interactivebrokers.com/support/faq/content/use-ibkrs-apis-paper-account-629299048). Incluye enlaces y aclaraciones sobre uso API/tarifas para Pro.
- **S8:** [IBKR: disponibilidad de datos de mercado por API](https://www.interactivebrokers.com/support/faq/content/live-market-data-available-via-629299474). Distingue suscripciones y licencias off-platform.
- **S9:** [IBKR: comisiones sobre acciones](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php). Consultar mercado y routing concretos; no confundir mercado español con residencia del cliente.
- **S10:** [IBKR Trading Web API](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/). Sesiones, posiciones/cartera, datos y superficie Trading.
- **S11:** [Capital.com: instrumentos API, versión inglesa](https://help.capital.com/hc/en-us/articles/4415165718290-Does-your-API-support-all-the-instruments). Actualización indicada: 23-11-2026; añade acciones reales en la UE frente a S2.
- **S12:** [IBKR: TWS API con Free Trial](https://www.interactivebrokers.com/support/faq/content/use-tws-api-free-trial-29082409). Permite conexión trial, limita datos sujetos a suscripción y diferencia TWS de IB Gateway.
- **S13:** [IBKR: probar API antes de abrir/financiar cuenta](https://www.interactivebrokers.com/support/faq/content/test-ibkrs-apis-before-account-629299073). Admite Free Trial y estructuras de test; confirmar alcance para el flujo elegido.

Limitaciones de la revisión: no es una auditoría contractual/regulatoria completa;
no se abrió ni aceptó contrato, no se accedió a cuentas y no se verificó ejecución
real/demo/paper. No convierte las capacidades documentadas por el proveedor en
funcionalidades implementadas o aceptadas de ATHENA.
