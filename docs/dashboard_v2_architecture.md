# ATHENA Dashboard V2
## Centro de Mando del Inversor

---

# Filosofía

El Dashboard no es una pantalla de bienvenida.

Es el lugar desde donde el usuario controla toda su estrategia de inversión.

Debe responder, en menos de 10 segundos, a estas preguntas:

- ¿Cómo va mi patrimonio?
- ¿Cuánto dinero tengo disponible?
- ¿Qué está haciendo mi cartera?
- ¿Qué oportunidades ha encontrado ATHENA?
- ¿Qué riesgos debo conocer hoy?
- ¿Qué debería hacer ahora?

---

# Arquitectura general

┌───────────────────────────────────────────────────────────┐
│ Header                                                    │
├───────────────┬───────────────────────────────────────────┤
│               │                                           │
│ Mi Espacio    │ Centro de Inteligencia ATHENA             │
│ (Fijo)        │ (Scroll)                                  │
│               │                                           │
├───────────────┴───────────────────────────────────────────┤
│ Footer (opcional)                                         │
└───────────────────────────────────────────────────────────┘

---

# HEADER

Siempre visible.

Contiene:

- Logo ATHENA
- Fecha
- Estado del mercado
- Notificaciones
- Configuración
- Perfil usuario

Altura aproximada:

70-80 px

---

# MI ESPACIO (Panel fijo)

Información personal del usuario.

Siempre visible.

No hace scroll.

Contendrá:

## Mi patrimonio

Valor actual

Rentabilidad diaria

Rentabilidad total

Rentabilidad anual

---

## Liquidez

Dinero disponible

Dinero invertido

Capital comprometido

---

## Diversificación

Distribución por sectores

Distribución por países

Distribución por divisas

---

## Riesgo

Nivel de riesgo

Volatilidad

Drawdown

---

## Objetivos

Objetivo financiero

Fecha prevista

Progreso

---

## Alertas

Dividendos

Resultados

Cambios importantes

Rebalanceos

---

# CENTRO DE INTELIGENCIA ATHENA

Zona con scroll.

Contiene toda la información generada por ATHENA.

Orden de aparición:

1. Mensaje Inteligente

2. Mejores oportunidades de compra

3. Mejores oportunidades de venta

4. Seguimiento de la cartera

5. Noticias relevantes

6. Calendario económico

7. Dividendos

8. Cambios de analistas

9. Información adicional

---

# Tarjeta de oportunidad

Cada empresa mostrará:

Nombre

Ticker

ATHENA Score

Barra visual

Precio actual

Variación

Nivel de riesgo

Explicación IA

Botón:

¿Por qué ATHENA recomienda esta inversión?

---

# Mensaje Inteligente

Debe ser dinámico.

Ejemplos:

Hoy ATHENA ha encontrado tres oportunidades superiores al 90%.

Tu cartera supera hoy al S&P500.

Tu exposición al sector tecnológico es elevada.

Sería recomendable aumentar el peso del sector salud.

---

# Filosofía

ATHENA no muestra datos.

ATHENA ayuda a tomar decisiones.

Cada recomendación debe explicar:

Qué ocurre.

Cómo afecta al usuario.

Qué recomienda ATHENA.

Por qué.