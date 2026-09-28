# RECADO PARA CHATGPT

Fecha: 2026-09-04
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Brecha de wiring resuelta — `ConversationState` ahora persiste de verdad en disco vía `ZANTIA_DB_PATH`
Objetivo: Documentar la investigación, el fix aplicado (solo Core, sin tocar `domains/health/`), la revisión explícita de D-6, y el resultado de las 4 pruebas pedidas.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. PENDIENTE = no resuelto, nunca inventado.

---

## Resumen ejecutivo

HECHO: `.ai/RISKS.md` R-22 (nueva) pasó de brecha sin abrir formalmente (solo mencionada de pasada en recado 014/D-6) a **RESUELTO**. `core/agent_contract.py:build_orchestrator` construía siempre `SQLiteStateStore(":memory:")` hardcodeado — hoy lee `ZANTIA_DB_PATH` (vía `core/config.py:DEFAULT_CONFIG.db_path`, que ya existía y nunca se usaba en el camino real) y construye el store con la ruta real cuando está configurada. Sin la variable, sigue cayendo a `":memory:"`, pero ya nunca en silencio — queda un `logger.warning` explícito en cada conversación nueva.

HECHO: **147 tests pasando + 2 deshabilitados a propósito** (149 recolectados) — 4 tests nuevos en `tests/core/test_agent_contract_persistencia.py`, 0 de los 145 anteriores rotos. No se tocó ningún archivo de `domains/` ni de ningún dominio.

HECHO: D-6 (`docs/decisions/d-6-identidad-canal-persistente.md`) revisada explícitamente, no asumida — conclusión: **se mantiene la separación** entre `identity_store.py` y `ConversationState`, pero por una razón distinta y más sólida que la original (ver sección dedicada abajo).

## Investigación previa (antes de tocar código)

**1. Dónde y cómo se instanciaba `SQLiteStateStore(":memory:")`**: `core/agent_contract.py:build_orchestrator`, línea 72 (antes del fix) — un solo lugar, sin condicional, sin leer ninguna variable de entorno:
```python
from state.store import SQLiteStateStore
store: StateStore = SQLiteStateStore(":memory:")
```
Confirmado con `grep -rn "SQLiteStateStore(\|InMemoryStateStore(" .` (excluyendo `.venv/` y `tests/`) que es la **única** instanciación hardcodeada de un store en memoria en todo `core/` — no hay un segundo lugar que corregir con el mismo criterio (requisito #3 del pedido, cubierto también con un test que hace el mismo `grep` vía `inspect.getsource`, así queda como aserción de regresión, no solo como prosa).

**2. `ZANTIA_DB_PATH` ya existía, sin conectar**: `.env.example:10` la documentaba desde antes ("Si se omite, el código usa ':memory:'"). `core/config.py:ZantiaConfig.db_path` (propiedad `@property`) ya leía `os.environ.get("ZANTIA_DB_PATH", ":memory:")` — pero `DEFAULT_CONFIG` (la instancia exportada desde `core/__init__.py`) no se importaba ni se usaba en NINGÚN otro archivo del proyecto, confirmado con `grep -rn "DEFAULT_CONFIG\|ZantiaConfig"`. Es decir: la plomería ya estaba construida, solo le faltaba la última conexión — no hubo que crear nada desde cero, wiring puro.

**3. Relación con `identity_store.py`/D-6**: confirmado leyendo `docs/decisions/d-6-identidad-canal-persistente.md` completo — la decisión de separar `identidad_canal` en su propio store (en vez de agregarlo como tabla del mismo `SQLiteStateStore`) se tomó **en parte** porque en ese momento reconectar `ZANTIA_DB_PATH` habría sido "un cambio de wiring del Core no pedido y fuera de alcance" de la tarea de 014. Esa razón puntual ya no aplica — el wiring ya está resuelto. Ver sección "Revisión de D-6" más abajo para la conclusión completa (no se revirtió la separación, pero el motivo cambió).

## El fix (solo Core — `domains/health/` sin tocar, confirmado con `git status`/diff acotado a `core/` y `state/`)

**`core/agent_contract.py`**:
```python
db_path = DEFAULT_CONFIG.db_path
if db_path == ":memory:":
    logger.warning(
        "ZANTIA_DB_PATH no está configurada — el ConversationState de "
        "esta conversación vive solo en memoria del proceso y se "
        "pierde por completo si el proceso se reinicia a mitad de "
        "camino. Configurar ZANTIA_DB_PATH (ver .env.example) antes "
        "de desplegar cualquier canal en producción."
    )
store: StateStore = SQLiteStateStore(db_path)
```
Logger `logging.getLogger("zantia.core")` — mismo patrón que `service/app.py:logging.getLogger("zantia.service")`, no un mecanismo nuevo.

**Decisión sobre el comportamiento por defecto (requisito explícito del pedido: "decide y documenta")**: se mantiene `":memory:"` como default sin la variable — NO se cambió a una ruta de archivo por defecto. Motivo, explícito, no implícito:
1. Consistencia con el precedente ya establecido por `identity_store.py:build_identity_store()` (mismo patrón exacto: `os.environ.get(...) or ":memory:"`, sin warning hasta ahora). Diverger del patrón sin necesidad habría dejado dos convenciones distintas conviviendo en el mismo proyecto.
2. Un default de archivo real habría cambiado el comportamiento de **toda** la suite existente (decenas de tests que construyen `AgentDefinition`/`Orchestrator` sin configurar la variable) — riesgo de contaminación entre tests (un `conversation_id` de un test anterior "sobreviviendo" en un archivo por defecto) y de escribir archivos fuera de `tmp_path` sin que nadie lo pidiera.
3. El riesgo real que el pedido señala no es "que el default sea `:memory:`" — es que sea **silencioso**. Un `logger.warning` explícito por cada conversación nueva resuelve exactamente eso sin los efectos secundarios de (2).

**`state/store.py`**: `SQLiteStateStore.__init__` ahora crea el directorio padre (`Path(db_path).parent.mkdir(parents=True, exist_ok=True)`) si `db_path != ":memory:"` — sin esto, una `ZANTIA_DB_PATH` apuntando a una carpeta que todavía no existe en el entorno de despliegue (caso realista: primer deploy) rompería con un error críptico de `sqlite3` en el primer mensaje real, no al arrancar el proceso.

**Aislamiento entre conversaciones (requisito #2 del pedido)**: por diseño, no por un mecanismo nuevo — `conversation_id` ya era la clave primaria de la tabla `conversation_state` (`state/store.py`, sin cambios en el schema). Múltiples instancias de `SQLiteStateStore` (una por `Activity`/conversación, como ya documentaba `domains/health/agent.py`) contra el mismo archivo son exactamente el patrón estándar de SQLite (cada una con su propia conexión `sqlite3.connect`), y cada fila queda aislada por esa clave. Confirmado con un test explícito de "tres procesos" (ver abajo), no solo argumentado.

## Revisión de D-6 (requisito explícito del pedido: documentar la conclusión, no asumirla)

**Pregunta**: ahora que `ConversationState` también persiste de verdad, ¿debería unificarse con `identity_store.py`?

**Conclusión: NO — se mantiene la separación, pero por un motivo distinto al original.**

La razón original de D-6 para descartar la alternativa 1 ("reutilizar `SQLiteStateStore`/`ZANTIA_DB_PATH` para `identidad_canal` como una tabla más del mismo archivo") era en parte de **alcance** ("requeriría además reconectar `ZANTIA_DB_PATH` al `build_orchestrator` actual... fuera de alcance de esta tarea"). Esa razón ya no existe. Pero investigando de nuevo con esta pregunta específica en mente, hay una razón **arquitectónica** independiente de esa que sigue siendo válida, y es más fuerte:

1. **Claves primarias incompatibles**: `conversation_state` usa `conversation_id` (una fila por Activity/conversación puntual, nace y muere con ella). `identidad_canal` usa `telefono` (una fila por número de canal, sobrevive a TODAS las conversaciones de ese teléfono). No son la misma entidad con forma distinta — son conceptos distintos que ocasionalmente comparten motor de almacenamiento (SQLite), no esquema.
2. **Retención incompatible**: `identidad_canal` tiene una política de retención explícita y ya implementada (180 días + eliminación a pedido, recado 016) que NO tiene sentido para `ConversationState` (¿qué significaría "vencer" una conversación puntual ya cerrada? Es una pregunta de producto distinta, no respondida, y mezclar los dos esquemas la forzaría a resolverse antes de tiempo).
3. **Core debe seguir sin saber de dominios**: `identidad_canal` es un concepto de negocio del dominio salud (aunque conceptualmente reutilizable por cualquier dominio con canal telefónico). Si viviera en el mismo archivo/tabla que administra `core/agent_contract.py`, el Core empezaría a acoplarse — aunque sea solo a nivel de archivo físico compartido — a una decisión de un dominio específico. Mantenerlos en archivos separados (aun si ambos son SQLite, aun si ambos ahora persisten de verdad) preserva la línea "el Core no sabe de dominios" de forma literal, no solo de código sino de infraestructura de datos.

**Lo que SÍ cambia con este fix**: la desventaja que D-6 documentaba ("dos archivos SQLite conceptualmente similares — riesgo de confusión") sigue existiendo tal cual, pero ya no es agravada por la asimetría de "uno persiste de verdad y el otro no" — ahora los dos son igual de reales, cada uno con su propia variable (`ZANTIA_DB_PATH` / `ZANTIA_IDENTIDAD_DB_PATH`), documentadas una al lado de la otra en `.env.example` explicando la distinción. No se propone ningún cambio adicional a `identity_store.py` — sigue exactamente como quedó en recado 016.

## Verificación (las 4 pruebas pedidas)

Archivo nuevo: `tests/core/test_agent_contract_persistencia.py` (no se tocó ningún test existente).

1. **`ZANTIA_DB_PATH` configurada, "reinicio del proceso" real**: `test_build_orchestrator_usa_zantia_db_path_y_sobrevive_a_reinicio` — mismo patrón que `test_dos_gateways_distintos_comparten_identidad_via_store` de 014. `proceso_1` (via `build_demo_agent()`, agente demo real con sus tools) avanza una conversación hasta `RECOPILACION_DE_DATOS` con datos reales, cierra su conexión (`store.close()`); `proceso_2`, instancia de `Orchestrator` completamente nueva apuntando al mismo archivo, recupera el estado exacto (mismo `fase_actual`, mismos `datos_recopilados`, misma `version`) y la conversación sigue avanzando normalmente desde ahí hasta `RESPUESTA` (incluye ejecución real de la tool `schedule_event`). **PASA**.
2. **Sin `ZANTIA_DB_PATH`, comportamiento por defecto documentado**: dos tests — `test_build_orchestrator_sin_zantia_db_path_cae_a_memoria_y_advierte` (confirma `store._db_path == ":memory:"` Y que quedó un `logger.warning` con "ZANTIA_DB_PATH" + "no está configurada" en el logger `zantia.core`, capturado con `caplog`) y `test_build_orchestrator_con_zantia_db_path_no_advierte` (confirma que el warning NO aparece cuando la variable SÍ está configurada — evita que una producción bien configurada tenga alarmas falsas). **PASAN los dos**.
3. **Dos conversaciones distintas, mismo archivo, sin mezclarse**: `test_dos_conversaciones_distintas_no_se_mezclan_en_el_mismo_archivo` — tres `Orchestrator` distintos (no dos) contra el mismo archivo: `proceso_a` escribe `conv-a` con `evento="cumpleaños de Ana"`, `proceso_b` escribe `conv-b` con `evento="reunión de trabajo"`, y un tercer `Orchestrator` ("verificador", que nunca escribió nada) lee ambas filas del mismo archivo y confirma que cada una tiene exactamente su propio dato, sin cruzarse. **PASA**.
4. **Suite completa**: `.venv/bin/pytest -q` desde la raíz del repo → **147 passed, 2 skipped** (los 2 mismos de siempre, gateados por `ZANTIA_RUN_REAL_HRMM_TESTS`, sin cambios). Corrida completa, no solo el archivo nuevo — Core + dominio salud + identidad, tal como pedía el requisito #4 explícitamente por ser un cambio de Core (el de mayor riesgo transversal).

## Archivos tocados (todos dentro de lo permitido — Core, sin `domains/health/`)

- `core/agent_contract.py` (el fix)
- `state/store.py` (creación de directorio padre)
- `.env.example` (documentación del nuevo comportamiento del warning)
- `tests/core/test_agent_contract_persistencia.py` (nuevo, 4 tests — ninguno existente modificado)
- `.ai/RISKS.md` (R-22 nueva, RESUELTO; R-11 corregida para no seguir afirmando algo que antes de este fix no era cierto)
- `.ai/ARCHITECTURE.md` (fila de `StateStore` actualizada)
- Este recado (`021`)

## Pendiente / fuera de alcance de esta sesión, a propósito

- `ConversationMemory` y `EventLog` siguen sin persistir (R-11, todavía ABIERTO) — el pedido fue específicamente sobre `ConversationState`, no sobre estos dos. Mismo patrón (`ZANTIA_DB_PATH` o uno propio) es un candidato razonable para una sesión futura, no decidido acá.
- No se probó `ZANTIA_DB_PATH` en un despliegue real (EasyPanel) — sigue pendiente R-12/R-16 (decisión de plataforma, Docker nunca construido en esta máquina), sin relación directa con este fix salvo que ahora SÍ hay algo real que desplegar con esa variable configurada.
