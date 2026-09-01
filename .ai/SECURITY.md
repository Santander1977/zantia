# SEGURIDAD — ZANTIA

> Mecanismos de autenticación existentes + inventario de secretos. NUNCA se escribe un valor real de secreto en este archivo — solo nombre, propósito y dónde vive.

## Mecanismos de autenticación

| Mecanismo | Protege qué | Usado por |
|---|---|---|
| Header `X-Backend-Secret` (valor = secreto compartido, confirmado leyendo `hrmm-backend/app/trusted_auth.py`) | Endpoints de escritura/lectura sensible de la API de agenda de hrmm-backend (`GET/POST /api/agenda/citas*`, `POST /api/agenda/verificacion/enviar`) | `domains/health/hrmm_appointment_service.py:HrmmAppointmentService` |
| Código de verificación de 6 dígitos por correo (TTL 10 min, máx. 5 intentos, un solo uso — confirmado leyendo `hrmm-backend/app/recovery_codes.py`) | Segundo factor de identidad del PACIENTE antes de reprogramar/cancelar una cita real (independiente del header anterior) | `domains/health/gateway.py`, sub-flujo de verificación |

## Inventario de secretos (sin valores)

| Nombre de variable | Propósito | Dónde vive (plataforma) | Quién la usa |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Activar `core/brain.py:AnthropicBrain` (no usado por defecto — Core corre con `FakeBrain`) | A configurar por el usuario, ver `.env.example` | `core/brain.py` |
| `HRMM_BACKEND_SECRET` | Autenticar a ZANTIA como canal de confianza ante hrmm-backend (mismo valor que `BACKEND_TRUSTED_SECRET` del lado de hrmm-backend — nombres de variable distintos a propósito, mismo secreto compartido) | El usuario copia el valor real directamente desde EasyPanel a ambos lados — nunca se pasa por chat ni se hardcodea | `domains/health/hrmm_appointment_service.py:HrmmAppointmentService` |
| `HRMM_BACKEND_URL` | URL base de la API de agenda real de hrmm-backend | A configurar por el usuario, ver `.env.example` | `domains/health/hrmm_http.py:RealHttpClient` (instanciado por quien conecte `HrmmAppointmentService`) |
| `HRMM_BACKEND_ENV` | Distingue `staging`/`production` — nunca apunta a producción por defecto | A configurar por el usuario, ver `.env.example` | Capa de configuración que instancia `HrmmAppointmentService` (aún no construida — ver `.ai/CURRENT_STATE.md`) |

## Notas de auditoría de seguridad

- **Integración hrmm-backend (2026-09-01)**: `HrmmAppointmentService` es un adaptador que llama a la API real de otro proyecto de este ecosistema (`hrmm-backend`). Su contrato se verificó leyendo el código fuente real (solo lectura, sin modificar `hrmm-backend`) — ver `/Users/enzoalfonso/recado/` (recado de esta fase) para el detalle exacto de endpoints, parámetros y hallazgos.
- Ningún test de esta fase ejecuta contra la red real ni usa un secreto real — toda la suite (`tests/domains/health/test_hrmm_*.py`) corre contra `FakeHttpClient` (sin red) con un valor de secreto ficticio (`"secreto-de-prueba-no-real"`). El test de red real (`test_get_availability_contra_hrmm_backend_real`) existe pero está deshabilitado por defecto (`pytest.mark.skipif`), a la espera de que el usuario confirme entorno/credenciales.
- Reprogramar/cancelar una cita real EXIGE el código de verificación del paciente además del secreto de canal — `HrmmAppointmentService.cancel_appointment`/`reschedule_appointment` (la firma estándar del Protocol, sin documento/código) lanzan `VerificationRequiredError` deliberadamente, nunca ejecutan la acción real sin verificación completa.
- No se encontraron endpoints sensibles de hrmm-backend sin gate de auth explícito — `GET /api/agenda/citas/buscar-paciente` es intencionalmente público (confirmado por comentario en el propio código fuente de hrmm-backend, que documenta que gatearlo por error rompió producción una vez), y devuelve deliberadamente el mínimo dato posible (`nombre_paciente`, `telefono` — nunca la lista de citas).
