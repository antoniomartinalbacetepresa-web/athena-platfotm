# DATA MODEL

Versión 0.2

ATHENA utiliza un modelo de datos orientado a entidades, evidencia y tiempo de disponibilidad. El modelo evita tratar un ticker como si fuera una empresa: un mismo emisor puede tener varias clases, ADR, listados secundarios o símbolos distintos según el mercado.

## Identidad de emisor

`canonical_issuers` representa a la entidad económica emisora. Sus atributos de identidad no deben inferirse a partir del mercado donde cotiza un instrumento.

Campos conceptuales principales:

- identificador canónico de emisor;
- nombre canónico;
- identificadores externos verificables;
- país de domicilio del emisor (`domicile_country`);
- región derivada del domicilio (`region_key`);
- fuente, método y confianza de resolución.

El domicilio del emisor y el país de cotización son dimensiones distintas. Un ADR estadounidense de una empresa domiciliada en Asia no convierte el domicilio del emisor en Estados Unidos.

## Instrumento y listado

`instruments` representa un valor negociable/listado concreto.

Campos conceptuales principales:

- símbolo/ticker;
- bolsa y mercado;
- país de cotización (`country`);
- tipo de instrumento;
- moneda;
- estado activo/inactivo;
- indicador explícito de listado primario cuando exista evidencia;
- capitalización observada para ese listado;
- metadatos de proveedor.

`instrument_issuer_links` enlaza instrumentos con emisores canónicos y conserva la evidencia de resolución. La deduplicación para capitalización y ponderación se realiza por emisor, no por ticker.

## Selección de listado canónico

La selección es conservadora:

1. Se buscan listados cuyo país de cotización coincida, tras normalización de alias, con el domicilio del emisor.
2. Si existe exactamente un listado doméstico marcado explícitamente como primario, se selecciona.
3. Si existe exactamente un único listado doméstico, se selecciona.
4. Si existen varias clases/listados domésticos sin una única evidencia de primariedad, el emisor queda ambiguo.
5. Si no existe listado doméstico, no se elige arbitrariamente un listado extranjero.

Los casos ambiguos y los emisores sin listado doméstico son bloqueos de readiness para ponderación regional. No se resuelven eligiendo el ticker de mayor capitalización o el primero de una lista.

## Capitalización canónica y pesos regionales

Para un emisor con listado doméstico canónico inequívoco, ATHENA utiliza la capitalización de ese listado como estimación canónica del emisor. Si todavía no existe selección inequívoca, la mediana entre capitalizaciones enlazadas puede conservarse únicamente como diagnóstico; no constituye evidencia suficiente para activar ponderaciones.

Los ETF y fondos conocidos se excluyen del cálculo de capitalización de emisores. La capitalización regional se atribuye por domicilio del emisor, nunca por país de cotización. Emisores con domicilio no resuelto no se reasignan silenciosamente a la región del mercado donde cotizan.

La capa de diagnóstico registra además discrepancias entre capitalizaciones de listados asociados al mismo emisor mediante ratios máximo/mínimo. Estos ratios sirven para investigar calidad de datos, clases, ADR y posibles errores; no son por sí mismos una regla de producción.

`isWeightingReady` debe permanecer desactivado hasta que se satisfagan simultáneamente los gates definidos por el servicio de readiness y exista validación externa independiente con una referencia de evidencia no vacía.

## Procedencia de datos

Los datos normalizados conservan `DataProvenance` con dimensiones temporales diferentes:

- `effective_at`: periodo o instante económico al que se refiere el dato;
- `published_at`: instante/fecha de publicación declarada por la fuente, cuando existe;
- `source_timestamp`: timestamp proporcionado por la fuente;
- `retrieved_at`: instante en que ATHENA recuperó el dato;
- `available_at`: instante explícito a partir del cual el dato podía ser conocido por el sistema para un análisis point-in-time;
- `version`, identificadores raw/normalizados y URL de fuente.

Estas fechas no son intercambiables. En particular, `effective_at` no demuestra disponibilidad y `retrieved_at` no debe usarse para simular cuándo el mercado podía conocer información histórica.

## Política point-in-time y backtesting

Los motores históricos y de backtesting deben filtrar información por `available_at <= as_of`. Si `available_at` no existe, el dato se considera no disponible para ese corte temporal. ATHENA no infiere silenciosamente `available_at` a partir de otras fechas.

Cada adaptador de fuente debe definir y probar su política de disponibilidad antes de que sus datos se utilicen en un backtest. Cuando una fuente sólo expone una fecha sin hora y no existe evidencia suficiente sobre la hora real de disponibilidad, no se fabricará precisión temporal.

## Comparabilidad y confianza

La comparación de observaciones entre fuentes requiere como mínimo el mismo:

- `metric`;
- tipo de dato (`data_kind`);
- `entity_id`;
- unidad;
- moneda;
- `effective_at`.

Dos observaciones de la misma fuente no cuentan como corroboración independiente. La puntuación de confianza debe reflejar calidad y acuerdo entre fuentes comparables, no volumen de filas duplicadas.

## Métricas de empresa

Sobre la identidad canónica y sus instrumentos pueden construirse métricas como:

- sector e industria;
- capitalización;
- precio y rangos históricos;
- dividendos y payout;
- beta y riesgo;
- PER, PEG y múltiplos;
- ROE, ROIC y ROA;
- deuda y caja;
- flujo de caja;
- crecimiento;
- márgenes;
- métricas técnicas, fundamentales y de valoración.

El catálogo puede superar las 200 métricas, pero cada una debe conservar entidad, unidad, periodo, procedencia, calidad y disponibilidad temporal suficientes para su uso previsto.

## Capas derivadas

Cada emisor podrá incorporar, de forma trazable:

- ATHENA Score;
- ATHENA Confidence;
- ATHENA DNA;
- ATHENA Timeline;
- resumen explicable;
- noticias;
- competidores;
- riesgos;
- catalizadores.

Las estimaciones y recomendaciones deben diferenciar hechos, cálculos y estimaciones, y no presentar como certeza información que dependa de supuestos o datos incompletos.
