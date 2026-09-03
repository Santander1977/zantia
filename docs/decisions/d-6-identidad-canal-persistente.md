# D-6: Identidad de canal persistente entre conversaciones, en un store propio separado de ConversationState

**Decisión**: La identidad de canal (teléfono→documento) verificada por el gate de 012 se persiste ahora en una tabla `identidad_canal`, en un store dedicado (`domains/health/identity_store.py:SQLiteIdentidadCanalStore`) a nivel de `HealthGateway` (compartido por todo el proceso) — NO reutilizando el `SQLiteStateStore` de `ConversationState` (`state/store.py`). Antes de escribirse como confiable, la asociación exige un código de verificación de 6 dígitos por correo (mismo mecanismo ya construido en 009 para cancelar/reprogramar) — no se acepta con solo `buscar-paciente`. El código se confirma contra un endpoint nuevo, `POST /api/agenda/verificacion/confirmar`, PROPUESTO/coordinado con el usuario pero todavía no implementado en hrmm-backend.

**Motivo**: El usuario pidió (2026-09-02) que un paciente ya identificado no tenga que repetir su documento en cada conversación nueva — mismo patrón que WhatsApp Banking/Nequi. Investigando `core/agent_contract.py:build_orchestrator` se confirmó `[CONFIRMADO]` que cada `HealthAgentContext` (uno por Activity/conversación) construye su PROPIO `SQLiteStateStore(":memory:")`, sin conectar `ZANTIA_DB_PATH` — ese store nace y muere con la conversación puntual, exactamente lo opuesto de lo que esta necesidad requiere. Un dato que debe sobrevivir a todas las conversaciones de un mismo teléfono necesita vivir a nivel de proceso (`HealthGateway`), no de conversación.

**Alternativas consideradas**:
1. Reutilizar `SQLiteStateStore`/`ZANTIA_DB_PATH` para `identidad_canal` como una tabla más del mismo archivo — descartada: requeriría además reconectar `ZANTIA_DB_PATH` al `build_orchestrator` actual (hoy hardcodeado a `:memory:`), un cambio de wiring del Core no pedido y fuera de alcance de esta tarea (`.claude/rules/proteccion-produccion-y-codigo.md`: no refactorizar lo que no es objeto directo del pedido).
2. Guardar solo en memoria de `HealthGateway` (como ya hacía `_identidad_resuelta` desde 012) — descartada explícitamente por el usuario: no sobrevive a un reinicio del proceso, que es justo el caso que se pidió resolver.
3. (Elegida) Store SQLite propio (`identity_store.py`), a nivel de `HealthGateway`, con su propia variable de entorno (`ZANTIA_IDENTIDAD_DB_PATH`).

**Ventajas de la opción elegida (3)**:
- Ciclo de vida correcto: vive mientras el teléfono siga siendo válido, no mientras dure una conversación — coincide exactamente con el requisito.
- No exige tocar `core/agent_contract.py` ni el wiring existente de `ConversationState` — cero riesgo sobre componentes 🟡/🔴 no relacionados con este pedido.
- Mismo criterio de minimalismo que el resto del proyecto (`sqlite3` stdlib, sin ORM, sin dependencias nuevas — D-1).

**Desventajas**:
- Dos archivos SQLite conceptualmente similares (`ZANTIA_DB_PATH` y `ZANTIA_IDENTIDAD_DB_PATH`) — riesgo de confusión si no se documenta la distinción (mitigado: ver `.ai/DATA_MODEL.md`, advertencia de nombres ambiguos, y el docstring de `identity_store.py`).
- El código de verificación agrega una dependencia BLOQUEANTE de un endpoint de hrmm-backend que no existe todavía (`POST /api/agenda/verificacion/confirmar`) — a diferencia del resto de la integración con hrmm-backend (siempre verificada contra código real antes de construir), aquí se construyó primero el lado ZANTIA contra un contrato coordinado, no confirmado — ver `.ai/RISKS.md` R-19.

**Riesgo**: Medio — el store en sí es simple y probado (`tests/domains/health/test_identidad_persistente.py`, incluida una prueba de "dos procesos" contra el mismo archivo); el riesgo real está en la dependencia externa no implementada (R-19) y en la ausencia de política de retención (R-20, decisión explícita del usuario de posponerla).

**Impacto**: Nuevo archivo `domains/health/identity_store.py`. `domains/health/gateway.py` (`HealthGateway.identity_store`, hidratación en `handle_inbound_message`, wizard de `_gestionar_identificacion` extendido a 3 pasos). `domains/health/hrmm_appointment_service.py` (+`confirm_verification_code`, método propio fuera del Protocol). `service/app.py` (wiring de `build_identity_store()`). `.env.example` (+`ZANTIA_IDENTIDAD_DB_PATH`). Sin cambios en `HealthBrain`, `AppointmentService` Protocol, `ChatwootChannel`, ni en el wiring de `ConversationState`.

**Estado**: IMPLEMENTADA en ZANTIA (2026-09-02, recado `014`) — BLOQUEADA para producción real hasta que `POST /api/agenda/verificacion/confirmar` exista del lado de hrmm-backend (R-19).
