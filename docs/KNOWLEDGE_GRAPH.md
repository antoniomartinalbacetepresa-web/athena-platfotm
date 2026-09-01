# ATHENA KNOWLEDGE GRAPH

Versión 0.1

---

# Objetivo

El Knowledge Graph es el modelo de conocimiento de ATHENA.

No almacena únicamente datos.

Describe cómo se relacionan todas las entidades del sistema.

Gracias a este modelo ATHENA podrá razonar sobre el mercado y no limitarse a mostrar información.

---

# Entidades principales

Actualmente ATHENA reconoce las siguientes entidades:

- Empresa
- Sector
- Industria
- País
- Mercado
- Índice
- ETF
- Fondo
- Divisa
- Materia Prima
- Criptomoneda
- Banco Central
- Indicador Macroeconómico
- Noticia
- Resultado Empresarial
- Directivo
- Institución
- Usuario
- Cartera
- Alerta

---

# Relaciones

Las entidades pueden relacionarse entre sí.

Ejemplos:

Empresa
    pertenece a
Sector

Sector
    pertenece a
Industria

Empresa
    cotiza en
Mercado

Empresa
    pertenece a
Índice

Empresa
    compite con
Empresa

Empresa
    depende de
Materia Prima

Empresa
    obtiene ingresos en
País

Empresa
    está afectada por
Banco Central

Empresa
    publica
Resultados

Empresa
    aparece en
Noticias

Usuario
    posee
Empresa

Usuario
    sigue
Empresa

Usuario
    recibe
Alertas

---

# Filosofía

Cada nueva funcionalidad deberá integrarse dentro de este grafo.

No se crearán módulos aislados.

Todo debe estar conectado.
