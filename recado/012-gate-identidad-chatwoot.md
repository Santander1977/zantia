# RECADO PARA CHATGPT

Fecha: 2026-09-01
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Resolución de la brecha de identidad teléfono↔documento (R-15, identificada en recado `011`) — gate de identificación en `domains/health/gateway.py`.
Objetivo: Documentar el mecanismo implementado, cómo se persiste la asociación teléfono→documento dentro de una conversación, y el resultado de las 7 pruebas pedidas por el usuario (6 nuevas + la suite completa).

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. PENDIENTE = decisión o dato aún no confirmable, nunca inventado. Ver recado `011` para el contexto completo de R-15 (dónde se encontró la brecha, por qué `_identidad_resuelta` existía sin conectar desde 009).

---

## Resumen ejecutivo

HECHO: se implementó el gate de identidad en `domains/health/gateway.py`, sin tocar `HealthBrain`, `ChatwootChannel` ni `HrmmAppointmentService` (restricción explícita del usuario) y sin modificar ninguno de los 109 tests preexistentes. **115 tests pasando + 1 deshabilitado a propósito** (116 recolectados) — 6 tests nuevos, 0 tests rotos.

**Decisión de producto que llegó ya tomada** (no se negoció ni se propuso alternativa): pedir el documento explícitamente en el primer turno de una conversación nueva por un canal cuyo identificador no es un documento, en vez de negociar un endpoint nuevo con hrmm-backend.

## Mecanismo implementado

**Gate scoped por canal, no por AppointmentService** (ajuste encontrado durante la implementación, ver sección "Corrección encontrada" abajo): el gate solo se activa cuando (a) el `AppointmentService` activo distingue identificador de canal de documento real (`HrmmAppointmentService`, detectado con el mismo duck-typing que ya usaba `resolve_patient_identity` desde 009: `getattr(appointment_service, "buscar_paciente", None)`) Y (b) el canal concreto está en `_CANALES_SIN_IDENTIFICADOR_DOCUMENTO = {"chatwoot"}` — un allowlist explícito, deliberadamente no inferido del nombre del canal, para no gatear por accidente un canal futuro que sí entregue el documento directamente.

**Flujo de 2 turnos** (decisión de diseño, no pedida explícitamente pero la más simple y menos arriesgada de implementar correctamente — ver "Decisiones autónomas" abajo):
1. Primer mensaje de un número nuevo, sin identidad resuelta → `domains/health/gateway.py:_gestionar_identificacion` responde pidiendo el documento. NINGUNA otra intención se procesa en este turno (no se clasifica intención, no se crea `PatientRequest` ni `Activity`).
2. Segundo mensaje (el documento) → se llama `resolve_patient_identity` (009, sin tocar) contra `GET /citas/buscar-paciente` (público, sin secreto). Si hay match: se guarda `gateway._identidad_resuelta[patient_reference] = documento` y se confirma. Si no hay match: mensaje claro, se puede reintentar (hasta 3 veces).
3. Mensajes siguientes de ese mismo número, dentro de la misma "sesión" del proceso: `patient_reference in gateway._identidad_resuelta` ya es verdadero → el gate no vuelve a activarse, se procesa normalmente.

## Persistencia (requisito #3 — sin duplicar un mecanismo existente)

Se reutilizó `HealthGateway._identidad_resuelta: Dict[str, str]` — campo YA DECLARADO en 009 pero nunca conectado. Es un dict en memoria de proceso, EXACTAMENTE el mismo patrón que los otros tres dicts de correlación ya existentes en `HealthGateway` (`_open_conversations`, `_contexts`, `_pending_verifications`) — se agregó un cuarto dict del mismo tipo, `_pending_identity: Dict[str, Dict[str, Any]]` (patient_reference -> {"channel", "intentos"}), para rastrear una identificación en curso.

**Por qué NO se usó `ConversationState`/`StateStore`** (se revisó explícitamente, como pidió el usuario): en el momento en que se necesita saber "¿ya se identificó este número?", TODAVÍA no existe ninguna `Activity` ni `ConversationState` — ambas nacen DESPUÉS de que la identidad se resuelve (ver `_resolver_programar_cita`/`_resolver_gestion_de_cita_existente`). `ConversationState` está indexado por `activity_id`, no por número de teléfono, así que no es alcanzable en este punto del flujo. Los dicts de `HealthGateway` (en memoria de proceso, igual que los tres ya existentes) son el mecanismo correcto y ya establecido para "estado compartido entre conversaciones, indexado por identificador de canal" — no se inventó uno nuevo.

**Límite conocido de esta persistencia** (heredado de los otros tres dicts, no nuevo de este cambio): vive en memoria de proceso — un reinicio del servicio pierde todas las identidades ya resueltas, y el paciente tendría que volver a dar su documento. Ya documentado como riesgo general (`.ai/RISKS.md` R-11, "persistencia solo parcial") — no se resolvió aquí porque no era parte del pedido.

## Uso del documento resuelto (no solo se pide, se USA)

Se corrigieron los puntos donde el código, antes de este cambio, pasaba `request.patient_reference` (el número de teléfono) directo a `AppointmentService`/`Activity.patient_reference` asumiendo que YA era el documento — exactamente el bug que R-15 describía. Se agregó `_documento_resuelto(gateway, patient_reference)` (helper de una línea: `gateway._identidad_resuelta.get(patient_reference, patient_reference)` — con fallback al valor tal cual si no hace falta resolución, o sea CERO cambio de comportamiento para Mock o para cualquier canal fuera del allowlist) y se usó en:
- `_resolver_programar_cita` / `_resolver_gestion_de_cita_existente`: el documento resuelto es lo que se guarda en `Activity.patient_reference` (lo que `agent.py`/`tools.py`, sin tocar, terminan pasando a `AppointmentService`).
- `_resolver_consulta` / `_resolver_confirmacion` / `_resolver_gestion_de_cita_existente`: `get_patient_appointments(...)` recibe el documento resuelto, no el teléfono.
- `_iniciar_verificacion_para_gestion`: `documento = _documento_resuelto(...)` en vez de asumir `request.patient_reference` directo.

**La correlación (`_open_conversations`/`register_context`/`find_open_context`) sigue usando el número de teléfono sin cambios** — es correcto que así sea: los mensajes siguientes del paciente llegan identificados por su número, no por su documento, así que la correlación DEBE seguir siendo por teléfono. Solo el valor que finalmente llega a `AppointmentService` cambió.

## Corrección encontrada durante la implementación (no oculta)

El primer diseño gateaba por `_requiere_identidad_real(gateway)` SOLO (cualquier uso de `HrmmAppointmentService`, sin importar el canal). Al correr la suite completa, esto ROMPIÓ 4 tests preexistentes de `test_hrmm_gateway_verification.py` que usan `HrmmAppointmentService` con `channel="demo"` y un `patient_reference` arbitrario (ej. `"999"`) que esos tests YA asumían como documento — exactamente el supuesto anterior a esta extensión, válido para ese canal de prueba. Corregido restringiendo el gate a `_CANALES_SIN_IDENTIFICADOR_DOCUMENTO = {"chatwoot"}` — consistente con el requisito explícito del usuario ("ChatwootChannel, específicamente"). Con esta corrección, los 109 tests preexistentes volvieron a pasar sin ninguna modificación.

## Escalamiento tras intentos fallidos (requisito #5)

Límite: 3 intentos (sugerido por el usuario, "ej. 3"). Al tercer documento inválido consecutivo: se limpia `_pending_identity` (nunca queda en limbo — un mensaje posterior arranca el gate de nuevo desde cero, no queda atascado), y se reutiliza el MISMO mecanismo de escalamiento que ya existe en este archivo para `RequestIntent.ESCALAMIENTO`: se crea una `PatientRequest` con `status=RequestStatus.ESCALADA` (para quedar en el registro/auditoría de solicitudes) y se responde con el mismo mensaje `_MENSAJE_ESCALAMIENTO_INBOUND` ya usado en el resto del archivo — no se inventó un mecanismo de escalamiento nuevo.

## Caveat de producto NO resuelto aquí, documentado explícitamente (no inventado)

`GET /citas/buscar-paciente` (hrmm-backend, público, 009) solo encuentra pacientes con historial PREVIO en ese sistema. Un paciente genuinamente NUEVO (nunca antes registrado en hrmm-backend, pero con un documento de identidad perfectamente válido) sería rechazado por este gate como si su documento no existiera — porque, desde la perspectiva de hrmm-backend, en efecto no existe todavía. Esto es una consecuencia directa de la decisión de producto ya tomada por el usuario (usar `buscar-paciente` tal cual, sin negociar un endpoint nuevo) — no es un bug de esta implementación, pero es una limitación real que el usuario debe decidir si acepta o si amerita un mecanismo distinto para pacientes nuevos (fuera de alcance de este pedido). Documentado en `.ai/RISKS.md` R-15 como parte de por qué queda PARCIALMENTE MITIGADO, no MITIGADO.

## Decisiones autónomas tomadas en este trabajo

1. **Flujo de 2 turnos** (pedir -> confirmar) en vez de un flujo de 1 turno que recuerde el mensaje original y lo re-procese automáticamente tras identificarse. Más simple, más fácil de verificar correctamente, y consistente con la lectura literal del pedido ("el primer turno... debe pedir el documento antes de continuar con cualquier gestión"). El sub-flujo de verificación por código (009) SÍ retoma la acción original automáticamente tras el código — se consideró imitar ese patrón aquí, pero se prefirió la opción más simple dado que el pedido no lo exigía explícitamente.
2. **Gate scoped por canal** (`_CANALES_SIN_IDENTIFICADOR_DOCUMENTO`), no por AppointmentService — encontrado necesario al correr la suite completa (ver "Corrección encontrada" arriba), y coherente con el requisito explícito del usuario de acotar esto a ChatwootChannel.
3. **Reutilizar `_identidad_resuelta`/dicts en memoria de proceso** en vez de `ConversationState`, tras revisar explícitamente por qué `ConversationState` no es alcanzable en este punto del flujo (ver sección "Persistencia" arriba).

## Verificación (7 pruebas pedidas)

Nuevo archivo: `tests/domains/health/test_identity_gate_chatwoot.py` (6 tests, todos contra `HrmmAppointmentService` real con `FakeHttpClient` — sin red real):

1. `test_mensaje_nuevo_por_chatwoot_sin_identidad_pide_documento` — PASA. Confirma que el primer turno pide el documento y que NO se crea ninguna `PatientRequest` todavía.
2. `test_documento_valido_resuelve_identidad_y_continua` — PASA. Documento válido (con `buscar-paciente` programado para encontrarlo) resuelve la identidad, y un mensaje posterior se procesa usando el documento real contra `AppointmentService` (verificado indirectamente: la respuesta solo llega a "no tienes ninguna cita" si `get_patient_appointments(documento)` se consultó con el documento correcto).
3. `test_documento_no_encontrado_no_resuelve_identidad` — PASA. Documento que `buscar-paciente` no encuentra (404 simulado) da un mensaje claro y NO resuelve la identidad — puede reintentar.
4. `test_segundo_mensaje_ya_identificado_no_vuelve_a_pedir_documento` — PASA. Con la identidad ya resuelta, un mensaje nuevo se procesa directo, sin repreguntar.
5. `test_camino_activity_outbound_no_se_ve_afectado` — PASA. `require_document_on_activity` (009, sin tocar) sigue exigiendo el documento en el payload exactamente igual; `start_activity_and_register` (camino outbound) no invoca el gate en absoluto.
6. `test_limite_de_intentos_fallidos_escala` — PASA. 3 documentos inválidos consecutivos escalan (mensaje de escalamiento + `PatientRequest` con `status=ESCALADA` creada), y un mensaje posterior no queda atascado (arranca el gate de nuevo).
7. Suite completa: `.venv/bin/pytest -q` → **115 passed, 1 skipped** (109 preexistentes SIN modificar + 6 nuevos). Comando ejecutado y confirmado en esta sesión.

## Pendiente (no resuelto aquí, ni inventado)

- Probar este mecanismo contra la red real de hrmm-backend (sigue bloqueado por no tener `HRMM_BACKEND_SECRET`, ver recado `011`).
- Confirmar con evidencia real, de punta a punta (`HRMM_BACKEND_ENV=production` de verdad + `ChatwootChannel` conectado a un inbox real), antes de considerar cambiar el default de `HRMM_BACKEND_ENV` — sigue en `mock`, tal como pidió el usuario explícitamente para esta fase.
- Decisión de producto sobre pacientes genuinamente nuevos que `buscar-paciente` no encuentra (ver caveat arriba) — no resuelta, no inventada.

RECADO GENERADO: /Users/enzoalfonso/recado/012-gate-identidad-chatwoot.md
