# 028 — Tabla completa antes/después del cambio de tono (recado 027)

**Fecha**: 2026-09-06
**Continúa**: recado 027 (catálogo de servicios + pase de tono conversacional)
**Propósito**: el usuario pidió ver el texto COMPLETO de las 8 filas de la tabla de antes/después del recado 027 — al pegarlas directamente en el chat, las filas 4 a 8 llegaron cortadas a mitad de frase. Este archivo existe para que la tabla completa quede en un lugar estable y revisable, con el texto verificado línea por línea contra el código real (`domains/health/brain.py`, `domains/health/gateway.py`) en el momento de escribir esto — no transcrito de memoria.

## Tabla completa (8 filas)

| # | Contexto | Archivo / función | Antes | Después |
|---|---|---|---|---|
| 1 | Fallback de sí/no — se repetía literal turno tras turno en la conversación real | `brain.py`, fallback final de `_interpretar_decision` | ¿Te gustaría que te ayude a programar tu atención? Puedes responder sí o no. | ¿Te ayudo a agendar tu atención? Con que me digas sí o no, ya sé cómo seguir. |
| 2 | Sin disponibilidad (recado 026 ya le había quitado la frase prohibida "te contactamos"; aquí se le agregó empatía) | `brain.py`, `_ofrecer_disponibilidad` (rama sin opciones) | Por ahora no tengo horarios disponibles para ese servicio. Escríbeme más tarde para revisar de nuevo. | Lamento decirte que por ahora no tengo horarios disponibles para ese servicio. Escríbeme más tarde y lo revisamos de nuevo con gusto. |
| 3 | Ofrece disponibilidad real | `brain.py`, `_ofrecer_disponibilidad` (rama con opciones) | Perfecto, estas son las opciones disponibles: {opciones}. ¿Cuál prefieres? | ¡Perfecto! Estas son las opciones disponibles: {opciones}. ¿Cuál te queda mejor? |
| 4 | Identidad confirmada | `gateway.py`, `_MENSAJE_IDENTIDAD_CONFIRMADA` | Gracias, ya confirmé tu identidad. ¿En qué te puedo ayudar? Puedo programar, reprogramar, cancelar o consultar una cita. | ¡Gracias! Ya confirmé tu identidad. ¿En qué te puedo ayudar hoy? Puedo programar, reprogramar, cancelar o consultar tus citas. |
| 5 | Pedir documento (primer contacto por Chatwoot/Telegram) | `gateway.py`, `_MENSAJE_PEDIR_DOCUMENTO` | Antes de continuar, ¿me confirmas tu número de documento de identidad? Lo necesito para consultar tus datos de forma segura. | ¡Hola! Antes de seguir, ¿me confirmas tu número de documento de identidad? Lo necesito para consultar tus datos con seguridad. |
| 6 | Paciente declina | `brain.py`, rama `_es_negativo` de `_interpretar_decision` | Entiendo, gracias por tu tiempo. Si cambias de opinión, aquí estamos. | Entiendo perfectamente, gracias por tu tiempo. Si más adelante cambias de opinión, aquí voy a estar. |
| 7 | Pide información no autorizada (diagnóstico, resultados, etc.) | `brain.py`, rama `_INFO_NO_AUTORIZADA` de `_interpretar_decision` | Eso no lo tengo disponible por este canal — no puedo darte información clínica que no esté autorizada aquí. Si quieres, puedo poner en contacto al equipo para resolver esa duda. | Uy, esa parte no te la puedo compartir por este canal — no puedo darte información clínica que no esté autorizada aquí. Si quieres, con gusto pongo tu duda en manos del equipo para que te ayuden con eso. |
| 8 | "¿Por qué me contactan?" / pide más información — aquí se corrigió además la frase prohibida "te contactamos" que se había quedado sin arreglar en el recado 026 | `brain.py`, rama `_PIDE_INFO` de `_interpretar_decision` | Te contactamos por {motivo}. La idea es ayudarte a programar tu atención cuando te quede cómodo. ¿Te gustaría revisar opciones de horario? | Con gusto te cuento: esto es sobre {motivo}. La idea es ayudarte a programar tu atención cuando te quede cómodo. ¿Revisamos juntos las opciones de horario? |

## Notas de trazabilidad

- `{opciones}` y `{motivo}` son interpolaciones de datos reales (turnos reales del catálogo de disponibilidad, y el motivo real de la Activity) — nunca texto inventado; se muestran aquí como placeholder solo para no repetir contenido dinámico de ejemplo.
- Todas las garantías de fondo (guardrail `NoPrometerContactoGuardrail`, verificación de identidad, nunca inventar disponibilidad) se verificaron sin cambios después de este pase — ver recado 027 para el detalle de la suite de tests (184 recolectados, 182 pasando + 2 deshabilitados a propósito) y la confirmación explícita de `test_modifica_respuesta_con_promesa_prohibida`.
- **Aprobado por el usuario (2026-09-06)**, con un solo ajuste antes de commitear: en la fila 4, "consultar una cita tuya" → "consultar tus citas" (se lee más natural) — ya aplicado en `gateway.py` y reflejado en la tabla de arriba. Las otras 7 filas quedaron aprobadas sin cambios. Suite completa vuelta a correr después del ajuste: 182 pasando + 2 deshabilitados a propósito, sin regresiones.
