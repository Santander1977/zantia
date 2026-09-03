# CONTRATOS API — ZANTIA

> Endpoints/contratos que ESTE proyecto expone hacia afuera (lo que otros consumen de él). Para lo que este proyecto consume de sistemas externos, ver `.ai/INTEGRATIONS.md`.

Cada endpoint documentado aquí en el mismo cambio que lo crea o modifica (regla R-API-2, ver `.claude/rules/contratos-api.md`). Ningún endpoint consumido por más de un componente cambia de contrato sin versión nueva o período de compatibilidad documentado (R-API-1).

| Endpoint | Método | Auth | Consumidores conocidos | Versión |
|---|---|---|---|---|
| `/health` | GET | Ninguna (mismo patrón que hrmm-backend) | Chequeo de salud de la plataforma de despliegue (EasyPanel) | Sin versionar — endpoint de infraestructura, no de negocio |
| `/webhook/chatwoot` | POST | Ninguna del lado de ZANTIA (Chatwoot no firma sus webhooks salientes por defecto) — riesgo abierto, ver nota abajo | Instancia de Chatwoot de este ecosistema (inbox de prueba) | Sin versionar — un solo consumidor conocido hoy |

## Notas de versionado

Sin esquema de versión todavía — ningún endpoint de negocio expuesto (solo transporte/webhook). A definir cuando exista un segundo consumidor real de algún endpoint.

## Nota de seguridad — `/webhook/chatwoot` sin autenticación (2026-09-01, recado 011)

Decisión consciente, documentada aquí como exige `.claude/rules/contratos-api.md` (nunca un olvido silencioso): Chatwoot no firma sus webhooks salientes con un secreto compartido por defecto en su configuración estándar. `/webhook/chatwoot` valida la FORMA del payload (`event == "message_created"`, `message_type == "incoming"`) pero no autentica el origen de la petición. Mitigación mínima aplicada: el endpoint solo puede afectar conversaciones ya conocidas por Chatwoot (usa el `conversation.id`/`source_id` que trae el propio payload, no puede leer ni escribir nada fuera de `MockAppointmentService` mientras `HRMM_BACKEND_ENV=mock`). PENDIENTE antes de producción real: restringir por IP de origen de Chatwoot, o activar un secreto de webhook si la versión de Chatwoot del ecosistema lo soporta — no inventado aquí porque no se verificó si esa instancia de Chatwoot lo permite.
