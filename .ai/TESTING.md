# TESTING — ZANTIA

> Snapshot de qué se prueba, en qué nivel, y qué falta. No es la suite en sí — es el mapa de cobertura.

| Componente | Framework | Niveles cubiertos | Qué falta |
|---|---|---|---|
| `state/` (modelo, store, máquina) | pytest | Unidad (creación, recuperación, persistencia real en SQLite, concurrencia optimista, transiciones válidas/inválidas) | Migración a un motor distinto de SQLite (si se decide) |
| `guardrails/` | pytest | Unidad (bloqueo, escalamiento, modificación de respuesta) | Reglas adicionales cuando exista un dominio real |
| `tools/` | pytest | Unidad (READ, WRITE, idempotencia, error simulado, NOTIFY) | Tools reales de un dominio (hoy son ficticias) |
| `core/orchestrator.py` | pytest | Integración end-to-end (flujo normal completo, interrupción por riesgo, prioridad riesgo>resto, no reprocesar tras escalado, idempotencia de mensaje) | Reintentos de tool con backoff real; `AnthropicBrain` en vivo |
| `observability/` | pytest | Unidad (eventos de transición y guardrail quedan registrados) | Persistencia de eventos entre procesos (hoy es solo en memoria) |
| `domains/health/` (Activity, gateway, tools, brain) | pytest | Unidad + integración end-to-end (Activity, disponibilidad, reserva/idempotencia, recordatorios 72h/24h/8h, reprogramación, cancelación, no-show, escalamiento, declinación, info no autorizada, ActivityResult/callback idempotente, correlación inbound/outbound, PatientRequest, 3 escenarios e2e completos) | Canal real; `ActivitySource`/`ActivityResultSink` reales (hoy Mock) |
| `domains/health/hrmm_appointment_service.py` (adaptador real) | pytest, contra `FakeHttpClient` (sin red real) | Unidad (traducción de catálogo, disponibilidad con allowlist de `estado` confirmado real, reserva e idempotencia doble, `VerificationRequiredError`, wizard de verificación por código — código inválido y reintento, cancelar y reprogramar verificados, error claro sin secreto configurado, `buscar-paciente` público, `confirm_verification_code` válido/inválido/error inesperado — recado 014) | **Escritura contra red real (booking/reprogramar/cancelar) — deshabilitado a propósito** (`pytest.mark.skipif`, gateado por `ZANTIA_RUN_REAL_HRMM_TESTS`), bloqueado por no tener `HRMM_BACKEND_SECRET` disponible (R-6). `confirm_verification_code` en particular: el endpoint que llama TODAVÍA NO EXISTE en hrmm-backend (R-19) — imposible de probar contra red real hasta que se implemente ahí |
| `domains/health/config.py` (composición Mock/Hrmm) | pytest | Unidad (default mock, mock explícito, production con variables completas — sin red real vía inyección de `FakeHttpClient`, production sin URL/sin secreto falla al arrancar, staging falla explícito, valor desconocido falla explícito) | — |
| `channels/chatwoot_channel.py` (canal real) | pytest, `http_post` inyectado (sin red real) | Unidad (webhook entrante se traduce, eco de saliente se ignora, sin remitente falla explícito, `send` responde a la conversación correcta, sin conversación previa falla, sin token falla) | Conexión a un inbox de Chatwoot real (pendiente, ver `.ai/RISKS.md` R-4) |
| `service/app.py` (transporte HTTP) | pytest (`fastapi.testclient.TestClient`) + verificación manual con `uvicorn` real y `curl` real | `GET /health`, webhook completo de extremo a extremo con `MockAppointmentService`, eco ignorado, fallo al responder no produce 500 (bug real encontrado y corregido con la verificación manual) | Build/run con Docker real (no hay runtime de contenedores en esta máquina, ver R-16) |
| `domains/health/gateway.py` — gate de identidad (R-15) | pytest, contra `FakeHttpClient` (sin red real) | Unidad (mensaje nuevo por `chatwoot` pide documento, documento válido pide código de verificación antes de confiar, código inválido permite reintentar, código válido resuelve identidad/persiste/continúa, documento no encontrado no resuelve identidad, segundo mensaje ya identificado no repregunta, camino Activity outbound no se ve afectado, límite de 3 intentos de documento escala — reescrito en recado 014 para el wizard de 3 pasos) | Prueba end-to-end real con `HRMM_BACKEND_ENV=production` + canal Chatwoot real (sigue en `mock` por defecto, ver `.ai/RISKS.md` R-15) |
| `domains/health/brain.py`/`agent.py` — gestión para beneficiario (R-15, extensión) | pytest, contra `FakeHttpClient` (sin red real) | Unidad (titular gestiona para sí mismo sin cambios, "es para mi mamá" con documento válido usa el documento del beneficiario en la reserva real, documento de beneficiario no encontrado no continúa, EventLog registra gestor/beneficiario por separado, `MockAppointmentService` ignora la frase por completo) | Reprogramar/cancelar con beneficiario (solo cubre reserva); mejora opcional de "recordar relación" (no implementada, ver `.ai/RISKS.md` R-15) |
| `domains/health/identity_store.py` — identidad de canal persistente (R-15, extensión, recado 014) | pytest | Unidad (smoke test del store SQLite, `build_identity_store` lee `ZANTIA_IDENTIDAD_DB_PATH`/cae a `:memory:`/sobrevive un "reinicio" real con archivo), integración con el gateway (contacto siguiente con identidad verificada no pide nada, dos `HealthGateway` distintos comparten identidad vía el mismo archivo SQLite, fila PENDIENTE_VERIFICACION no se reconoce) | Política de retención/expiración (R-20, decisión explícita del usuario de posponerla); prueba end-to-end real contra hrmm-backend (bloqueada por R-19: el endpoint `verificacion/confirmar` no existe todavía ahí) |

130 tests pasando + 1 deshabilitado a propósito (131 recolectados), a 2026-09-02 (`.venv/bin/pytest -q`). Ver los recados en `/Users/enzoalfonso/recado/` (006 a 014) para el detalle de qué reproduce cada test por fase.

## Mínimos obligatorios (heredados de `PROJECT-TEMPLATE`)

- Todo componente nuevo nace con al menos un test de humo (smoke test).
- Todo contrato consumido por más de un componente tiene al menos una prueba de contrato.

Ver `.claude/rules/testing.md` para el detalle completo de las reglas.

## Estrategia mínima viable para ZANTIA

Framework y niveles de cobertura específicos pendientes hasta elegir el stack. Mínimo acordado el 2026-08-31: al menos un smoke test por componente desde el día en que ese componente nace (sin posponerlo) — sin nivel de cobertura adicional impuesto todavía, a decidir según la criticidad real del dominio conversacional.
