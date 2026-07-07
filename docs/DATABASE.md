# ATHENA TYCHE

# Base de Datos

Versión 1.0

---

# Objetivo

La base de datos almacenará toda la información necesaria para que ATHENA TYCHE pueda analizar inversiones, aprender continuamente y ayudar al usuario a tomar mejores decisiones.

---

# Tabla USERS

Información de cada usuario.

Campos:

- id
- nombre
- email
- password_hash
- país
- idioma
- fecha_registro
- último_login
- nivel_inversor
- perfil_riesgo
- objetivo_inversión
- premium

---

# Tabla PORTFOLIOS

Cada usuario podrá tener varias carteras.

Ejemplos:

- Principal
- Dividendos
- Largo plazo
- Tecnología

Campos:

- id
- user_id
- nombre
- descripción
- moneda
- fecha_creación

---

# Tabla POSITIONS

Acciones que posee el usuario.

Campos:

- id
- portfolio_id
- ticker
- empresa
- cantidad
- precio_medio
- fecha_última_compra

---

# Tabla TRANSACTIONS

Historial completo.

Tipos:

- Compra
- Venta
- Dividendo
- Aportación
- Retirada
- Comisión

Campos:

- id
- portfolio_id
- ticker
- tipo
- cantidad
- precio
- fecha

---

# Tabla STOCKS

Información de cada empresa.

Campos:

- ticker
- nombre
- sector
- industria
- país
- bolsa

---

# Tabla ATHENA_SCORE

Puntuación actual.

Campos:

- ticker
- score
- confianza
- recomendación
- última_actualización

---

# Tabla ATHENA_SCORE_HISTORY

Histórico del ATHENA Score.

Campos:

- id
- ticker
- score
- fecha

---

# Tabla NEWS

Noticias importantes.

Campos:

- id
- ticker
- titular
- resumen
- sentimiento
- fecha

---

# Tabla AI_RECOMMENDATIONS

Historial de recomendaciones.

Campos:

- id
- ticker
- score
- explicación
- confianza
- fecha
- resultado_30d
- resultado_90d

---

# Tabla USER_DECISIONS

Registro de decisiones del usuario.

Campos:

- id
- user_id
- ticker
- acción
- motivo
- seguía_recomendación
- fecha

---

# Filosofía

Nunca se eliminará información histórica.

Toda la información ayudará al motor ATHENA a aprender continuamente y mejorar la calidad de sus análisis.
