# RECADO PARA CHATGPT

Fecha: 2026-09-01
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: `HrmmAppointmentService` — adaptador real que conecta `domains/health/` con la agenda real de `hrmm-backend`, reemplazando `MockAppointmentService`
Objetivo: Documentar el contrato real verificado (con sus diferencias frente a la especificación original), el hallazgo del requisito de verificación por código, la solución construida, y el resultado de las pruebas — todo sin ejecutar red real ni usar secretos reales, por decisión explícita del usuario en esta fase.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. INFERENCIA = conclusión razonada, marcada explícitamente donde el código fuente no daba una respuesta cerrada (ej. valores exactos de `estado`). RECOMENDACIÓN = propuesta. PENDIENTE = decisión aún no tomada, nunca inventada.

---

## Resumen ejecutivo

HECHO: se construyó `HrmmAppointmentService` (+ `hrmm_http.py`, `hrmm_catalog.py`) implementando el Protocol `AppointmentService` (007/008, sin modificarlo salvo la extensión ya aditiva `get_patient_appointments`) contra la API real de `hrmm-backend`, con el contrato verificado LEYENDO el código fuente real de ese proyecto (solo lectura — ningún archivo de `hrmm` fue modificado, confirmado por hash/mtime al final).

HECHO: la verificación de código encontró una diferencia crítica frente a la especificación original del usuario — `reprogramar`/`cancelar` exigen, además de la autenticación de canal, un **código de verificación de 6 dígitos** enviado al correo del paciente. Esto no estaba contemplado en el pedido inicial y se resolvió con un nuevo wizard determinista en `domains/health/gateway.py`, sin tocar `HealthBrain` (decisión D-4).

HECHO: **91/91 tests pasando + 1 deshabilitado a propósito** (92 recolectados) — 20 tests nuevos de esta fase, todos contra `FakeHttpClient` (sin red real). **Cero llamadas a la red real de hrmm-backend en esta sesión**, por decisión explícita del usuario.

## Contrato real verificado (diferencias frente a lo que el usuario describió originalmente)

| Endpoint | Tal como lo describió el usuario | Confirmado en el código real |
|---|---|---|
| `GET /api/agenda/disponibilidad` | — | Igual — público, filtra por `medico_id`/`fecha`, NO por servicio |
| `POST /api/agenda/citas` | — | Igual — público (rate-limited), body con `slot_id`, `documento_paciente`, `nombre_paciente`, `telefono` |
| `POST /api/agenda/citas/{id}/reprogramar` | Implícitamente un body JSON | **Diferente**: query params obligatorios `nuevo_slot_id`, `documento_paciente`, **`codigo`** — este último no estaba en la especificación |
| `POST /api/agenda/citas/{id}/cancelar` | Implícitamente un body JSON | **Diferente**: query params obligatorios `documento_paciente`, **`codigo`** |
| `GET /api/agenda/citas/buscar-paciente` | Público, sin auth | Confirmado — público, devuelve SOLO `{nombre_paciente, telefono}` |
| Header de autenticación | `BACKEND_TRUSTED_SECRET` (nombre de variable) | Confirmado: el HEADER se llama `X-Backend-Secret`; `BACKEND_TRUSTED_SECRET` es el nombre de la variable de entorno del LADO de hrmm-backend |
| `POST /api/agenda/verificacion/enviar` | No mencionado originalmente | **Nuevo, encontrado en la investigación**: body `{documento_paciente}`, requiere auth de canal, envía código de 6 dígitos por CORREO (vía webhook n8n — no SMS ni WhatsApp), TTL 10 min, máx. 5 intentos, un solo uso |
| `POST /api/agenda/citas/{id}/enviar-confirmacion` | No mencionado | Mecanismo DISTINTO (reenvía el correo de confirmación general, no requiere código) — usado por `portal-citas`, no relevante para el wizard de verificación |

**Staging**: HECHO — no existe un entorno de staging documentado para hrmm-backend; un único entorno de producción real (EasyPanel). Confirmado leyendo `docs/progreso.md` de ese proyecto.

**Secretos detectados** (no leídos, solo por listado de directorio, tal como exige la regla de este ecosistema): `POSIBLE SECRETO DETECTADO EN: /Users/enzoalfonso/Orangutan/hrmm/backend/.env` y `.env.bak_pre_rotation` — ambos gitignored en su propio proyecto, ya conocidos por el usuario (es de donde copiará el valor real).

## Decisión de identidad del paciente

HECHO (convención de diseño, documentada en el código): con `HrmmAppointmentService` activo, `patient_reference` (concepto interno de ZANTIA, ya usado en todo 007/008) **es** el documento de identidad real del paciente. Dos caminos de resolución:

1. **Activity (outbound)**: `require_document_on_activity` exige `Activity.patient_contact['documento']` — falla de forma clara y explícita si falta, nunca lo inventa (`gateway.py`).
2. **PatientRequest (inbound)**: `resolve_patient_identity` usa `GET /citas/buscar-paciente` (público, sin autenticación — mismo patrón que ya usa, según la investigación, el chatbot n8n existente de hrmm) para confirmar identidad antes de continuar.

## El hallazgo: verificación por código obligatoria

HECHO — investigado en dos rondas (dos agentes de solo lectura, cero escritura):

- Canal: **correo electrónico**, nunca SMS/WhatsApp — enviado por hrmm-backend vía un webhook de n8n (`N8N_WEBHOOK_CODIGO_URL`), no directo a un proveedor de correo.
- Código: 6 dígitos, TTL 600s (10 minutos), máximo 5 intentos, un solo uso (`app/recovery_codes.py`, confirmado).
- Nadie en el ecosistema (ni `portal-citas` ni `hrmm-panel-operador`) llama hoy a `verificacion/enviar` — solo lo usaba el chatbot n8n `orquestador_citas`, que es exactamente lo que ZANTIA está reemplazando/extendiendo para este dominio.
- Es un mecanismo DISTINTO del código de "check-in de digiturno" (`checkin_codigo.py`) — nombres similares, propósitos no relacionados.

**Solución implementada** (opción elegida por el usuario, tras pedir detalle del mecanismo antes de decidir): un nuevo sub-flujo COMPLETO en `domains/health/gateway.py`, independiente de `ConversationState`/`Orchestrator`/`HealthBrain`:

```
"cancelar mi cita" / "reprogramar mi cita"
   │
   ▼ (solo si AppointmentService.requires_verification_code == True)
[reprogramar] ofrece nuevas opciones (determinista, sin Brain) → paciente elige
   │
   ▼
send_verification_code(documento) → "te enviamos un código a tu correo (a***@x.com)"
   │
   ▼ (siguiente mensaje del paciente = intento de código, SIEMPRE interceptado
   │  antes que cualquier otra clasificación — ver handle_inbound_message)
código correcto → cancel/reschedule_appointment_verified() → ejecuta la acción REAL
código incorrecto → "no es válido o venció" → permite reintentar, NO pierde el estado pendiente
```

`MockAppointmentService` (007/008, sin tocar) no declara `requires_verification_code`, así que ese camino de la gestión de citas sigue exactamente igual que antes — verificado con un test de control explícito.

## Otros problemas resueltos

- **Catálogo**: `CatalogMirror` (nuevo) sincroniza `servicios`/`medicos` bajo demanda — `get_availability` no acepta filtro de servicio en la API real, así que se resuelve `nombre → servicio_id` localmente y se filtra client-side; `medico_id → nombre/consultorio` también viene del espejo, porque la respuesta de disponibilidad no trae esos datos directamente.
- **Idempotencia reforzada**: antes de reservar, se consulta si ya existe una cita activa equivalente (mismo paciente/servicio/fecha) — protege el camino Activity contra un reintento del sistema IPS con una `idempotency_key` distinta.
- **`nombre_paciente`/`telefono` en la reserva**: el Protocol `book_appointment` no los lleva explícitos — se resuelven vía `register_patient_contact` (método propio, fuera del Protocol), poblado por el gateway tras identidad resuelta.

## Corrección encontrada al implementar (no oculta)

`Appointment.service` se llenaba con el `servicio_id` crudo de hrmm-backend en vez del nombre legible — rompía el wizard de reprogramación, que necesita volver a llamar `get_availability(cita.service)` esperando un NOMBRE, no un ID. Corregido con `CatalogMirror.nombre_por_servicio_id`, encontrado probando manualmente el flujo antes de escribir los tests formales.

## Tests

TESTS EJECUTADOS: 92 recolectados
TESTS PASANDO: 91
TESTS DESHABILITADOS A PROPÓSITO: 1 (`test_get_availability_contra_hrmm_backend_real`, gateado por `ZANTIA_RUN_REAL_HRMM_TESTS`, nunca activo por defecto)
TESTS FALLANDO: 0

Cubren: traducción de catálogo, disponibilidad (excluye bloques ocupados — INFERENCIA sobre valores de `estado`, ver abajo), reserva exitosa, idempotencia por clave, no-duplicación por cita activa equivalente, `cancel`/`reschedule_appointment` directos lanzan `VerificationRequiredError` siempre, envío de código, código inválido no ejecuta la acción y permite reintentar, código correcto ejecuta la acción real (Fake), `buscar-paciente` público incluso sin secreto configurado, error claro si falta el secreto, wizard completo de cancelación y de reprogramación de extremo a extremo, y control explícito de que `MockAppointmentService` sigue sin pedir código.

## INFERENCIA declarada (no verificada contra datos reales)

El campo `estado` de `Cita`/`BloqueDisponibilidad` está tipado como `str` libre en el código de hrmm-backend, sin enum documentado. El mapeo `_MAPA_ESTADO_HRMM` (hrmm-backend → `AppointmentStatus`) y el filtro de "bloques ocupados" en `get_availability` son mejores esfuerzos razonables (términos en español más probables), **no confirmados contra respuestas reales** — marcados explícitamente como INFERENCIA en el código y en `docs/health-demand-agent.md`. PENDIENTE DE VALIDACIÓN antes de confiar en ellos para lógica crítica en producción.

## Pendiente (no resuelto aquí, ni inventado)

- Capa de configuración que decida Mock vs. `HrmmAppointmentService` según `HRMM_BACKEND_ENV` — no construida en esta fase.
- Pruebas de integración con red real — explícitamente diferidas. No hay staging; falta decidir si se prueba contra producción con datos de prueba marcados (con backup/verificación previos) o se espera a un entorno de staging.
- Validar contra datos reales el mapeo de valores de `estado` (marcado INFERENCIA arriba).
- Envío del correo nativo de confirmación de hrmm-backend (`enviar-confirmacion`) — coexiste sin cambios, ZANTIA no lo suprime, pero tampoco lo invoca todavía.
- Canal real de mensajería para ZANTIA (sigue sin decidir, heredado de fases anteriores).
