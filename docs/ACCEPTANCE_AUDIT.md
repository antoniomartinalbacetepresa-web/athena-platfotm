# ATHENA TYCHE — inventario de aceptación y auditoría cuantitativa

Inicio: 2026-11-02. Fuente: `docs/MASTER_PROJECT.md` (alcance completo, incluidas fases futuras) y `docs/ROADMAP.md` (estimaciones históricas del 2026-09-24). Este inventario es **una línea base incompleta**, no una certificación del 91 % ni del 85 %.

Ejecutar desde `backend`: `python -m scripts.acceptance_progress`. Validación: `python -m pytest tests/test_acceptance_progress.py -q`.

## Criterios y fórmula

`docs/ACCEPTANCE_INVENTORY.json` registra IDs estables, módulo, alcance, peso de 1 a 5 con justificación, aceptación observable, dependencias, nivel requerido, estado, evidencia con SHA exacto, revisión y bloqueos. Cada criterio se cuenta **una sola vez por alcance**; el producto incluye también los criterios del núcleo, sin sumarlos dos veces. Las áreas futuras (alertas, idiomas, comunidad, ML) **no se eliminan** para acelerar.

Para cada alcance, cuando la correspondencia con el plan esté revisada y **todos** sus criterios tengan `reviewed=true`, el porcentaje de ingeniería se calcula como:

`100 * sum(weight * min(level(status)/level(requiredLevel), 1)) / sum(weight)`

Niveles: `pending=blocked=0`, `implemented_ci=1`, `real_data=2`, `deployed=3`. Un criterio que solo necesita CI puede completarse con CI; uno que exige despliegue no puede recibir 100 % por una prueba sintética. El peso refleja dependencia/impacto, **no** líneas de código, commits ni número de tests. Para aprobar el 100 % también deben estar todos los criterios en su nivel requerido y **todos los gates obligatorios verificados**.

Si falta revisión del mapeo o de un criterio, `percent=null` y el informe dice **porcentaje actual no certificable**. La cobertura se muestra como criterios revisados/total. No se publica una cifra parcial como si fuera progreso global.

## Procedimiento por ejecución

1. Leer HEAD y CI push/PR del SHA exacto. Revisar la aceptación funcional prioritaria (Market → News → ATHENA), más una dependencia del alcance completo.
2. Añadir o actualizar un criterio solo tras cotejar su aceptación con código, prueba y, cuando corresponda, datos auténticos y despliegue. Registrar SHA/enlace y marcar `reviewed=true` solo tras revisión humana/técnica documentada. Un test sintético solo puede justificar `implemented_ci`.
3. Mantener `scopeMappingReviewed=false` hasta confirmar que el inventario abarca **todo** MASTER_PROJECT y ROADMAP; no basta con contar las 13 áreas del roadmap. Revisar duplicidades, pesos y dependencias. Registrar antes/después/delta únicamente si ambos porcentajes son certificables.
4. No inferir licencia de mercado, cobertura real 365 días, verificación PIT histórica, precisión predictiva, seguridad de producción ni Ollama local de la CI. Los gates de despliegue, OOS prospectivo, seguridad operativa, acciones corporativas y protección de rama siguen pendientes.

**Limitación actual:** las referencias de CI de la línea base acreditan ejecución de tests del SHA de referencia, no una auditoría detallada de cada aceptación. Por ello los criterios siguen `reviewed=false` aunque se haya identificado código y tests. El primer trabajo de las siguientes horas es revisar y cerrar los criterios de la ruta vertical real, sin sacrificar desarrollo funcional.
