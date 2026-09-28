# 065 — Texto completo de las transcripciones reales del recado 064

**Fecha**: 2026-09-10
**Propósito**: el usuario pidió ver el texto EXACTO y completo de las 4 llamadas reales del recado 064 (3 ya reportadas + la nueva de 2 preguntas fuera de contexto) — al pegarlas directamente en el chat llegaron cortadas. Este archivo existe para que el texto completo quede en un lugar estable y revisable, sin cortes, mismo criterio que el recado 028 con la tabla del recado 027.

Todas las llamadas usan datos sintéticos de prueba (`FakeHttpClient`/`MockAppointmentService`, nunca red real contra hrmm-backend, nunca un paciente real) — solo la llamada a la API de Anthropic es real en las 4.

---

## 1. Wizard de código de verificación (cancelar/reprogramar) — "mejor no" reconocido como salir

```
Paciente: quiero cancelar mi cita

Sistema: Buenas noches. Soy Andrés, tu asistente virtual para la gestión de tus citas
médicas del Hospital Regional del Magdalena Medio. ¿Qué deseas hacer?
1. Reservar una cita
2. Reprogramar una cita
3. Cancelar una cita
4. Consultar mis citas
5. Salir / terminar Listo, te enviamos un código a tu correo (a***@dominio.com) para
confirmar. Escríbelo aquí para continuar cuando lo tengas.

Paciente: oye disculpa, se me hizo tarde y ya ni sé si quiero seguir con esto, mejor no

Sistema: De acuerdo, no seguimos con esto por ahora. ¿En qué más te ayudo?
1. Reservar una cita
2. Reprogramar una cita
3. Cancelar una cita
4. Consultar mis citas
5. Salir / terminar
```

Nota: el primer mensaje del sistema concatena el saludo institucional + el inicio real del wizard en una sola línea con un espacio (sin salto de línea entre "5. Salir / terminar" y "Listo, te enviamos...") — es el comportamiento REAL de `handle_inbound_message` (`f"{saludo_apertura} {respuesta}"`), no un artefacto de esta captura.

---

## 2. Wizard de identidad de canal — "¿a qué correo me mandaron eso?"

```
Paciente: hola

Paciente: 123456789

Paciente: perdón, ¿a qué dirección de correo me mandaron eso?

Sistema: Te enviamos el código a tu correo (a***@dominio.com). Cuando lo tengas,
escríbelo aquí para continuar.
```

---

## 3. Fallback de menú general (sin conversación abierta) — "qué tengo agendado"

```
Paciente: hola

Paciente: oye cuentame que tengo agendado por ahi

Sistema: Aquí tienes tu 1 cita activa:
1. medicina general — Jueves 10 de septiembre, 09:00, Consultorio 3
```

---

## 4. Dos preguntas fuera de contexto en la MISMA conversación, en medio de un flujo de selección de fecha/horario — transcripción completa de 5 turnos

```
Turno 1
Paciente: sí

Sistema: Estas son las fechas que tenemos disponibles:
1. Sábado 5 de septiembre
2. Domingo 6 de septiembre
3. Lunes 7 de septiembre
¿Cuál te queda mejor?

--------------------------------------------------------------------------------
Turno 2 — interrupción 1: pregunta de ubicación del hospital
Paciente: oye, y ¿dónde queda el hospital exactamente?

Sistema: Buena pregunta, pero no tengo la dirección exacta registrada por este medio —
te recomiendo llamar directamente al hospital para confirmarla.

Retomando lo de antes, ¿cuál de las fechas que te compartí te queda mejor?

--------------------------------------------------------------------------------
Turno 3 — interrupción 2 (DISTINTA, más adelante en la misma conversación):
pregunta sobre calidad de atención
Paciente: otra cosa, ¿los médicos de ahí son buenos atendiendo?

Sistema: Es una pregunta válida, pero no tengo información objetiva para darte una
opinión sobre eso. Lo que sí puedo hacer con gusto es ayudarte a agendar tu atención
cuando quieras.

Volviendo a lo de antes, ¿cuál de las fechas que te compartí te queda mejor?

--------------------------------------------------------------------------------
Turno 4 — el paciente retoma la selección EXACTAMENTE donde iba, sin repetir nada
Paciente: 1

Sistema: Para el sábado 5 de septiembre tengo estos horarios disponibles en Sede Norte:
1. 09:00
2. 10:00
¿Cuál prefieres?

--------------------------------------------------------------------------------
Turno 5 — la reserva se completa con total normalidad
Paciente: 1

Sistema: ¡Genial, Paciente Ficticio! Dame un momento mientras te dejo la reserva lista.
¡Listo! Quedó confirmado: medicina general el 2026-09-05 a las 09:00 en Sede Norte.
```

**Verificación adicional, no solo por el texto**: tras el turno 2 y tras el turno 3, se consultó `ConversationState.datos_recopilados` directamente (no se infirió del texto) — `etapa` seguía siendo `"esperando_fecha"` y `fechas_ofrecidas` no había cambiado en ningún momento, en ambos casos. El estado de la selección nunca se perdió.

**Guardrails durante estos 3 turnos** (leído directamente del `EventLog` real de esta conversación): los 9 guardrails de Core evaluaron `ALLOW` en los 3 turnos, sin ninguna excepción — incluido `tipo_de_pregunta_alterada -> "tipo de pregunta preservado"` y `opinion_personal -> "sin opinión personal detectada"`. Ningún guardrail necesitó intervenir.
