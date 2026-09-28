# RECADO PARA CHATGPT

Fecha: 2026-09-02
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Identidad de canal PERSISTENTE entre conversaciones (extensión de R-15) — un paciente ya identificado por WhatsApp deja de tener que repetir su documento cada vez que abre una conversación nueva
Objetivo de la investigación: Confirmar si hrmm-backend expone un mecanismo para verificar un código de confirmación fuera del contexto de cancelar/reprogramar una cita (necesario para el nuevo flujo de registro de identidad), y documentar el diseño, implementación y resultado de pruebas de la extensión.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. INFERENCIA = conclusión razonada. PENDIENTE = decisión aún no tomada, nunca inventada.

---

## Resumen ejecutivo

HECHO: se implementó persistencia de identidad de canal (teléfono→documento verificado) en una tabla `identidad_canal` nueva, respaldada por un store SQLite propio (`domains/health/identity_store.py`), separado del `SQLiteStateStore` de `ConversationState`. El wizard de identidad de 012 (`domains/health/gateway.py:_gestionar_identificacion`) creció de 2 a 3 pasos: pedir documento → validar contra `buscar-paciente` → confirmar con código de verificación de 6 dígitos por correo (mismo mecanismo de 009). Un contacto siguiente del mismo teléfono, incluso tras un reinicio del proceso, se reconoce de inmediato sin repetir el wizard.

HECHO: **130 tests pasando + 1 deshabilitado a propósito** (131 recolectados) — 15 tests nuevos de esta fase (`test_identidad_persistente.py`: 9; `+3` en `test_hrmm_appointment_service.py`; `test_identity_gate_chatwoot.py` reescrito para el wizard de 3 pasos), 0 de los 120 tests previos rotos.

HALLAZGO CRÍTICO (bloqueante, resuelto con decisión explícita del usuario): hrmm-backend **NO tiene hoy** ningún endpoint HTTP para confirmar un código de verificación fuera del contexto de cancelar/reprogramar una cita puntual. Se construyó el lado ZANTIA contra un contrato PROPUESTO/coordinado (`POST /api/agenda/verificacion/confirmar`) — ver sección dedicada abajo.

## Investigación: ¿existe un endpoint genérico de verificación de código en hrmm-backend?

HECHO (solo lectura, ningún archivo de `hrmm-backend` modificado — respeta `.claude/rules/aislamiento-entre-proyectos.md`, mismo criterio ya usado en recado 009):

- `/Users/enzoalfonso/Orangutan/hrmm/backend/app/recovery_codes.py`: `verificar_codigo(documento_paciente, codigo) -> bool` es **genérico** — solo depende del documento y el código, ninguna referencia a una cita. Consume el código (un solo uso), respeta TTL 600s (10 min) y máximo 5 intentos.
- `/Users/enzoalfonso/Orangutan/hrmm/backend/app/api/agenda.py`: `recovery_codes.verificar_codigo` se invoca en exactamente 3 lugares — dentro de `cancelar_cita` (línea ~305), `reprogramar_cita` (línea ~334), y un flujo de "PortalAccionRequest" (línea ~524) que también exige `cita_id`. **Ningún endpoint expone la función de forma standalone.**
- Conclusión: para verificar identidad de canal (donde puede no existir todavía ninguna cita), ZANTIA necesita un endpoint que hoy no existe.

## Decisión del usuario ante el hallazgo

Se presentaron 4 opciones (ver conversación): (A) nuevo endpoint mínimo en hrmm-backend reusando `recovery_codes.verificar_codigo`, (B) usar una cita existente como ancla, (C) registrar sin verificación por código, (D) otra idea. **El usuario eligió (A)**: construir el lado ZANTIA contra un contrato documentado y coordinar el endpoint real como trabajo aparte en el repositorio de hrmm-backend.

**Contrato PROPUESTO, NO CONFIRMADO** (documentado explícitamente como tal en el código, nunca presentado como verificado):
```
POST /api/agenda/verificacion/confirmar
Headers: X-Backend-Secret
Body: {"documento_paciente": str, "codigo": str}
200 -> válido (y consumido)
401 -> inválido/vencido/agotado (mismo código que ya usan cancelar/reprogramar)
```
Implementación sugerida del lado de hrmm-backend (no ejecutada, no es este repositorio): un router que llame `recovery_codes.verificar_codigo(documento_paciente, codigo)` y traduzca el bool a 200/401 — la función ya existe y es genérica, el trabajo es solo exponerla.

## Diseño e implementación en ZANTIA

**Tabla `identidad_canal`** (`domains/health/identity_store.py`): columnas `telefono` (PK), `documento`, `estado` (`PENDIENTE_VERIFICACION`/`VERIFICADO`), `verificado_en`. Store SQLite propio (`SQLiteIdentidadCanalStore`, stdlib `sqlite3`, sin ORM — mismo criterio que `state/store.py`), a nivel de `HealthGateway` (compartido por todo el proceso, ver `service/app.py`), NO en el store de `ConversationState`.

**Por qué un store separado (decisión documentada, D-6)**: HECHO — se confirmó leyendo `core/agent_contract.py:build_orchestrator` que cada `HealthAgentContext` (uno por Activity/conversación) construye su PROPIO `SQLiteStateStore(":memory:")`, sin conectar `ZANTIA_DB_PATH` — nace y muere con esa conversación puntual. Un dato que debe sobrevivir a TODAS las conversaciones de un mismo teléfono (incluyendo reinicios del proceso) necesita vivir a un nivel distinto. Esta es una brecha de wiring PREEXISTENTE (ConversationState nunca se conectó a persistencia real de archivo) — no se resolvió aquí, está fuera de alcance de este pedido (no se refactorizó `core/agent_contract.py`).

**Wizard de 3 pasos** (`domains/health/gateway.py:_gestionar_identificacion`, `_iniciar_verificacion_de_identidad`, `_procesar_codigo_de_identificacion`): (1) pedir documento (sin cambios de 012); (2) validar contra `buscar-paciente` (sin cambios de 012) — al validar, escribe `identity_store.guardar_pendiente(telefono, documento)` y llama `send_verification_code` (009, sin cambios); (3) NUEVO — siguiente mensaje se interpreta como código, se llama `confirm_verification_code`. Válido → `identity_store.marcar_verificado` + puebla `_identidad_resuelta` de esta conversación. Inválido → se permite reintentar, SIN contador propio de intentos (se respeta el límite de 5/TTL 10 min que ya impone `recovery_codes.py`, por instrucción explícita del usuario de no inventar un límite nuevo).

**Reconocimiento inmediato en contacto siguiente** (requisito #3 del pedido): al inicio de `handle_inbound_message`, si el teléfono no está en `_identidad_resuelta` (memoria de este proceso) pero SÍ tiene fila `VERIFICADO` en `identity_store`, se hidrata directo, sin invocar el wizard. Probado con dos `HealthGateway` distintos ("dos procesos") contra el mismo archivo SQLite.

**Sin vencimiento** (requisito #4 explícito del usuario: "No definas vencimiento en esta fase") — documentado como PENDIENTE en `.ai/RISKS.md` (R-20) y `.ai/DATA_MODEL.md` (política de retención), nunca omitido en silencio (regla `.claude/rules/proteccion-datos-personales.md`).

## Archivos importantes

- `domains/health/identity_store.py` — NUEVO. `EstadoIdentidadCanal`, `IdentidadCanal`, `IdentidadCanalStore` (Protocol), `SQLiteIdentidadCanalStore`, `build_identity_store`.
- `domains/health/gateway.py` — `HealthGateway.identity_store` (campo nuevo), `build_health_gateway(identity_store=...)`, hidratación en `handle_inbound_message`, wizard extendido.
- `domains/health/hrmm_appointment_service.py` — `confirm_verification_code` (método propio, fuera del Protocol `AppointmentService`, mismo criterio que `send_verification_code`/`buscar_paciente`).
- `service/app.py` — wiring de `identity_store=build_identity_store()`.
- `.env.example` — `ZANTIA_IDENTIDAD_DB_PATH` (nueva, separada de `ZANTIA_DB_PATH`).
- `docs/decisions/d-6-identidad-canal-persistente.md` — decisión formal completa (motivo/alternativas/riesgo/impacto).
- Tests: `tests/domains/health/test_identidad_persistente.py` (nuevo, 9 tests), `test_hrmm_appointment_service.py` (+3), `test_identity_gate_chatwoot.py` (reescrito).

## Decisiones o conclusiones

- Store separado del de `ConversationState` — ver D-6.
- Verificación por código obligatoria antes de persistir (requisito #2c) — no se aceptó la opción más simple de confiar solo en `buscar-paciente`.
- Contrato del endpoint nuevo de hrmm-backend PROPUESTO por ZANTIA, no diseñado por hrmm-backend — sujeto a que el equipo de ese proyecto lo confirme/ajuste al implementarlo.

## Problemas encontrados

Ninguno de tipo "bug encontrado al implementar" en esta fase (a diferencia de 012/013) — el hallazgo principal fue el gap de contrato con hrmm-backend, ya cubierto arriba.

## Riesgos

- **R-19 (nuevo, CRÍTICO/bloqueante)**: `POST /api/agenda/verificacion/confirmar` no existe en hrmm-backend — el paso de código del gate de identidad no puede ejecutarse contra la red real hasta que se implemente ahí. Bloquea cualquier despliegue con `HRMM_BACKEND_ENV=production` + `ChatwootChannel`.
- **R-20 (nuevo)**: sin política de retención para `identidad_canal` — decisión explícita del usuario de posponerla, documentada, no resuelta.
- R-15 (extendido, ver `.ai/RISKS.md`): sigue sin probarse contra red real; `buscar-paciente` sigue sin encontrar pacientes genuinamente nuevos.

## Recomendaciones

1. Coordinar con el repositorio `hrmm-backend` la implementación de `POST /api/agenda/verificacion/confirmar` (trabajo mínimo: exponer `recovery_codes.verificar_codigo` ya existente detrás de un router nuevo) antes de cualquier prueba de red real de este flujo.
2. Definir política de retención de `identidad_canal` antes de operar con usuarios reales (R-20).
3. Cuando el endpoint real exista, ejecutar una prueba de integración real (mismo patrón que el test deshabilitado de `hrmm_appointment_service.py`, gateado por una variable explícita) antes de confiar en `confirm_verification_code` en producción.

## Información que debe conocer ChatGPT

Este repositorio (`icaco`/ZANTIA) tenía, ANTES de esta sesión, una cantidad significativa de trabajo YA IMPLEMENTADO pero **nunca comiteado** (recados 010 a 013 completos: validación de estado real, config/empaquetado/Chatwoot, gate de identidad 012, gestión de beneficiario 013) — confirmado por `git status` al inicio de esta sesión (todos esos archivos aparecían `M`/`??` contra el último commit, `5fca90e`). Esta sesión NO comiteó nada (no se pidió) — todo ese trabajo previo, más el de esta fase, sigue sin commit al cierre de este recado.

## Preguntas pendientes

- ¿Quién/cuándo implementa `POST /api/agenda/verificacion/confirmar` en hrmm-backend? (bloqueante para producción real).
- ¿Cuál debe ser la política de retención de `identidad_canal` (R-20)? Sin definir por decisión explícita del usuario en esta fase.
- ¿Se debe comitear el trabajo acumulado (recados 010-014) en algún punto próximo, dado el volumen sin versionar?

RECADO GENERADO: /Users/enzoalfonso/recado/014-identidad-persistente.md
