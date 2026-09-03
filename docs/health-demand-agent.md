# Agente de Demanda Inducida y Gestión de Atención — dominio salud

> Documenta lo REALMENTE implementado en `domains/health/` (prompt maestro 007, sección 42). No es una propuesta — cada afirmación aquí corresponde a código que existe y a tests que pasan (`.venv/bin/pytest tests/domains/health -q`).

## Propósito

Gestionar pacientes previamente identificados por un sistema de una IPS (institución prestadora de servicios de salud) como candidatos para una actividad de demanda inducida: contactarlos, explicarles el motivo, resolver dudas dentro de lo autorizado, facilitar la programación de una cita, gestionar recordatorios y reprogramaciones, y devolver el resultado al sistema originador.

**Este agente NO diagnostica, NO prescribe, NO modifica tratamientos y NO decide por sí mismo que un paciente necesita una intervención.** La necesidad de contacto viene siempre de una `Activity` creada por el sistema originador (IPS).

## Arquitectura

Este dominio se construyó **sobre** el Core existente (`core/`, `state/`, `memory/`, `knowledge/`, `tools/`, `guardrails/`, `observability/` — documentado en `.ai/ARCHITECTURE.md`), sin reemplazarlo. `domains/health/` añade:

```
IPS (sistema originador)
   │  create Activity
   ▼
ActivitySource (MockActivitySource)  ── domains/health/activity_source.py
   │
   ▼
domains/health/agent.py  ── capa de orquestación de dominio (el "pegamento")
   │
   ├── core.Orchestrator (Core, sin modificar salvo la corrección de la sección "Correcciones")
   │      ├── HealthBrain           (domains/health/brain.py)
   │      ├── ConversationState     (Core: state/)
   │      ├── GuardrailEngine       (Core: guardrails/, mismas 3 reglas del Core)
   │      └── ToolRegistry          (tools de dominio: domains/health/tools.py)
   │
   ├── AppointmentService (MockAppointmentService)  ── domains/health/appointment_service.py
   ├── ReminderManager                                ── domains/health/reminder_manager.py
   └── ActivityResultSink (MockActivityResultSink)   ── domains/health/result_sink.py
                                                          │
                                                          ▼
                                                    IPS (resultado)
```

## Tres capas de estado (decisión documentada — prompt 007, sección 6)

1. **`ConversationState.fase_actual`** (Core) — micro-estado de UN turno conversacional. No cambia entre dominios.
2. **`Activity.status`** (`domains/health/models.py`) — ciclo de vida GRUESO: `PENDING -> ACCEPTED/IN_PROGRESS -> COMPLETED/FAILED/CANCELLED/EXPIRED`.
3. **`Activity.management_status`** (`domains/health/models.py`) — progreso GRANULAR del dominio: `NOT_CONTACTED -> CONTACTING -> CONTACTED -> ENGAGED -> APPOINTMENT_PENDING -> APPOINTMENT_CONFIRMED -> REMINDER_72H/24H/8H -> ATTENDED/NO_SHOW/RESCHEDULE_REQUESTED/RESCHEDULED/DECLINED/ESCALATED`.

Ninguna capa se infiere de otra. La única capa con autoridad para escribir 2 y 3 es `domains/health/agent.py` (nunca el Brain).

## Flujo conversacional

```
CONTACTAR (plantilla determinista, no generada por el Brain)
   ↓
IDENTIFICAR intención / EXPLICAR MOTIVO / INFORMAR
   ↓
DECISIÓN del paciente:
   ACEPTA ──────────────► consulta disponibilidad ► ofrece opciones ► selección ► reserva ► confirmación
   NO ACEPTA ───────────► DECLINED
   NO PUEDE AHORA ──────► finalizada (sin decisión)
   SOLICITA HUMANO ─────► ESCALATED (vía el mecanismo de escalación ya existente del Core)
   PIDE INFO ───────────► responde con lo autorizado (Activity.program/reason)
   PIDE INFO NO AUTORIZADA ► indica limitación, no inventa, no escala automáticamente
```

Tras una cita confirmada, en cualquier momento posterior (incluida la respuesta a un recordatorio):
```
"no puedo asistir" / "reprogramar" ► nuevas opciones ► selección ► reprogramación ► cancela recordatorios viejos ► nuevos recordatorios
"cancelar la cita"                ► cancelación ► Activity.status = CANCELLED ► cancela recordatorios
"confirmo" / "asistiré"           ► management_status vuelve a APPOINTMENT_CONFIRMED
```

## Entidades

- **`Activity`**: unidad de trabajo (identidad, objetivo, paciente, contexto autorizado, gestión, agenda, control). Minimización de datos: solo lo estrictamente necesario, ningún dato clínico adicional.
- **`Appointment`**: referencia a la cita — ZANTIA nunca es el sistema maestro de agenda, solo guarda `appointment_id` + datos mínimos.
- **`Reminder`**: uno por tipo (`REMINDER_72H`/`24H`/`8H`) por cita, con programación **determinista** (aritmética de fechas, no generada por el Brain).
- **`ActivityResult`**: lo que se reporta de vuelta al sistema originador.

## Integraciones (todas Mock en este MVP — contratos listos para intercambiar por reales sin tocar el Brain, sección 39)

| Interfaz | Mock actual | Futuro real |
|---|---|---|
| `ActivitySource` | `MockActivitySource` (memoria) | `POST /activities` |
| `AppointmentService` | `MockAppointmentService` (memoria, dinámica) | API real de agenda |
| `ActivityResultSink` | `MockActivityResultSink` (memoria) | `POST /activity-results` |
| `Channel` (Core) | `channels/mock_channel.py:MockChannel` | WhatsApp / Web / Voz / SMS |

## Correcciones encontradas al implementar (transparencia, no ocultas)

1. **`core/orchestrator.py`**: la respuesta final no reflejaba si una tool WRITE fallaba sin lanzar excepción (solo el caso de excepción se manejaba). Corregido: ahora, si `ToolResult.success is False`, la respuesta nunca afirma éxito — cumple explícitamente la sección 14 ("no declarar confirmado si el sistema no confirmó"). También se corrigió que un error irrecuperable de tool ahora sí transiciona formalmente a `ESCALADO_ESTANDAR` (antes solo lo *declaraba* sin persistir la transición).
2. **`state/machine.py`**: se agregaron las transiciones `RECOPILACION_DE_DATOS -> RESPUESTA` y `IDENTIFICACION_DE_INTENCION -> RESPUESTA` — necesarias porque, dentro de un mismo turno síncrono, "razonar + ejecutar una tool" puede completarse sin necesitar una parada de fase intermedia.
3. **`HealthBrain`**: inicialmente recibía la `Activity` por valor en el constructor — como `Activity` es un modelo pydantic inmutable (cada actualización crea una copia nueva), esto congelaba al Brain con la versión inicial para siempre (nunca veía `appointment_id` tras reservar). Corregido: recibe un proveedor perezoso (`lambda: context.activity`).
4. **Sincronización de `management_status`**: comprobar solo "¿existe la clave en `resultado_de_herramientas`?" es insuficiente porque ese diccionario es acumulativo entre turnos — tras una reprogramación, seguiría "ganando" el resultado de la reserva original. Corregido: se usa la etapa **actual** del turno + un marcador "de un solo disparo" que se consume tras usarse.

## Tests

`tests/domains/health/` — 29 tests, todos pasando junto con los 34 del Core (`.venv/bin/pytest -q` → 63/63). Cubren: creación/validación/ciclo de vida de Activity, consulta y selección de disponibilidad, reserva y su idempotencia, fallo de reserva sin declarar éxito falso, los 3 recordatorios y su idempotencia, respuesta a un recordatorio, reprogramación (con cancelación de recordatorios antiguos), cancelación, no-show, escalamiento, declinación, información no autorizada, `ActivityResult` y su callback idempotente, y dos escenarios end-to-end completos (camino feliz con recordatorios simulados, y camino de reprogramación) — este último reproduce literalmente el flujo pedido en la sección 37 del prompt maestro.

## Seguridad y datos

Todos los pacientes y datos usados en tests/ejemplos son ficticios (`PAC-*`, "María Rodríguez" como ejemplo del prompt). No se registran datos clínicos más allá de lo mínimo necesario (`objective`, `reason`, `service`) — ningún diagnóstico, resultado de examen ni historia clínica se modela en `Activity`. El manejo de "información no autorizada" nunca inventa datos ni intenta responder desde fuera del contexto de la Activity.

## Limitaciones conocidas (no resueltas en este MVP)

- No hay canal real conectado (`MockChannel` demuestra el contrato, sección 30).
- El protocolo de riesgo/urgencia real sigue siendo el genérico y no-clínico heredado del Core (`core/brain.py:RISK_KEYWORDS_DEMO`) — el criterio clínico real sigue **PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL** (heredado de `003`/`004`).
- `ReminderManager`/`EventLog` viven en memoria de proceso — no hay un scheduler real que dispare recordatorios por sí solo a la hora programada (en este MVP, `fire_reminder` se invoca explícitamente, simulando el paso del tiempo).
- `MockAppointmentService` no modela solapamiento de turnos, franjas por profesional/agenda real ni reglas de negocio de la IPS — es deliberadamente simple (sección 38: no sobrediseñar).

## Extensión: acceso bidireccional (`domains/health/gateway.py`)

Añadida sobre este mismo dominio (2026-09-01, misma sesión), sin tocar `Activity`, `HealthBrain`, `AppointmentService`/`MockAppointmentService` (salvo la extensión aditiva `get_patient_appointments`), `ReminderManager`, `ActivityResultSink`, `MockChannel` ni las funciones existentes de `agent.py`.

**Problema que resuelve**: hasta aquí, toda conversación nacía de una `Activity` creada por la IPS (`contact_patient`, siempre outbound). Un mensaje **inbound** puede ser una respuesta a algo en curso o una solicitud nueva del paciente — el documento fuente original no especificaba cómo distinguirlos.

**Mecanismo de correlación** (`HealthGateway`, `domains/health/gateway.py`): un registro `patient_reference -> conversation_id` (verificado por frescura en cada consulta, no por cierre explícito recordado en cada punto de salida). Si hay una conversación abierta, se enruta ahí con `handle_patient_message` (Core, sin tocar). Si no, se clasifica la intención (`domains/health/intent.py`, determinista por palabras clave, independiente de `HealthBrain`) y se crea una `PatientRequest`.

**Reuso, no duplicación**: `PROGRAMAR_CITA`/`REPROGRAMAR_CITA`/`CANCELAR_CITA` iniciados por el paciente construyen una Activity **sintética** (`source_system="PATIENT_INITIATED"`) y la alimentan al mismo `HealthBrain`/`Orchestrator` ya construido — literalmente las mismas funciones que usa el camino de demanda inducida y el de recordatorios (verificado con un test que cuenta invocaciones de `HealthBrain._iniciar_reprogramacion` en ambos caminos). `CONSULTAR_CITA`/`CONFIRMAR_CITA` sin conversación previa son deterministas y directas contra `AppointmentService` — no necesitan máquina de estados.

**`patient_confirmation_status`**: campo nuevo (`ConfirmationTracker`, `domains/health/confirmation.py`), separado de `AppointmentStatus` — la agenda sigue siendo la única fuente de verdad del estado real de la cita.

**Corrección encontrada al implementar esta extensión** (no oculta): una Activity sintética recién reservada quedaba "abierta" indefinidamente (su `status` seguía `PENDING`/`IN_PROGRESS`, nunca `accept_activity`d ni `finalize_and_report`d), así que cualquier mensaje posterior del paciente sobre un asunto distinto quedaba atrapado en la conversación ya resuelta. Corregido: `_cerrar_si_definitivo` cierra automáticamente (reutilizando `finalize_and_report`, sin tocarlo) toda Activity `PATIENT_INITIATED` apenas alcanza un desenlace definitivo (reservada/reprogramada/declinada) — nunca se aplica a una Activity de demanda inducida real, que sigue su propio ciclo de vida a través de recordatorios.

Tests: `tests/domains/health/test_bidirectional_gateway.py` (8 tests) + los 63 anteriores = 71/71.

## Integración real: `HrmmAppointmentService` (2026-09-01, misma sesión)

Adaptador que implementa `AppointmentService` (el mismo Protocol de 007, sin modificarlo salvo la extensión aditiva `get_patient_appointments`) contra la API real de **hrmm-backend** (otro proyecto de este ecosistema, en `/Users/enzoalfonso/Orangutan/hrmm/backend`) — verificada leyendo su código fuente real, solo lectura, sin modificar nada de ese proyecto.

**Archivos**: `hrmm_http.py` (capa HTTP, `RealHttpClient` con `urllib` stdlib + `FakeHttpClient` para tests), `hrmm_catalog.py` (`CatalogMirror`, espejo local de servicios/médicos — `HealthBrain` nunca inventa catálogos, siempre consulta este espejo), `hrmm_appointment_service.py` (el adaptador en sí).

**Identidad del paciente**: convención explícita — con `HrmmAppointmentService` activo, `patient_reference` (interno de ZANTIA) ES el documento de identidad real. Camino Activity: `require_document_on_activity` exige `Activity.patient_contact['documento']`, falla claro si falta, nunca lo inventa. Camino PatientRequest: `resolve_patient_identity` usa `GET /citas/buscar-paciente` (público, confirmado sin autenticación leyendo el código — mismo patrón que ya usa el chatbot n8n existente de hrmm).

**Verificación por código — el hallazgo no contemplado en el pedido original**: verificando el código real se encontró que `reprogramar`/`cancelar` exigen, además de nuestra autenticación de canal (`X-Backend-Secret`), un código de 6 dígitos enviado por correo al paciente (`POST /verificacion/enviar`, TTL 10 min, 5 intentos, un solo uso — confirmado en `hrmm-backend/app/recovery_codes.py`). Por eso `cancel_appointment`/`reschedule_appointment` (la firma estándar del Protocol) **siempre lanzan `VerificationRequiredError`** — la ejecución real solo ocurre a través de `cancel_appointment_verified`/`reschedule_appointment_verified`, orquestados por un wizard nuevo y completo en `domains/health/gateway.py` (envía código → pausa el turno → valida → ejecuta), sin tocar `HealthBrain`. Ver decisión D-4 (`docs/decisions/d-4-adaptador-real-hrmm-backend.md`).

**Idempotencia reforzada**: antes de reservar, se verifica vía `get_patient_appointments` si ya existe una cita activa equivalente (mismo paciente/servicio/fecha) — protege específicamente el camino Activity, donde un reintento del sistema IPS podría disparar la misma gestión dos veces con una `idempotency_key` distinta.

**Corrección encontrada al implementar** (no oculta): `Appointment.service` se estaba llenando con el `servicio_id` crudo de hrmm-backend en vez del nombre legible, rompiendo el wizard de reprogramación (que necesita volver a consultar `get_availability(cita.service)`, y esa función espera un NOMBRE, no un ID). Corregido con `CatalogMirror.nombre_por_servicio_id`.

**Estado de las pruebas**: 20 tests nuevos, todos contra `FakeHttpClient` (sin red real, sin secretos reales) — **0 pruebas ejecutadas contra la red real de hrmm-backend en esta sesión**, por decisión explícita del usuario ("todavía no ejecutar pruebas de red real"). Existe un test de integración real (`test_get_availability_contra_hrmm_backend_real`) pero está deshabilitado por defecto.

## Validación real de valores de `estado` (2026-09-01, sesión posterior — recado 010)

HECHO: se hizo una llamada GET real, de solo lectura, sin secreto, contra `GET /api/agenda/disponibilidad` en la producción real de hrmm-backend (`https://curson8n-hrmm-backend.byrp3l.easypanel.host`), sin parámetros. Se confirmaron los **únicos dos valores reales** que toma `BloqueDisponibilidad.estado` sobre 10311 bloques: **`"Libre"`** y **`"Reservado"`** (capitalizados). El filtro de `get_availability` en `hrmm_appointment_service.py` se corrigió de un denylist por substring (INFERENCIA) a un **allowlist explícito** (`estado.lower() == "libre"`) — un valor no contemplado se excluye por defecto, conservador, en vez de ofrecerse por error. Test de control: `test_get_availability_excluye_estado_no_contemplado`.

PENDIENTE (sigue sin poder confirmarse): `Cita.estado` (el mapeo `_MAPA_ESTADO_HRMM`) — es un campo DISTINTO al de `BloqueDisponibilidad`, expuesto únicamente por `GET /api/agenda/citas`, que exige `X-Backend-Secret`. Se intentó sin secreto (por instrucción explícita de no usar el secreto de escritura en esta sesión) y respondió `401 {"detail":"No autorizado."}` — confirma que el endpoint SÍ exige auth, pero no permite ver valores reales de `estado` de citas. `_MAPA_ESTADO_HRMM` sigue siendo INFERENCIA best-effort, sin cambios, hasta que se autorice una llamada con el secreto real.

Observación no solicitada, reportada por transparencia: los IDs vistos en la respuesta siguen el patrón `SLOT-TEST-XXXXX`/`MED-XX`/`SERV-XX`, y `GET /citas/buscar-paciente?documento=TEST-0001` devolvió `{"nombre_paciente":"Paciente Prueba Webhook",...}` — sugiere que este entorno de "producción" contiene datos de prueba/seed claramente etiquetados, no solo reservas reales de pacientes. No cambia la validación (los valores de `estado` son del sistema, no de los datos), pero es relevante para R-7 (no hay staging separado).

**Pendiente, no resuelto en esta fase**:
- ~~Capa de configuración que decida Mock vs. `HrmmAppointmentService` según `HRMM_BACKEND_ENV`~~ — construida en `domains/health/config.py` (recado 011).
- Pruebas de integración reales (escritura) — no existe staging documentado para hrmm-backend (confirmado); no hay `HRMM_BACKEND_SECRET` disponible en esta máquina; falta decidir si se prueba contra producción con datos de prueba marcados, con backup/verificación previos.
- Envío del correo nativo de confirmación de hrmm-backend (`POST /citas/{id}/enviar-confirmacion`) — mecanismo DISTINTO al de verificación (confirmado leyendo el código); coexiste sin cambios, ZANTIA no lo suprime ni lo reemplaza, pero tampoco lo invoca activamente todavía.
- Validar `_MAPA_ESTADO_HRMM` (`Cita.estado`) contra datos reales — requiere el secreto real y autorización explícita para usarlo (ver arriba).
- ~~Brecha de identidad teléfono↔documento~~ — resuelta a nivel de diseño en recado `012`: `domains/health/gateway.py:_gestionar_identificacion` pide el documento al paciente en el primer turno de una conversación por `ChatwootChannel`, lo confirma contra `GET /citas/buscar-paciente`, y asocia el documento real al número de WhatsApp (`_identidad_resuelta`) para el resto de la conversación — con escalamiento tras 3 intentos fallidos. Sigue abierto: (a) nunca probado contra la red real; (b) `buscar-paciente` solo encuentra pacientes con historial previo, un paciente genuinamente nuevo sería rechazado (decisión de producto sin resolver). Ver `.ai/RISKS.md` R-15.

## Gestión "en nombre de otro paciente" (2026-09-01, recado 013)

Extensión de R-15: el titular del canal (ya identificado, recado 012) puede declarar que la gestión es para un beneficiario distinto ("es para mi mamá", "para mi hijo"). `HealthBrain` (`domains/health/brain.py` — **primera vez que se toca en este proyecto**, autorizado explícitamente para esta fase) detecta la frase (`_PARA_OTRO`), pide el documento del beneficiario, lo valida contra `GET /citas/buscar-paciente` (mismo endpoint público de 009), y exige confirmación explícita del nombre real devuelto ANTES de continuar. Solo activo cuando el `AppointmentService` expone `buscar_paciente` (Hrmm) — con `MockAppointmentService` la frase se ignora por completo, cero cambio de comportamiento.

Una vez confirmado, TODO el flujo de reserva (disponibilidad ya era genérica por servicio; la reserva en sí) usa el documento del BENEFICIARIO, nunca el del titular — `Activity.patient_reference` sigue siendo el titular (el "gestor"), solo el parámetro `patient_reference` de la tool `book_appointment` cambia. `agent.py` (también tocado, extensión mínima) registra un evento `GESTION_EN_NOMBRE_DE_BENEFICIARIO` en el `EventLog` del Core con `gestor_documento` y `beneficiario_documento` en campos SEPARADOS, solo cuando hay beneficiario — el caso por defecto no gana ningún evento nuevo. Ver `.ai/DATA_MODEL.md` para la distinción completa titular/gestor/beneficiario.

**Bug real encontrado y corregido durante la implementación**: `HealthBrain.interpret()` lowercasea todo el mensaje al inicio (para el matching de palabras clave) — aplicado sin querer también al DOCUMENTO del beneficiario, corrompiendo documentos con letras. Corregido pasando el mensaje original (sin lowercase) específicamente a la etapa que valida el documento.

**No implementado, declarado PENDIENTE explícitamente** (mejora opcional del pedido, esfuerzo no bajo): recordar la relación titular→beneficiario con una etiqueta (ej. "mamá") entre conversaciones distintas — requeriría una nueva capa de persistencia cruzando conversaciones (el titular puede tener varias Activities en el tiempo) inyectada como dependencia nueva en `HealthBrain`, no solo un dict en memoria de una sola conversación.

**Alcance no cubierto, declarado explícitamente**: reprogramar/cancelar vía el wizard de verificación por código (`gateway.py`, Hrmm) todavía no distingue beneficiario — sigue usando la identidad del titular ya resuelta. Solo el flujo de RESERVA (vía `HealthBrain`) soporta beneficiario en esta fase.

Tests: `tests/domains/health/test_beneficiario_gestion.py` (5 tests) + los 115 anteriores = 120/120 (+ 1 deshabilitado a propósito).

## Identidad de canal persistente entre conversaciones (2026-09-02, recado 014)

Problema que resuelve: hasta aquí (012/013), `HealthGateway._identidad_resuelta` vivía solo en memoria del PROCESO — un paciente ya identificado tenía que repetir su documento en cualquier conversación nueva si el proceso se reiniciaba entretanto. El usuario pidió el patrón ya usado por WhatsApp Banking/Nequi: registrarse una vez, ser reconocido siempre después.

**Store nuevo, no reutilizando `ConversationState`**: `domains/health/identity_store.py:SQLiteIdentidadCanalStore` — tabla `identidad_canal` (`telefono`, `documento`, `estado`, `verificado_en`), a nivel de `HealthGateway` (compartido por todo el proceso, ver `service/app.py`). Deliberadamente NO en el `SQLiteStateStore` de `ConversationState`: se confirmó leyendo `core/agent_contract.py:build_orchestrator` que cada `HealthAgentContext` (uno por Activity/conversación) construye su PROPIO store en `:memory:`, sin conectar `ZANTIA_DB_PATH` — nace y muere con esa conversación, lo opuesto de lo que esta necesidad requiere. Ver decisión D-6 (`docs/decisions/d-6-identidad-canal-persistente.md`).

**Wizard extendido a 3 pasos** (`_gestionar_identificacion`, `gateway.py`): (1) pedir documento — sin cambios de 012; (2) validar contra `buscar-paciente` — sin cambios de 012; (3) **nuevo** — antes de confiar en la asociación, se exige un código de verificación de 6 dígitos por correo (`send_verification_code`, ya construido en 009, reusado sin cambios). Código correcto → `identity_store.marcar_verificado` (única escritura de `estado=VERIFICADO` en todo el archivo) + puebla `_identidad_resuelta` para el resto de la conversación. Código incorrecto → se permite reintentar, sin inventar un contador de intentos propio (se respeta el límite de 5 intentos/TTL 10 min que ya impone `recovery_codes.py` del lado de hrmm-backend).

**Reconocimiento inmediato en un contacto siguiente**: al inicio de `handle_inbound_message`, si el teléfono no está en `_identidad_resuelta` (memoria de este proceso) pero SÍ tiene una fila `VERIFICADO` en `identity_store` (persistente), se hidrata directo — nunca se vuelve a invocar el wizard. Probado explícitamente simulando dos "procesos" (dos `HealthGateway` distintos) contra el mismo archivo SQLite (`tests/domains/health/test_identidad_persistente.py`).

**Hallazgo real durante la implementación, no oculto**: no existe en hrmm-backend ningún endpoint HTTP que confirme un código de verificación de forma independiente de cancelar/reprogramar una cita — `app/recovery_codes.py:verificar_codigo(documento_paciente, codigo)` es genérico, pero solo se invoca dentro de `cancelar_cita`/`reprogramar_cita` (`app/api/agenda.py`), ambos con `cita_id` obligatorio (confirmado leyendo ese código, solo lectura, en `/Users/enzoalfonso/Orangutan/hrmm/backend`). Presentado al usuario, que eligió construir el lado ZANTIA (`HrmmAppointmentService.confirm_verification_code`) contra un contrato PROPUESTO (`POST /api/agenda/verificacion/confirmar`) y coordinar el endpoint real como trabajo aparte en el repositorio de hrmm-backend — ver `.ai/RISKS.md` R-19 (bloqueante para producción real hasta que exista).

**No implementado, declarado PENDIENTE explícitamente**: política de retención/vencimiento de `identidad_canal` — decisión explícita del usuario de no definirla en esta fase (requisito #4 del pedido). Ver `.ai/RISKS.md` R-20 y `.ai/DATA_MODEL.md`.

**Alcance no cubierto**: esta extensión resuelve la identidad del TITULAR del canal — no toca el mecanismo de beneficiario (013), que sigue viviendo por conversación (`ConversationState.datos_recopilados`) y sin persistir entre conversaciones (mejora opcional ya declarada PENDIENTE en 013).

Tests: `tests/domains/health/test_identidad_persistente.py` (9 tests nuevos) + `test_hrmm_appointment_service.py` (+3 tests de `confirm_verification_code`) + `test_identity_gate_chatwoot.py` (reescrito para el wizard de 3 pasos) + los 120 anteriores = 130/130 (+ 1 deshabilitado a propósito).
