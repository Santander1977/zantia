# D-1 — Stack técnico del Core MVP de ZANTIA

**Decisión**: usar Python 3.9 + pydantic (contratos de datos) + pytest (tests) + `sqlite3` de la librería estándar (persistencia del `ConversationState`), en un entorno virtual propio del proyecto (`icaco/.venv`, aislado de otros proyectos de Orangutan).

**Motivo**: el prompt maestro de construcción de ZANTIA (sección 30) delega explícitamente esta elección, pidiendo evaluar las necesidades reales del MVP antes de seleccionar tecnología, priorizando mantenibilidad, soporte amplio, facilidad de desarrollo/prueba y preparación para crecer (sección 29: escalable ≠ complejo).

**Alternativas consideradas**:
- **Node/TypeScript**: descartado para el MVP — no aporta ventaja clara sobre Python para esta capa (lógica de orquestación + validación de contratos + persistencia simple), y Python tiene mejor ajuste con `pydantic` para traducir directamente las tablas de campos de `004-contrato-estado-icaco.md` en un modelo validado.
- **PostgreSQL en vez de SQLite**: descartado para el MVP — exigiría un servidor de base de datos corriendo (Docker o local), lo cual el proyecto explícitamente no tiene todavía (sin Docker, sin decisión de deployment). `sqlite3` es parte de la librería estándar de Python, no agrega dependencias, y ya demuestra concurrencia optimista real (ver `state/store.py`). El `StateStore` es una interfaz (`Protocol`) — migrar a Postgres más adelante es agregar una tercera implementación, no reescribir el Orchestrator.
- **SQLAlchemy/ORM**: descartado para el MVP — el esquema es una sola tabla (`conversation_state`, clave + versión + JSON), no justifica la complejidad de un ORM todavía (sección 29: no agregar frameworks solo porque son populares).
- **Anthropic SDK instalado por defecto**: descartado — `AnthropicBrain` existe como código real pero la dependencia `anthropic` queda comentada en `requirements.txt`, para no forzar su instalación ni exigir una API key en la suite de tests, que corre con `FakeBrain` (determinista, sin red, sin costo).

**Ventajas**: cero dependencias externas más allá de `pydantic`/`pytest`; tests deterministas y rápidos (34 tests en <0.1s); camino de migración claro a un motor de persistencia distinto sin tocar el Orchestrator; alineado con la traducción directa de las tablas formales de `004-contrato-estado-icaco.md` a modelos `pydantic`.

**Desventajas**: SQLite con `check_same_thread=False` es una simplificación de un solo proceso — no sirve tal cual para un despliegue con múltiples procesos/workers concurrentes sobre el mismo archivo; Python 3.9 (versión disponible en el sistema) carece de algunas azúcares sintácticas de 3.10+ (se evitaron deliberadamente en el código, ver comentarios en `state/models.py`).

**Riesgo**: bajo para el MVP (sin usuarios reales, sin despliegue). Medio si se despliega tal cual a producción con concurrencia real sin revisar el modelo de conexión SQLite.

**Impacto**: define el lenguaje y las herramientas de todo el Core (`core/`, `state/`, `memory/`, `knowledge/`, `tools/`, `guardrails/`, `observability/`, `agents/`). No define el stack de un futuro canal/servidor expuesto (sección 19 de `005`, sigue pendiente) ni el de un dominio real.

**Estado**: IMPLEMENTADA (2026-09-01) — ver `/Users/enzoalfonso/recado/006-construccion-zantia.md`.
