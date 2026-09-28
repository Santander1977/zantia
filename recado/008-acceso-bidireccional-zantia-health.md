# RECADO PARA CHATGPT

Fecha: 2026-09-01
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Evolución de `domains/health/` de "Agente de Demanda Inducida" (007) a "Agente de Acceso y Gestión de Atención" bidireccional
Objetivo: Documentar el mecanismo de correlación inbound/outbound (el vacío real que el diseño de 007 no cubría), qué se construyó, y el resultado de los tests — todo sobre el Core y el dominio ya existentes, sin reemplazar nada.

Nota de numeración: esta extensión se pidió inicialmente documentar como "recado 009"; en un mensaje posterior el propio usuario la referenció como "008" (junto a "007... 63/63 tests + las extensiones de bidireccionalidad"). Se usa aquí **008** por ser la numeración secuencial correcta (008 no existía) y la más reciente indicada — sin renumerar ningún archivo ya existente.

Convenciones: HECHO = verificado ejecutando algo en esta sesión. INFERENCIA = conclusión razonada. RECOMENDACIÓN = propuesta. PENDIENTE = decisión aún no tomada.

---

## Resumen ejecutivo

HECHO: se construyó `domains/health/gateway.py` (+ 3 archivos nuevos de apoyo: `patient_request_source.py`, `confirmation.py`, `intent.py`) que añade un camino **inbound** al dominio salud, con un mecanismo de **correlación** explícito — sin tocar `Activity`, `HealthBrain`, `AppointmentService`/`MockAppointmentService` (salvo una extensión aditiva), `ReminderManager`, `ActivityResultSink`, `MockChannel` ni las funciones ya existentes de `agent.py`.

HECHO: **71/71 tests pasando** (63 de 007 + 8 nuevos).

HECHO: se encontró y corrigió un defecto real durante la implementación (no oculto): una Activity sintética recién reservada quedaba "abierta" indefinidamente en el registro de correlación.

## Mecanismo de correlación (el vacío que el documento fuente no especificaba)

`HealthGateway._open_conversations: Dict[patient_reference, conversation_id]` + `HealthGateway._contexts: Dict[conversation_id, HealthAgentContext]`. En cada mensaje inbound:

1. `find_open_context(gateway, patient_reference)` — busca la entrada, y verifica FRESCURA en el momento (`Activity.status not in {COMPLETED, FAILED, CANCELLED, EXPIRED}`), no por un "cierre" que alguien deba recordar llamar en cada punto de salida.
2. Si existe y está fresca → se enruta con `handle_patient_message` (Core, sin tocar) — nunca se crea una `PatientRequest`.
3. Si no existe → se clasifica la intención (`intent.py`, determinista, independiente de `HealthBrain`) → se crea una `PatientRequest` → se construye una Activity **sintética** (`source_system="PATIENT_INITIATED"`) que alimenta al mismo motor conversacional ya construido.

## Reutilización verificada, no duplicada

`PROGRAMAR_CITA`/`REPROGRAMAR_CITA`/`CANCELAR_CITA` inbound construyen una Activity sintética y llaman a `build_health_agent_context`/`handle_patient_message` (007, sin tocar) — el mismo código que usa la demanda inducida y los recordatorios. Verificado explícitamente con un test que parchea `HealthBrain._iniciar_reprogramacion` (`unittest.mock.patch.object` con `side_effect` = el método original) y cuenta invocaciones en ambos caminos (respuesta a recordatorio vía `handle_reminder_response`, y solicitud inbound fresca vía `gateway.handle_inbound_message`) — mismo método, mismo `call_count` acumulado, no una reimplementación paralela.

`CONSULTAR_CITA`/`CONFIRMAR_CITA` sin conversación previa son deterministas y directas contra `AppointmentService.get_patient_appointments` (nueva capacidad aditiva) — no pasan por `HealthBrain`, no hace falta máquina de estados para una lectura pura.

## `patient_confirmation_status` — campo separado, verificado

`ConfirmationTracker` (nuevo, `domains/health/confirmation.py`) guarda `patient_confirmation_status` por `appointment_id`, en un almacén propio — nunca lee ni escribe `AppointmentStatus`. Test explícito: tras `CONFIRMAR_CITA`, `AppointmentStatus` de la cita permanece exactamente igual, mientras `ConfirmationTracker` pasa de `SIN_CONFIRMAR` a `CONFIRMADO`.

## Corrección encontrada al implementar (no oculta)

Una Activity sintética recién reservada quedaba con `status` en `PENDING`/`IN_PROGRESS` indefinidamente (nunca pasaba por `accept_activity` ni `finalize_and_report`), así que `find_open_context` la seguía considerando "abierta" para siempre — cualquier mensaje posterior del paciente sobre un asunto totalmente distinto (p. ej. "¿cuándo es mi cita?" tras ya haber reservado) quedaba atrapado respondiendo dentro de la conversación de reserva ya resuelta, en vez de reclasificarse. Corregido con `_cerrar_si_definitivo`: cierra automáticamente (reutilizando `finalize_and_report`, sin tocarlo) toda Activity `PATIENT_INITIATED` apenas su `management_status` alcanza un desenlace definitivo (`APPOINTMENT_CONFIRMED`/`RESCHEDULED`/`DECLINED`) — gateado explícitamente por `source_system == "PATIENT_INITIATED"`, así que **nunca se aplica a una Activity de demanda inducida real**, que debe seguir abierta a través de sus propios recordatorios de varios días.

## Archivos

| Archivo | Contenido |
|---|---|
| `domains/health/models.py` (extendido) | `PatientRequest`, `RequestIntent`, `RequestStatus`, `PatientConfirmationStatus` — añadidos al final, sin tocar las clases existentes |
| `domains/health/patient_request_source.py` (nuevo) | `PatientRequestSource` + `MockPatientRequestSource` |
| `domains/health/confirmation.py` (nuevo) | `ConfirmationTracker` |
| `domains/health/intent.py` (nuevo) | `classify_intent` |
| `domains/health/gateway.py` (nuevo) | `HealthGateway`, correlación, enrutamiento inbound |
| `domains/health/appointment_service.py` (extendido) | `get_patient_appointments` añadido a `AppointmentService` (Protocol) y `MockAppointmentService` |
| `tests/domains/health/test_bidirectional_gateway.py` (nuevo) | 8 tests |
| `docs/health-demand-agent.md` (actualizado) | Sección "Extensión: acceso bidireccional" añadida |

## Qué quedó con flujo completo vs. solo contrato

- **Flujo completo**: `PROGRAMAR_CITA`, `REPROGRAMAR_CITA`, `CANCELAR_CITA`, `CONSULTAR_CITA`, `CONFIRMAR_CITA`.
- **Contrato mínimo/determinista, sin flujo conversacional propio** (el propio pedido permitía esto — "no todas requieren un flujo completo nuevo"): `ESCALAMIENTO` (ack fijo + `PatientRequest.status = ESCALADA`), `INFORMACION_SERVICIO` (ack genérico fijo). `DEMANDA_INDUCIDA` existe en el catálogo por completitud simétrica con `Activity.activity_type`, pero no es alcanzable como clasificación de un mensaje inbound (por definición, la demanda inducida siempre la inicia la IPS, nunca el paciente) — mensajes no reconocidos se clasifican por defecto como `PROGRAMAR_CITA` (la opción más segura: ofrece ayuda en vez de asumir que ya existe una cita que gestionar).

## Resultado de tests

TESTS EJECUTADOS: 71 (63 + 8 nuevos)
TESTS PASANDO: 71
TESTS FALLANDO: 0

## Pendiente (no resuelto aquí, ni inventado)

- Canal real (`WhatsApp`) — sigue sin conectar (`MockChannel`).
- `AppointmentService` real (hrmm-backend) — sigue Mock; **trabajo en curso aparte**, ver mensaje del usuario recibido a continuación de este mismo recado.
- Protocolo clínico de riesgo/urgencia real — sigue PENDIENTE DE VALIDACIÓN CLÍNICA/LEGAL (heredado de 003/004).
