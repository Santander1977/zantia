# 060 — Verificación de despliegue de 093775f + el "correo faltante" no es un bug (es R-21)

**Fecha**: 2026-09-10
**Estado**: Solo investigación/documentación — **cero cambios de código** en esta sesión.

---

## 1. Contexto

El usuario probó `@Zantia_test_bot` en Telegram tras un despliegue en EasyPanel del commit `093775f` (recado 059: correo de confirmación real, 5ta opción de salida del menú, vocabulario de despedida ampliado). En la prueba real, el mensaje final tras reservar una cita no mencionó nada sobre el correo — ni éxito ni fallo — y el usuario pidió verificar despliegue + investigar esto antes de decidir si abordar la causa.

## 2. Verificación de despliegue

**[CONFIRMADO]** `git log`/`git status`/`git ls-remote origin refs/heads/main` — commit `093775f1140f13f75dadf069d95fa2b448c9d745` local y en `origin/main` (GitHub) son idénticos. Working tree limpio antes de empezar.

**[CONFIRMADO]** El usuario redesplegó en EasyPanel y compartió la URL pública: `https://curson8n-zantia.byrp3l.easypanel.host/`. `GET /health` real respondió `HTTP/2 200`, `server: uvicorn`, `{"status":"ok"}`.

**[DESCONOCIDO — límite estructural, no falta de esfuerzo]** Que el commit corriendo sea exactamente `093775f`. `service/app.py` solo expone `/health`, `/webhook/chatwoot`, `/webhook/telegram` — ninguno reporta hash/versión de build. No existe hoy ningún mecanismo para correlacionar HTTP↔commit con precisión. La única forma indirecta sería comportamiento observable exclusivo de `093775f` (ej. que el menú ya muestre la 5ta opción "Salir / terminar" en una conversación real) — no ejecutado en esta sesión.

**Documentado**: `.ai/DEPLOYMENT.md` (repo ZANTIA) actualizado con la URL pública, la nota de verificación de arriba, y corrección de 3 ítems del checklist que seguían marcados como pendientes (R-16, R-17, creación del servicio en EasyPanel) pese a estar resueltos hace días — quedaban contradictorios al lado de la URL real. Cambio sin commitear (regla del proyecto: ningún commit sin pedido explícito).

## 3. El "correo faltante" — investigado, NO es un bug

Leído el código real (no inferido):
- `domains/health/models.py:163-180` — `sufijo_confirmacion_correo(correo_confirmacion_enviado)`: si el parámetro es `None`, devuelve `""` **a propósito** (docstring explícito: "omitir el tema es más honesto que forzar una frase sobre algo que no ocurrió en absoluto").
- `domains/health/agent.py:208-218` y `domains/health/gateway.py:1482` — ambos caminos (reserva/reprogramación vía `agent.py`; cancelar/reprogramar vía el wizard de código de `gateway.py`) usan la MISMA función compartida.
- `domains/health/gateway.py:1457` — `correo_conocido = None` (hardcodeado) en el sub-flujo de cancelar/reprogramar por código.
- `domains/health/tools.py:56` — `BookAppointmentTool` llama `book_appointment(slot_id, patient_reference, idempotency_key)` sin `correo` en absoluto para una reserva nueva.

**Conclusión**: hoy, en TODO el flujo de ZANTIA, `correo` siempre llega `None` a estas funciones (nadie lo captura en ningún punto de la conversación) → `sufijo_confirmacion_correo(None)` siempre devuelve cadena vacía → el mensaje final de reserva/cancelación/reprogramación nunca menciona el correo hoy. Esto es exactamente el comportamiento diseñado en el recado 059/054, no una regresión ni una brecha de despliegue.

La única garantía de "siempre dice algo" que definió el recado 059 es para `respuesta_pregunta_sobre_correo` (`models.py:183-199`) — cuando el paciente pregunta EXPLÍCITAMENTE "¿me enviaste el correo?" — nunca para el sufijo automático tras confirmar.

**Nota honesta**: este comportamiento observado es indistinguible entre "093775f está desplegado y correo=None por diseño" y "093775f todavía no está desplegado y el mecanismo ni existe" — ambos casos se ven exactamente igual desde afuera. No sirve como evidencia indirecta de despliegue.

## 4. Causa raíz real: R-21, sigue ABIERTO por decisión explícita

`.ai/RISKS.md` R-21: ZANTIA no captura el correo del paciente en ningún punto de la conversación — causa raíz sin resolver desde el recado 015, confirmada de nuevo hoy leyendo el código real (sección 3). El usuario decidió explícitamente **dejarlo pendiente, no abordarlo hoy**. Confirmado con `grep` que R-21 sigue documentado como `ABIERTO` en `.ai/RISKS.md`, sin ninguna edición en esta sesión.

## 5. Archivos tocados

- `.ai/DEPLOYMENT.md` — única modificación de esta sesión (documentación, sin código). Sin commitear.

## 6. Información que debe conocer quien retome esto

- El repo ZANTIA no tiene ningún endpoint de versión/build — si en el futuro hace falta correlacionar despliegue↔commit con precisión, hay que decidir si vale la pena agregar uno (no pedido ni implementado hoy).
- R-21 sigue siendo la causa raíz real detrás de "el paciente nunca recibe confirmación de que se le envió el correo" — mientras no se resuelva, CUALQUIER reserva/cancelación/reprogramación real seguirá sin mencionar el correo en el mensaje automático, sin importar cuántas veces se redespliegue.

## 7. Preguntas pendientes

- ¿Cuándo se aborda R-21? Requiere una decisión de producto (¿se pide el correo en la conversación? ¿se reutiliza uno ya registrado en hrmm-backend por otro canal?) — no decidida hoy.
