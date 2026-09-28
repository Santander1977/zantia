# RECADO PARA CHATGPT

Fecha: 2026-09-01
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Construcción del primer agente de dominio real sobre el Core existente — Agente de Demanda Inducida y Gestión de Atención en salud (`domains/health/`)
Objetivo: Documentar arquitectura construida, archivos, contratos, flujo, tests, resultados verificados, limitaciones, decisiones, problemas encontrados y potencial pedagógico — solo lo REALMENTE implementado y probado en esta sesión.

Este documento es autocontenido. Se apoya en `002` a `006` (históricos, no modificados en esta sesión) y en `docs/health-demand-agent.md` del propio proyecto (documentación técnica operativa, no pedagógica — ver la sección "Potencial de formación" al final de este recado para esa distinción).

Convenciones: **HECHO** = verificado ejecutando algo en esta sesión (tests corridos con `.venv/bin/pytest`, scripts manuales ejecutados). **INFERENCIA** = conclusión razonada. **RECOMENDACIÓN** = propuesta. **PENDIENTE** = decisión aún no tomada.

---

## Resumen ejecutivo

HECHO: se construyó `domains/health/` — el primer agente de dominio real de ZANTIA — **sobre** el Core existente (documentado en `006-construccion-zantia.md`), sin reemplazarlo. Implementa el flujo completo de demanda inducida pedido: `Activity` con tres capas de estado separadas, `AppointmentService`/`ActivitySource`/`ActivityResultSink` (Mock, con contrato listo para reemplazo real), `ReminderManager` con programación determinista, `HealthBrain`, y 5 tools de dominio.

HECHO: **63/63 tests pasando** (`.venv/bin/pytest -q`: 34 del Core + 29 nuevos del dominio salud), incluidos los dos escenarios end-to-end pedidos explícitamente (camino feliz completo con 3 recordatorios simulados, y camino de reprogramación).

HECHO: se encontraron y corrigieron **2 defectos reales del Core** al construir este dominio (detallados abajo) — no se ocultan, son parte de este recado.

No se modificó Dani, `PROJECT-TEMPLATE`, `orangutan-kit` ni los recados históricos 001-006 (verificado con hashes/mtimes).

---

## Arquitectura construida

```
IPS (sistema originador)
   │  create Activity
   ▼
ActivitySource (MockActivitySource) ── domains/health/activity_source.py
   │
   ▼
domains/health/agent.py  ── capa de orquestación de DOMINIO (el "pegamento")
   │  única capa con autoridad para escribir Activity.status/management_status
   │
   ├── core.Orchestrator (Core — sin reemplazar)
   │      ├── HealthBrain           domains/health/brain.py
   │      ├── ConversationState     state/ (Core, sin tocar el modelo)
   │      ├── GuardrailEngine       guardrails/ (Core, mismas 3 reglas)
   │      └── ToolRegistry          domains/health/tools.py (5 tools de dominio)
   │
   ├── AppointmentService (MockAppointmentService)  domains/health/appointment_service.py
   ├── ReminderManager                                domains/health/reminder_manager.py
   └── ActivityResultSink (MockActivityResultSink)   domains/health/result_sink.py
                                                          │
                                                          ▼
                                                    IPS (ActivityResult)
```

## Tres capas de estado (decisión D-3, documentada en `docs/decisions/d-3-tres-capas-de-estado-dominio-salud.md`)

1. **`ConversationState.fase_actual`** (Core, sin cambios de modelo) — micro-estado de un turno.
2. **`Activity.status`** — ciclo de vida grueso: `PENDING -> ACCEPTED/IN_PROGRESS -> COMPLETED/FAILED/CANCELLED/EXPIRED`.
3. **`Activity.management_status`** — progreso granular: `NOT_CONTACTED -> CONTACTING -> CONTACTED -> ENGAGED -> APPOINTMENT_PENDING -> APPOINTMENT_CONFIRMED -> REMINDER_72H/24H/8H -> ATTENDED/NO_SHOW/RESCHEDULE_REQUESTED/RESCHEDULED/DECLINED/ESCALATED`.

Ninguna capa se infiere de otra; solo `domains/health/agent.py` escribe las capas 2 y 3.

## Archivos creados

| Archivo | Contenido |
|---|---|
| `domains/health/models.py` | `Activity`, `Appointment`, `Reminder`, `ActivityResult` (pydantic) + enums de las 3 capas de estado |
| `domains/health/activity_source.py` | `ActivitySource` (Protocol) + `MockActivitySource` (idempotente por `activity_id`) |
| `domains/health/appointment_service.py` | `AppointmentService` (Protocol) + `MockAppointmentService` (disponibilidad ficticia pero DINÁMICA) |
| `domains/health/reminder_manager.py` | `ReminderManager` — programación determinista (aritmética de fechas, no LLM) |
| `domains/health/result_sink.py` | `ActivityResultSink` (Protocol) + `MockActivityResultSink` (idempotente) |
| `domains/health/brain.py` | `HealthBrain` — Brain de dominio, keyword-based, con proveedor perezoso de la Activity |
| `domains/health/tools.py` | 5 tools: `get_availability` (READ), `book/reschedule/cancel_appointment` (WRITE), `record_activity_result` (NOTIFY) |
| `domains/health/agent.py` | Orquestación de dominio: `build_health_agent_context`, `contact_patient`, `handle_patient_message`, `fire_reminder`, `handle_reminder_response`, `handle_no_show`, `handle_attended`, `finalize_and_report` |
| `channels/mock_channel.py` | `MockChannel` — implementa el `Channel` genérico del Core (sección 30) |
| `docs/health-demand-agent.md` | Documentación técnica operativa completa (arquitectura, entidades, flujo, integraciones, limitaciones) |
| `docs/decisions/d-3-*.md` | Decisión formal de las 3 capas de estado |
| `tests/domains/health/*.py` | 29 tests (8 archivos) |

## Contratos (Mock -> Real, sin tocar el Brain — sección 39)

| Interfaz | Mock actual | Futuro real |
|---|---|---|
| `ActivitySource` | En memoria | `POST /activities` |
| `AppointmentService` | En memoria, dinámica | API real de agenda |
| `ActivityResultSink` | En memoria | `POST /activity-results` |
| `Channel` (Core) | `MockChannel` | WhatsApp / Web / Voz / SMS |

## Flujo conversacional (verificado con tests)

```
CONTACTAR (plantilla determinista)
   ↓
DECISIÓN del paciente:
   ACEPTA → disponibilidad → opciones → selección → reserva → confirmación
   NO ACEPTA → DECLINED
   NO PUEDE AHORA → finaliza sin decisión
   SOLICITA HUMANO → ESCALATED (vía escalación del Core, nunca promete contacto)
   PIDE INFO NO AUTORIZADA → indica limitación, no inventa

Tras cita confirmada (en cualquier momento posterior, incluida respuesta a recordatorio):
   "no puedo asistir" → reprogramación (cancela recordatorios viejos, crea nuevos)
   "cancelar" → Activity.status = CANCELLED
   "confirmo" → management_status vuelve a APPOINTMENT_CONFIRMED
```

## Correcciones encontradas al implementar (no ocultas)

1. **`core/orchestrator.py`**: no distinguía entre "la tool lanzó una excepción" y "la tool respondió pero con `success=False`" — en el segundo caso, el texto optimista que el Brain había propuesto ANTES de conocer el resultado se enviaba igual, pudiendo declarar una acción exitosa que no lo fue. Corregido: ahora, si `ToolResult.success is False`, la respuesta se sustituye por un mensaje que no afirma éxito (cumple sección 14 explícitamente). También se corrigió que un error irrecuperable de tool ahora transiciona formalmente el estado a `ESCALADO_ESTANDAR` (antes solo lo declaraba en la respuesta sin persistir la transición — la conversación quedaba en un estado inconsistente para mensajes futuros).
2. **`state/machine.py`**: faltaban las transiciones `RECOPILACION_DE_DATOS -> RESPUESTA` e `IDENTIFICACION_DE_INTENCION -> RESPUESTA` — necesarias porque, dentro de UN turno síncrono, "razonar + ejecutar una tool" puede completarse sin pasar por una parada de fase intermedia persistida (aunque sí queda registrado como evento de observabilidad).
3. **`HealthBrain` — bug de diseño propio, corregido antes de llegar a los tests formales**: el constructor inicial recibía la `Activity` por valor; como es un modelo pydantic inmutable, cada actualización de dominio crea una copia nueva, así que el Brain quedaba congelado con la primera versión para siempre (nunca veía `appointment_id` tras reservar, rompiendo la detección de reprogramación/cancelación). Corregido con un proveedor perezoso (`lambda: context.activity`).
4. **Sincronización de `management_status` — bug de diseño propio, corregido antes de los tests formales**: comprobar solo "¿existe la clave en `resultado_de_herramientas`?" fallaba porque ese diccionario es acumulativo entre turnos (004, sección 2.1) — tras una reprogramación, el resultado de la reserva ORIGINAL seguía "ganando". Corregido usando la etapa **actual** del turno + un marcador "de un solo disparo" que se consume tras usarse.

## Tests (todos ejecutados y pasando en esta sesión)

TESTS EJECUTADOS: 63
TESTS PASANDO: 63
TESTS FALLANDO: 0

Desglose del dominio salud (29): creación/idempotencia/validación de Activity (3), ciclo de vida y aceptación (2), contacto determinista (1), consulta y estructura de disponibilidad (2), selección y confirmación de reserva (1), tool READ directa (1), fallo de reserva sin declarar éxito falso (2), idempotencia de reserva (1), 72h/24h/8h programados y su orden (1), envío determinista de cada recordatorio (2), recordatorio no se reenvía dos veces (1), respuesta a recordatorio confirma asistencia (1), reprogramación completa (1), cancelación de recordatorios tras reprogramar (1), cancelación de cita (1), declinación (1), escalamiento sin prometer contacto (1), información no autorizada no inventada (1), no-show sin crear cita nueva (1), `ActivityResult` reportado tras reserva (1), callback idempotente (2), **2 escenarios end-to-end completos** (camino feliz de la sección 37 del prompt, y camino de reprogramación).

## Limitaciones conocidas (declaradas, no resueltas)

- Sin canal real conectado (`MockChannel` demuestra el contrato).
- Protocolo de riesgo/urgencia real: sigue **PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL** — se reutiliza el mecanismo genérico no-clínico del Core (`core/brain.py:RISK_KEYWORDS_DEMO`), nunca un criterio médico.
- `ReminderManager`/`EventLog` en memoria de proceso — sin scheduler real que dispare recordatorios por sí solo a su hora (`fire_reminder` se invoca explícitamente en este MVP, simulando el paso del tiempo).
- `MockAppointmentService` no modela solapamiento de turnos ni reglas de negocio reales de una IPS — deliberadamente simple (prompt, sección 38).
- `AnthropicBrain` (Core) sigue sin probarse en vivo; `HealthBrain` es determinista por palabras clave, no NLU real.

## Decisiones

- **D-3** (nueva, IMPLEMENTADA): tres capas de estado separadas — ver `docs/decisions/d-3-tres-capas-de-estado-dominio-salud.md`.
- Consentimiento de datos del paciente: se asume otorgado por el sistema originador al momento de incluir al paciente en el programa (fuera de este canal conversacional) — se registra explícitamente en el `ConversationState` al iniciar el contacto (`domains/health/agent.py:contact_patient`), nunca implícitamente en un guardrail.

## Problemas encontrados

Ninguno bloqueante fuera de las 4 correcciones ya documentadas arriba, todas resueltas en la misma sesión con tests que las cubren.

## Preguntas pendientes / decisiones futuras

- ¿Cuál es el primer sistema real de agenda a integrar (reemplazo de `MockAppointmentService`)?
- ¿Qué mecanismo de scheduling real disparará los recordatorios (cron, cola, worker)?
- ¿Qué canal real se conecta primero (WhatsApp es lo más probable dado el precedente de Dani, pero no se asume)?
- El protocolo clínico de riesgo/urgencia sigue requiriendo validación humana antes de cualquier uso con pacientes reales — no se puede avanzar a producción sin resolver esto.

---

## Potencial de formación

(Continuación del protocolo adoptado en `005` — separar documentación técnica de pedagógica, ver memoria `documentacion_pedagogica_zantia.md`.)

Esta fase, al ser la primera con un dominio real completo funcionando, deja material pedagógico más concreto que las fases anteriores:

- **Caso de estudio**: los 2 tests end-to-end (`tests/domains/health/test_end_to_end.py`) son un caso de estudio completo y verificable de "diseño en papel (prompt 007) → código real corriendo" — material directo para una clase.
- **Clase**: "Por qué separar el lifecycle de una unidad de trabajo de su progreso de gestión" — usando la decisión D-3 como ejemplo concreto con código real a ambos lados.
- **Laboratorio**: "Diseña un segundo dominio (`sales` o `citizen`) siguiendo el mismo patrón de 3 capas" — usando `domains/health/` completo como plantilla de referencia.
- **Error frecuente documentado** (con solución real): las 2 correcciones del Core + las 2 propias del dominio son ejemplos concretos y ya resueltos de errores comunes en sistemas con estado (inmutabilidad mal manejada, diccionarios acumulativos mal chequeados, éxito declarado sin verificación) — material de "qué NO hacer" con solución verificada, no solo teoría.
- **Checklist**: la lista de "Limitaciones conocidas" de este recado es, en sí misma, un checklist reutilizable de "qué preguntar antes de llevar un MVP de este tipo a producción".
- **Hueco todavío real** (no inventar contenido): sigue sin existir material de evaluación derivable; el protocolo clínico real (el corazón de la seguridad del dominio salud) sigue sin poder documentarse pedagógicamente porque todavía no existe — no se puede enseñar lo que aún no se ha decidido con criterio humano/clínico.
