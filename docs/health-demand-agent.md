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
