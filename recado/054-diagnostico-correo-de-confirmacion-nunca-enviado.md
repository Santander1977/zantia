# 054 — Diagnóstico: el correo de confirmación nunca se envía (causa en ZANTIA, no en hrmm-backend)

**Fecha**: 2026-09-07
**Estado**: Solo diagnóstico, tal como pediste — nada corregido todavía.

---

## 1. ¿Es una afirmación garantizada o un texto fijo? — CONFIRMADO: texto fijo, sin verificación

`domains/health/agent.py:202-206` y `domains/health/gateway.py:1328/1331` — el mensaje "Te enviamos un correo de confirmación con todos los detalles" se concatena INCONDICIONALMENTE cada vez que `just_booked`/`just_rescheduled` es verdadero, sin ninguna llamada, campo de respuesta, ni verificación que confirme que algún correo se disparó. El comentario del propio código documentaba una ASUNCIÓN nunca verificada:

> "hrmm-backend ya envía ese correo de forma NATIVA al ejecutar el POST real — ZANTIA nunca lo dispara ni lo duplica, solo lo complementa conversacionalmente."

Esta asunción es **incorrecta**, confirmada leyendo el código real de hrmm-backend (ver punto 3).

## 2. ¿hrmm-backend expone alguna forma de confirmar el envío? — NO, en el POST de reserva

`Cita`/`Appointment` (el modelo que devuelve `POST /api/agenda/citas`) no tiene ningún campo de estado de correo (`correo_enviado`, `notificacion_enviada`, etc.) — ni en el schema de hrmm-backend ni en el mapeo de ZANTIA (`_cita_a_appointment`). No hay forma de verificar el envío consultando la respuesta de esa llamada, porque **esa llamada nunca dispara ningún envío** (ver punto 3).

## 3. Investigación real en hrmm-backend (repo separado, `/Users/enzoalfonso/Orangutan/hrmm`, SOLO LECTURA)

Leí el código real (no logs — la evidencia de código es más concluyente: una llamada que no existe en el código no puede haberse intentado ni fallado):

- `backend/app/api/agenda.py:crear_cita` (el handler de `POST /api/agenda/citas`, lo único que ZANTIA llama) — llama a `provider.crear_cita(datos)` y devuelve. **No dispara ningún correo.**
- `backend/app/providers/agenda/mock.py:crear_cita` (el provider REAL activo en producción, pese al nombre histórico) — hace el `INSERT` en `agenda.citas` (incluyendo la columna `correo` si se manda) y `COMMIT`. **Tampoco dispara ningún correo.**
- El envío de correo (`_enviar_correo_notificacion`, que sí llama al webhook real de n8n) **solo se invoca desde `portal_cancelar_cita`/`portal_reprogramar_cita`** (el portal público) — nunca desde `crear_cita`.
- **Confirmado con la propia documentación de hrmm** (`docs/progreso.md`): el envío de confirmación SIEMPRE es un segundo paso EXPLÍCITO, separado de la creación de la cita — `POST /api/agenda/citas/{cita_id}/enviar-confirmacion` con `{email}` en el body. El agente de webchat (un proyecto n8n DISTINTO a ZANTIA) tiene esto como paso 8 explícito de su propio system prompt: "ofrecer el correo de confirmación tras agendar/cancelar/reprogramar", y lo ejecuta como una llamada de tool SEPARADA después de reservar. El portal público hace lo mismo desde su wizard.

**Conclusión: hrmm-backend nunca envía un correo automáticamente al crear una cita — por diseño, es un paso explícito que cada integración debe disparar por su cuenta.** No es un bug de hrmm-backend ni requiere trabajo en ese repositorio — es una capacidad que existe y funciona (confirmada real y probada muchas veces en `docs/progreso.md`, con Gmail real, `labelIds:["SENT"]`), simplemente **ZANTIA nunca la invoca**.

Esto ya estaba parcialmente documentado en el propio ZANTIA, sin haberse actuado: `docs/health-demand-agent.md:150` — *"Envío del correo nativo de confirmación de hrmm-backend (POST /citas/{id}/enviar-confirmacion) — mecanismo DISTINTO al de verificación (...); coexiste sin cambios, ZANTIA no lo suprime ni lo reemplaza, pero tampoco lo invoca activamente todavía."*

## Hallazgo secundario (compuesto, pero no la causa principal)

`HrmmAppointmentService.book_appointment` (ZANTIA) tampoco envía nunca el campo `correo` en el body de `POST /api/agenda/citas`, pese a que el propio docstring del archivo documenta que la API lo acepta (`{slot_id, documento_paciente, nombre_paciente, telefono, correo?, canal}`). Esto es el hallazgo YA CONOCIDO R-21 (`.ai/RISKS.md`, recado 015, sigue ABIERTO) — pero es secundario: aunque ZANTIA empezara a enviar `correo`, hrmm-backend seguiría sin disparar ningún correo automáticamente en el booking (punto 3) — haría falta ADEMÁS el segundo paso explícito.

## 4-5. Decisión pendiente (nada corregido todavía)

El mensaje de ZANTIA es exactamente el tipo de promesa no verificada que `NoPrometerContactoGuardrail` existe para evitar en otros contextos — pero aplicado a un canal (correo) en vez de a un contacto humano. Dos caminos posibles, ninguno implementado:

1. **Verificar de verdad**: `HrmmAppointmentService.book_appointment` empieza a capturar/enviar `correo` (cierra R-21) y, tras reservar, ZANTIA llama explícitamente a `POST /citas/{id}/enviar-confirmacion` — solo entonces el mensaje deja de ser una promesa y pasa a ser una acción verificada (con manejo de fallo: si esa llamada falla, no repetir la promesa). Requiere: (a) capturar el correo del paciente en algún punto de la conversación (hoy `Activity.patient_contact` no lo pide nunca), (b) el nuevo método en `HrmmAppointmentService`, (c) el cambio de mensaje condicionado al resultado real.
2. **Dejar de prometerlo** hasta que (1) esté implementado — cambiar el texto para no mencionar el correo en absoluto, o dejarlo condicionado ("si nos compartes tu correo, te enviamos la confirmación por ahí también").

No implementé ninguna de las dos — pendiente de tu decisión de producto (¿vale la pena capturar el correo del paciente en la conversación?, ¿cuándo?) antes de tocar código.

## Pendiente de tu decisión

1. ¿Cuál de los 2 caminos de la sección anterior prefieres (o alguno mixto)?
2. Si eliges el camino 1: ¿en qué punto de la conversación se debería pedir el correo? (¿siempre?, ¿solo si el paciente ya lo dio antes?, ¿opcional al final?)
