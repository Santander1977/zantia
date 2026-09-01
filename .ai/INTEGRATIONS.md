# INTEGRACIONES — ZANTIA

> Sistemas externos que ESTE proyecto consume o con los que se integra (automatización, mensajería, pagos, terceros). Distinto de `.ai/API_CONTRACTS.md` (lo que este proyecto expone).

| Sistema externo | Propósito | Cómo se integra | Quién lo mantiene | Secreto asociado (ver `.ai/SECURITY.md`, sin valores) |
|---|---|---|---|---|
| Mensajería (canal por confirmar: WhatsApp/Telegram/etc.) | Canal conversacional principal del agente | [PROPUESTO — pendiente de definir mecanismo exacto una vez elegido el stack] | [completar] | [completar] |
| hrmm-backend (agenda real, otro proyecto de este ecosistema) | Disponibilidad/reserva/reprogramación/cancelación/consulta de citas reales, y resolución de identidad de paciente (`buscar-paciente`) — reemplaza `MockAppointmentService` cuando está activo | HTTP directo (`domains/health/hrmm_http.py`) contra `HRMM_BACKEND_URL`, con header `X-Backend-Secret`; envía y recibe datos personales reales del paciente (documento de identidad, nombre, teléfono) — ver `.claude/rules/proteccion-datos-personales.md` | Proyecto `hrmm` (fuera de ZANTIA) | `HRMM_BACKEND_SECRET` |

## Notas

Registrado el 2026-08-31 al crear el proyecto: se confirmó que habrá integración de mensajería, pero el canal específico y el mecanismo de integración (API oficial, proveedor tercero, etc.) todavía no se decidieron — completar antes de implementar.

Registrado el 2026-09-01: integración con hrmm-backend construida (`domains/health/hrmm_appointment_service.py`), contrato de endpoints verificado leyendo el código real de `hrmm-backend` (solo lectura, ningún archivo de ese proyecto fue modificado — respeta `.claude/rules/aislamiento-entre-proyectos.md`). Esta integración reenvía datos personales reales (documento, nombre, teléfono) a un sistema externo — su propósito exacto y el mecanismo quedan documentados aquí, tal como exige `.claude/rules/proteccion-datos-personales.md`. Todavía sin probar contra red real (pendiente de confirmación de entorno por el usuario — ver recado de esta fase).
