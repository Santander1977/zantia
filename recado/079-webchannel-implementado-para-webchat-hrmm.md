# 079 — WebChannel implementado para ZANTIA (integración con el webchat de HRMM)

**Fecha**: 2026-09-11
**Tipo**: implementación completa, probada, **NO desplegada** — a la espera de confirmación explícita del usuario para el push/deploy en EasyPanel (regla `.claude/rules/proteccion-produccion-y-codigo.md`: ningún commit/push sin pedido explícito en el turno correspondiente).
**Repo**: `/Users/enzoalfonso/Orangutan/icaco` (ZANTIA)
**Continúa**: recado `077` (protocolo real de `eis-chat-hrmm`, investigación) y `078` (plan, preguntas abiertas) — este recado responde las 3 preguntas que 078 dejó pendientes y las implementa.

## 1. El pedido, textual (resumen)

Construir el WebChannel más simple de los tres existentes, para conectar `chat.semcolombia.com` (repo `eis-chat-hrmm`) a ZANTIA en producción HOY, sin período de prueba, riesgo aceptado explícitamente por el usuario. Contrato confirmado: entrada `{message, sessionId}`, salida `{"reply": str}` (JSON simple, sin streaming). `sessionId` como identificador de canal para el gate de identidad. Sin autenticación de webhook por ahora (riesgo documentado, no bloqueante). Errores nunca como 500 crudo — siempre `{"reply": "..."}` con 200.

## 2. Respuestas a las 3 preguntas abiertas del recado 078

1. **¿`{reply}` simple o `{success, reply, sessionId}`?** → Confirmado por el usuario: `{"reply": str}` simple. Esto significa que **`eis-chat-hrmm/src/server.js` SIGUE sin modificar** (fuera de alcance de este recado, alcance explícito "solo ZANTIA") — hoy ese archivo todavía envía `{action, chatInput, sessionId}` (contrato de n8n) y parsea NDJSON, NO el contrato `{message, sessionId}` → `{reply}` que este WebChannel ya expone. **Esto es un bloqueante real para el corte a producción "HOY" tal como está planteado** — ver sección 6 (huecos).
2. **¿Autenticación propia?** → No, decisión explícita del usuario. Documentado como riesgo nuevo (`.ai/RISKS.md` R-26) en `.ai/API_CONTRACTS.md`, `.ai/SECURITY.md` y `.ai/ARCHITECTURE.md` (regla `.claude/rules/contratos-api.md`: ningún endpoint sin auth queda sin decisión documentada).
3. **¿Se resuelve primero el `sessionId` efímero?** → Ya resuelto, en la sesión anterior de `eis-chat-hrmm` (commit `c83d3d9`, pusheado a `origin/main` de ese repo): `sessionId` ahora persiste en `localStorage` con expiración deslizante de 24h de inactividad. Confirmado con navegador real (Chrome) antes de esta sesión.

## 3. Qué se construyó

- **`channels/web_channel.py`** (nuevo) — `WebChannel`, implementa `Channel` Protocol (`contract.py`, sin modificarlo). El canal MÁS SIMPLE de los tres: ciclo request/response síncrono de un solo paso (`handle_request()` encola, `receive()` desencola, `send()` solo registra en `.sent` — nunca toca la red, a diferencia de `TelegramChannel.send()`/`ChatwootChannel.send()`). Sin ningún `http_post` inyectable porque no hay ninguna llamada de red que hacer. `sessionId` es el `conversation_id`, mismo patrón que `chat_id` de Telegram (autosuficiente, sin tabla `_conversaciones_*`).
- **`domains/health/gateway.py`** — una sola línea real modificada: `"web"` agregado a `_CANALES_SIN_IDENTIFICADOR_DOCUMENTO` (línea ~475). Mismo mecanismo exacto que ya cubre Chatwoot/Telegram (wizard documento → código → `identidad_canal`, vencimiento 180 días, olvido a pedido) — **cero cambios en `Orchestrator`/`HealthBrain`/`guardrails`**, tal como pedía el requisito explícito.
- **`service/app.py`** — import de `WebChannel`/`WebChannelError`; construcción directa `_canal_web = WebChannel()` (sin función `_construir_canal_web()` propia — no hay ninguna variable de entorno que pueda faltar); nuevo endpoint `POST /webhook/web`.
- **`POST /webhook/web`** — lee `{message, sessionId}`, llama `_canal_web.handle_request(...)` → `handle_inbound_message(_gateway, ...)` (MISMO gateway compartido con Chatwoot/Telegram) → `{"reply": texto}`. Todo el cuerpo corre dentro de un único `try/except Exception` deliberadamente amplio (única excepción a "nunca atrapar Exception genérico" de este archivo — justificado en el docstring del endpoint): sin ningún secreto que verifique el origen, cualquier payload malformado o fallo interno real debe volver como `200 {"reply": "<mensaje genérico>"}`, nunca un 500 — se registra siempre con `logger.exception`, nunca en silencio.

## 4. Verificación con evidencia real

Suite completa: **592 passed + 15 skipped (mismos skips preexistentes, gateados por red real) — cero regresiones**, corrida con `python -m pytest -q` dentro del `.venv` del proyecto. 16 tests nuevos:

- `tests/channels/test_web_channel.py` (6 tests) — traducción a `InboundMessage`, rechazo explícito sin `message`/`sessionId`, `send()` no toca red, `receive()` sin cola falla como los demás canales (`IndexError`), `message_id` distinto por mensaje.
- `tests/domains/health/test_identity_gate_web.py` (3 tests) — mirror casi literal de `test_identity_gate_telegram.py`, con `FakeHttpClient`/`HrmmAppointmentService` reales (sin red): un `sessionId` nuevo dispara el wizard completo (documento → código → `identidad_canal` VERIFICADO), uno ya verificado no lo repite, y dos `sessionId` distintos son identidades de canal independientes.
- `tests/service/test_app.py` (7 tests nuevos, vía `TestClient` de FastAPI):
  - **Contrato exacto**: `{message, sessionId}` → `200 {"reply": str}`, y SOLO esa clave (prueba de contrato, regla `.claude/rules/testing.md`).
  - **Persistencia de sesión**: dos peticiones HTTP separadas con el mismo `sessionId` se correlacionan como la misma conversación (`find_open_context`).
  - **Manejo de errores** (3 tests): sin `message`, sin `sessionId`, body que no es JSON — los 3 responden `200 {"reply": "<genérico>"}`, nunca un error crudo.
  - **Fallo interno simulado**: `handle_inbound_message` lanza `RuntimeError` (monkeypatch) → `200 {"reply": "<genérico>"}`, nunca 500 (mismo patrón que `test_webhook_telegram_fallo_al_responder_no_produce_500`, recado 023).
  - **End-to-end real** (requisito #4 del pedido): conversación de 4 turnos vía `/webhook/web` contra el `Orchestrator`/`HealthBrain`/guardrails REALES (solo `MockAppointmentService`, el default de `app_module`, evita red real hacia hrmm-backend) — saludo institucional con menú → elegir "Reservar" → elegir fecha → avanza sin caer en el mensaje de error genérico. Mismo `sessionId` en las 4 peticiones, confirmando que el flujo completo de reserva es alcanzable por este canal nuevo.

Sin red real ejercitada hacia `eis-chat-hrmm` ni hacia `hrmm-backend` en esta sesión — todo probado con `TestClient`/`FakeHttpClient`, como exige `.claude/rules/seguridad-y-secretos.md`.

## 5. Documentación actualizada (regla `.claude/rules/contratos-api.md`/`documentacion-y-memoria.md`)

- `.ai/API_CONTRACTS.md` — fila nueva para `/webhook/web` + nota de seguridad explicando la decisión de no-auth.
- `.ai/SECURITY.md` — entrada nueva en "Notas de auditoría de seguridad".
- `.ai/RISKS.md` — **R-26** (nuevo, ABIERTO): sin autenticación en `/webhook/web`, decisión explícita del usuario, mitigación mínima documentada (siempre 200, nunca fuga de info interna; alcance del daño limitado al flujo conversacional normal).
- `.ai/ARCHITECTURE.md` — tabla de componentes (`WebChannel` agregado junto a Chatwoot/Telegram) + fila nueva en "Rutas críticas" (🟡, por el riesgo de auth) + referencia actualizada en el párrafo de brecha de identidad.
- **`.ai/CURRENT_STATE.md` deliberadamente NO actualizado** — ya estaba ~27 recados detrás (se detiene en el recado `051`, con una nota propia de "brecha de esta snapshot" para 027-048) antes de empezar esta sesión; agregar solo el recado 079 ahí sin cerrar esa brecha previa habría sido más confuso que útil. Decisión de alcance, no un olvido — la destilación completa de 052-079 es tarea aparte (el propio archivo documenta que es "tarea típica del agente memory-keeper").

## 6. Huecos reales para el corte a producción "HOY" — leer antes de desplegar

1. **`eis-chat-hrmm/src/server.js` NO fue tocado y sigue hablando el contrato viejo de n8n** (`{action, chatInput, sessionId}` saliente, parseo NDJSON entrante) — este WebChannel espera `{message, sessionId}` y devuelve `{reply}` simple. **Si hoy se apunta la URL de destino de `eis-chat-hrmm` directo a `https://<host-easypanel>/webhook/web` sin tocar ese archivo, el widget se rompe**: Express seguiría mandando `{action, chatInput, sessionId}` (que `WebChannel.handle_request` rechazaría con `WebChannelError` porque no hay campo `message` → respondería `{"reply": "<genérico>"}`, un mensaje de error amable pero SIEMPRE el mismo, nunca la respuesta real del dominio) y, aun si se corrigiera el envío, seguiría intentando parsear NDJSON de una respuesta que ya no lo es. **Este es un cambio pendiente, separado, en el OTRO repo** (`eis-chat-hrmm`), fuera del alcance explícito de este recado ("construir un WebChannel para ZANTIA"). Recomendación: antes de redirigir tráfico real, simplificar el bloque `axios.post` de `server.js` (líneas ~57-92) para enviar `{message, sessionId}` y leer `{reply}` directo — cambio pequeño, ya analizado en el recado 077.
2. **Sin secreto de webhook** (R-26) — riesgo aceptado explícitamente, no bloqueante, pero real: hoy cualquiera que descubra la URL de `/webhook/web` puede iniciar conversaciones del dominio salud.
3. **`HRMM_BACKEND_ENV` en el despliegue real de EasyPanel** — si está en `production` (no verificado en esta sesión, no se tocó ningún `.env` de despliegue), el gate de identidad (`_CANALES_SIN_IDENTIFICADOR_DOCUMENTO` con `"web"`) SÍ se activa de verdad — un usuario nuevo del webchat pasará por el wizard completo de documento + código de verificación por correo antes de poder gestionar una cita real. Esto nunca se probó contra la red real de hrmm-backend con el canal `"web"` específicamente (sí con `FakeHttpClient`, ver sección 4) — mismo estado de riesgo ya heredado de Telegram/Chatwoot (R-15).
4. **Nada de esto se desplegó** — ningún commit, ningún push, ningún cambio en EasyPanel. A la espera de confirmación explícita del usuario, y de una decisión sobre el punto 1 (¿se toca `eis-chat-hrmm/server.js` en la misma sesión de deploy, o se acepta que el corte real quede pendiente de esa segunda mitad?).

## 7. Archivos tocados (todos en `/Users/enzoalfonso/Orangutan/icaco`, ninguno en `eis-chat-hrmm`)

- Nuevos: `channels/web_channel.py`, `tests/channels/test_web_channel.py`, `tests/domains/health/test_identity_gate_web.py`
- Modificados: `domains/health/gateway.py` (1 línea funcional + comentario), `service/app.py` (import + construcción + endpoint nuevo), `tests/service/test_app.py` (7 tests nuevos), `.ai/API_CONTRACTS.md`, `.ai/SECURITY.md`, `.ai/RISKS.md`, `.ai/ARCHITECTURE.md`
- Sin tocar (confirmado): `core/orchestrator.py`, `core/brain.py`, `domains/health/agent.py`, `domains/health/brain.py`, `guardrails/*`, `channels/contract.py`, `channels/telegram_channel.py`, `channels/chatwoot_channel.py`

## 8. Siguiente paso

Reportar al usuario: implementación lista y probada (16 tests nuevos, suite completa 592/592 + 15 skipped, cero regresiones). Pedir explícitamente: (a) confirmación para commitear y pushear a `origin/main` de `icaco`, (b) decisión sobre el hueco de la sección 6.1 (`eis-chat-hrmm/server.js`) antes de considerar el corte "completo", y (c) confirmación de que EasyPanel ya tiene auto-deploy configurado desde ese remoto (no verificado en esta sesión — `.ai/RISKS.md` R-12 sigue abierto sobre plataforma de despliegue).
