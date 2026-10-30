# SEC 13F — comparación de coincidencias entre inversores (solo informativa)

La pantalla Investors puede comparar de **2 a 5 CIK distintos** tras completar
con éxito las consultas reales SEC EDGAR. Se comparan únicamente formularios
originales `13F-HR` del **mismo día de posición**. Si hay fechas diferentes,
enmiendas `13F-HR/A`, fuentes no verificadas o identidades duplicadas, el
resultado es **no comparable**; no se reutiliza una comparación anterior.

El cálculo usa la coincidencia **exacta del CUSIP tal como lo declara SEC**,
una vez por CIK. Solo entran filas `SH` sin `PUT`/`CALL` y CUSIP de nueve
caracteres alfanuméricos; se excluyen `PRN` y marcadores `*`, `@`, `#`.
No se asignan tickers ni identidades canónicas, no se suman importes ni se
infieren pesos o exposición económica. El detalle permite revisar **todas**
las coincidencias, ordenadas por número de declarantes y CUSIP.

Una coincidencia de CUSIP es evidencia histórica de **filas declaradas**,
no de tenencia actual, valor de cartera completo, consenso inversor ni
identidad canónica. SEC 13F no cubre todas las posiciones y puede contener
enmiendas o diferencias temporales. La función es de solo lectura,
`no_advice`, sin scoring, recomendación, aprendizaje, ponderación ni órdenes.

Aceptación de código: regresiones de fechas incompatibles, enmiendas,
identidades repetidas, opciones, PRN, marcadores ambiguos, deduplicación
por CIK, ordenación y acceso UI al detalle. La aceptación desplegada HTTPS
y la autenticidad operativa de cada filing siguen pendientes y no se
sustituyen por fixtures ni por CI verde.
