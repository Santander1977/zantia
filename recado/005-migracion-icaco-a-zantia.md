# RECADO PARA CHATGPT

Fecha: 2026-09-01
Proyecto: icaco (ecosistema Orangutan) — evaluando el cambio de identidad conceptual ICACO → ZANTIA
Tema: Auditoría de migración de identidad — inventario completo de referencias a "ICACO", dependencias, riesgos y plan de migración, ANTES de ejecutar ningún cambio físico
Objetivo: Determinar exactamente dónde aparece "ICACO", qué significa cada aparición, qué se puede cambiar con seguridad, qué debe conservarse, y si el proyecto está listo para ejecutar la migración conceptual a "ZANTIA" — sin modificar ningún archivo en esta fase

Este documento es autocontenido. Se apoya en tres documentos históricos, que **no fueron modificados** durante esta auditoría:
- `/Users/enzoalfonso/recado/002-autopsia-cerebro-dani.md`
- `/Users/enzoalfonso/recado/003-arquitectura-cerebro-icaco.md`
- `/Users/enzoalfonso/recado/004-contrato-estado-icaco.md`

Convenciones: **HECHO** = verificado directamente con comandos de solo lectura en esta sesión. **INFERENCIA** = conclusión razonada, no verificada literalmente. **RECOMENDACIÓN** = propuesta de este documento. **PENDIENTE** = requiere una decisión humana. **NO CONFIRMADO** = no se pudo verificar con las herramientas disponibles en esta sesión; no se asume una respuesta.

---

## 1. Resumen ejecutivo

HECHO: se encontraron **20 apariciones** de "icaco" (case-insensitive) en **15 archivos**, todas dentro del propio proyecto `icaco`, más 4 apariciones adicionales en los recados históricos (001-004, que deben conservarse intactos por instrucción explícita).

HECHO: **cero** apariciones de "icaco" en `PROJECT-TEMPLATE`, en `orangutan-kit`, en las 5 copias del skill de Dani, y en los demás proyectos hermanos de Orangutan (`hrmm`, `hrmm-panel-operador`, `mi-primer-proyecto`, `template-agente-ia`, `piloto-plantilla-01`, `piloto-sem-operacional`, `portal-citas`) — barridos todos en esta sesión.

HECHO: de las 20 apariciones dentro de icaco, **ninguna** es un identificador técnico, variable de entorno, URL, configuración de Docker o dato de test — porque **no existe todavía ni una sola línea de código, ni Docker, ni `.env`, ni stack elegido** en el proyecto (confirmado leyendo `.ai/CURRENT_STATE.md`). Las 20 apariciones son, sin excepción, **títulos de documentos y prosa explicativa**.

INFERENCIA + RECOMENDACIÓN (síntesis): esto convierte a esta migración en un caso casi ideal — de muy bajo riesgo técnico, porque no hay código ni infraestructura que romper. El único riesgo real y **crítico** identificado no está en ningún archivo de texto: es que **Claude Code deriva automáticamente su carpeta de memoria/sesión del nombre físico exacto de la ruta del proyecto** (`~/.claude/projects/-Users-enzoalfonso-Orangutan-icaco/`, que contiene el protocolo RECADO ya guardado). Renombrar la carpeta física `icaco/` haría que Claude Code cree una carpeta de memoria nueva y distinta, dejando huérfana la memoria ya guardada. Por eso la recomendación central de este documento es: **la identidad conceptual puede pasar a ZANTIA ahora; el nombre físico de la carpeta debe conservarse por ahora.**

Decisión de esta fase (detalle en sección 19): **SÍ, CON CONDICIONES.**

---

## 2. Contexto histórico

HECHO, leído directamente de los tres documentos:
- `002-autopsia-cerebro-dani.md`: autopsia técnica de "Dani", un agente de ventas por WhatsApp implementado en n8n, usado como fuente de patrones arquitectónicos (no como plantilla a clonar).
- `003-arquitectura-cerebro-icaco.md`: primera arquitectura conceptual de ICACO, un agente conversacional de salud, diseñada corrigiendo las debilidades encontradas en Dani (estado explícito, guardrails, observabilidad). Su sección 18 (principio 12) ya declaraba: *"El núcleo de orquestación, estado y guardrails es agnóstico de dominio — solo el conocimiento, las tools y las reglas de negocio cambian si ICACO se extiende más allá de salud."*
- `004-contrato-estado-icaco.md`: especificación técnica preliminar del objeto `ConversationState` de ICACO — modelo formal, máquina de estados, autoridad de escritura, contratos entre componentes.

RECOMENDACIÓN: estos tres documentos, junto con `001-auditoria-dani.md`, deben conservarse exactamente como están — son el registro de la cadena de decisiones **Dani → ICACO → ZANTIA**, y esta auditoría es, precisamente, el punto donde ese camino empieza a bifurcarse hacia el nombre nuevo (ver sección 10).

---

## 3. Inventario completo de referencias ICACO

HECHO — cada aparición, con archivo, línea y contexto textual exacto:

| # | Archivo | Línea | Contenido |
|---|---|---|---|
| 1 | `icaco/PROJECT.md` | 1 | `# icaco` |
| 2 | `icaco/README.md` | 1 | `# icaco` |
| 3 | `icaco/CONTRIBUTING.md` | 1 | `# Guía de contribución — icaco` |
| 4 | `icaco/CONTRIBUTING.md` | 15 | "...una regla de dominio adicional propia de `icaco`: protección de datos personales..." |
| 5 | `icaco/.claude/rules/proteccion-datos-personales.md` | 3 | "...añadida en la creación de `icaco` porque el proyecto es un agente conversacional..." |
| 6 | `icaco/.claude/rules/proteccion-datos-personales.md` | 16 | "Añadida al crear `icaco` con `/new-project`..." |
| 7 | `icaco/.ai/DATA_MODEL.md` | 1 | `# MODELO DE DATOS — icaco` |
| 8 | `icaco/.ai/RISKS.md` | 1 | `# REGISTRO DE RIESGOS — icaco` |
| 9 | `icaco/.ai/DISCOVERIES.md` | 1 | `# DESCUBRIMIENTOS — icaco` |
| 10 | `icaco/.ai/ARCHITECTURE.md` | 1 | `# ARQUITECTURA — icaco` |
| 11 | `icaco/.ai/ARCHITECTURE.md` | 15 | `\| icaco \| /Users/enzoalfonso/Orangutan/icaco \| — (aún no inicializado como repo git) \| único repo del proyecto \|` |
| 12 | `icaco/.ai/CURRENT_STATE.md` | 1 | `# ESTADO ACTUAL — icaco` |
| 13 | `icaco/.ai/API_CONTRACTS.md` | 1 | `# CONTRATOS API — icaco` |
| 14 | `icaco/.ai/TESTING.md` | 1 | `# TESTING — icaco` |
| 15 | `icaco/.ai/TESTING.md` | 16 | `## Estrategia mínima viable para icaco` |
| 16 | `icaco/.ai/INTEGRATIONS.md` | 1 | `# INTEGRACIONES — icaco` |
| 17 | `icaco/.ai/SECURITY.md` | 1 | `# SEGURIDAD — icaco` |
| 18 | `icaco/.ai/DECISIONS.md` | 1 | `# DECISIONES — icaco` |
| 19 | `icaco/.ai/DEPLOYMENT.md` | 1 | `# DESPLIEGUE — icaco` |
| 20 | `icaco/.ai/AGENTS.md` | 1 | `# AGENTES DE IA — icaco` |

Más una **referencia física, no textual**: la carpeta `/Users/enzoalfonso/Orangutan/icaco` en sí (analizada en sección 6), y una **referencia técnica derivada**: la carpeta de sesión/memoria de Claude Code `~/.claude/projects/-Users-enzoalfonso-Orangutan-icaco/` (analizada en sección 7).

Verificado, con **cero resultados**: `.claude/commands/*.md`, `.claude/agents/*.md`, `docs/CLIENT.local.md`, `docs/README.md`, `tests/README.md`, `scripts/README.md` — ninguno menciona "icaco" literalmente.

---

## 4. Clasificación

Usando la taxonomía A-K pedida:

- **A. Identidad conceptual**: los 20 hits de la sección 3, sin excepción (todos son título de documento o prosa explicativa sobre qué es/para qué existe el proyecto).
- **B. Nombre del proyecto**: la carpeta `icaco/` — tratada aquí como caso especial de **D** (ruta), por ser simultáneamente ambas cosas.
- **C. Identificador técnico**: **ninguno encontrado.** No existe `ICACO_API`, `icaco_service`, `icaco_db` ni equivalente — no hay código todavía.
- **D. Ruta**: `/Users/enzoalfonso/Orangutan/icaco` (la carpeta física) + su reproducción literal en la fila de topología de `ARCHITECTURE.md:15`.
- **E. URL**: **ninguna encontrada.**
- **F. Variable de entorno**: **ninguna encontrada** (no existe `.env` ni `.env.example` en icaco).
- **G. Configuración**: **ninguna encontrada** más allá de la documentación (no hay `settings.json` propio en `icaco/.claude/`).
- **H. Documentación**: los mismos 20 hits — son documentación **actual**, no histórica (a diferencia de los recados 002-004).
- **I. Test**: **ninguna referencia** — `tests/README.md` es genérico, sin menciones.
- **J. Referencia externa**: **ninguna encontrada** — ni PROJECT-TEMPLATE, ni orangutan-kit, ni Dani, ni ningún proyecto hermano mencionan "icaco".
- **K. Conocimiento de negocio**: los hits #5 y #6 (`proteccion-datos-personales.md`) — no son solo identidad, son el **registro histórico de por qué existe esa regla** ("se añadió cuando el proyecto se creó como icaco").

INFERENCIA: la ausencia total de hits en las categorías C, E, F, G, I, J es en sí misma el hallazgo más importante de esta auditoría — significa que la migración de identidad, en el estado actual del proyecto, es un cambio casi puramente documental.

---

## 5. Dependencias

HECHO:
- La sesión de Claude Code que ejecuta esta misma auditoría tiene como *working directory* exactamente `/Users/enzoalfonso/Orangutan/icaco` (confirmado con `pwd`).
- La carpeta de memoria/sesión de Claude Code (`~/.claude/projects/-Users-enzoalfonso-Orangutan-icaco/`) depende 100% de que la ruta física del proyecto sea exactamente esa — Claude Code la deriva automáticamente reemplazando `/` por `-` en la ruta absoluta.
- Esa carpeta contiene `memory/protocolo_recado.md` y `memory/MEMORY.md` (el protocolo RECADO guardado en sesiones anteriores) y el archivo de transcript de esta sesión.
- `icaco` no es todavía un repositorio git (`git status` devuelve "not a git repository") — no hay remoto, no hay CI, no hay historia que preservar todavía.
- No existen Dockerfile, docker-compose ni archivos `.env`/`.env.example` en el proyecto.

HECHO (verificado leyendo el script directamente, no asumido): `scripts/verificar-aislamiento.sh` calcula su `ROOT_DIR` de forma **relativa a su propia ubicación** (`$(dirname "${BASH_SOURCE[0]}")/..`), no con una ruta absoluta ni con el nombre "icaco" hardcodeado — por lo tanto **no depende del nombre de la carpeta** y seguiría funcionando igual aunque la carpeta se llamara distinto.

NO CONFIRMADO: si existe algún mecanismo interno de Claude Code, no observable desde el filesystem, que dependa adicionalmente del nombre del proyecto más allá de la ruta de memoria ya identificada.

---

## 6. Rutas críticas

HECHO, sobre `/Users/enzoalfonso/Orangutan/icaco`:
- **Existe**: sí, confirmado.
- **Qué contiene**: `.ai/` (13 archivos de memoria comprimida), `.claude/` (rules, agents, commands), `docs/` (incluye `CLIENT.local.md` gitignored), `scripts/verificar-aislamiento.sh`, `tests/README.md`, `PROJECT.md`, `README.md`, `CONTRIBUTING.md`, `.gitignore`.
- **Qué procesos dependen de ella**: la sesión activa de Claude Code (esta misma) y su carpeta de memoria derivada (sección 5).
- **Desde dónde se ejecuta Claude Code**: confirmado, desde esta misma ruta.
- **Scripts que esperan exactamente esa ruta**: **no** — el único script presente (`verificar-aislamiento.sh`) es relativo a sí mismo, no a "icaco" (ver sección 5).
- **Configuraciones que usan la ruta**: ninguna encontrada, salvo la fila de topología en `ARCHITECTURE.md:15`, que es documentación, no configuración ejecutable.
- **Procesos actualmente funcionando desde esa ubicación**: sí — esta misma sesión de Claude Code.

---

## 7. Claude Code

HECHO:
- No existe un `CLAUDE.md` propio en la raíz de `icaco` — las instrucciones de proyecto viven en `.claude/rules/` (7 archivos), `.claude/agents/` (4) y `.claude/commands/` (6).
- **Ninguno** de esos 17 archivos menciona "icaco" literalmente en su contenido (confirmado por grep) — son agnósticos de nombre, lo cual significa que ya están listos para convivir con una identidad conceptual distinta sin necesitar cambios.
- No existe `settings.json` ni `settings.local.json` propio de icaco.
- La única dependencia real de ruta confirmada es la carpeta de memoria/sesión (sección 5) — no es un archivo del proyecto editable, es un mecanismo interno de la herramienta.
- No se encontró un `CLAUDE.md` global de usuario (`~/.claude/CLAUDE.md`) que mencione "icaco".

NO CONFIRMADO: cualquier dependencia de Claude Code sobre el nombre del proyecto que no sea observable como archivo en el filesystem.

---

## 8. Project-Template

HECHO: **cero** referencias a "icaco"/"ICACO" en todo `PROJECT-TEMPLATE` (barrido recursivo, case-insensitive). Es coherente con su propósito declarado: contiene el ADN genérico de Orangutan, nunca contenido de un proyecto de cliente específico (regla de aislamiento entre proyectos, ya verificada como cumplida).

RECOMENDACIÓN (a futuro, fuera del alcance de esta auditoría de solo lectura): si se decide que el patrón "CORE + dominios" de ZANTIA debe convertirse en la arquitectura base que `PROJECT-TEMPLATE` ofrece a futuros proyectos de tipo "agente conversacional multi-dominio", eso sería un cambio deliberado de la plantilla — a decidir y documentar aparte, nunca de forma automática.

---

## 9. Orangutan-Kit

HECHO: **cero** referencias a "icaco" en todo `orangutan-kit`. Lo único relacionado con esta cadena de decisiones que contiene es una de las 5 copias idénticas del skill de ejemplo de Dani (`ejemplo-cerebro-ventas/cerebro-dani-v3.json`), que tampoco menciona "icaco" (verificado). No requiere ningún cambio.

---

## 10. Recados históricos

HECHO: `001-auditoria-dani.md`, `002-autopsia-cerebro-dani.md`, `003-arquitectura-cerebro-icaco.md` y `004-contrato-estado-icaco.md` existen en `/Users/enzoalfonso/recado/` y **no fueron modificados** durante esta auditoría (ninguna herramienta de escritura se usó sobre ellos en esta sesión).

RECOMENDACIÓN: conservarlos exactamente como están, sin renombrar ni reescribir — son el registro de la cadena **Dani → ICACO**. Este documento (`005`) es el punto donde el registro histórico se bifurca formalmente hacia ZANTIA, sin alterar lo anterior. Si más adelante se ejecuta la migración real (fuera de esta fase, que es solo auditoría), RECOMENDACIÓN: crear un documento adicional (ej. `006-migracion-icaco-a-zantia-ejecutada.md`) que registre qué se cambió efectivamente, separado de este documento, que es la auditoría *previa* a cualquier cambio.

---

## 11. Dani

HECHO: cero referencias cruzadas en ambas direcciones — Dani (sus 5 copias) no menciona "icaco" en absoluto, e icaco no menciona "dani", "cerebro-dani" ni "ejemplo-cerebro-ventas" en absoluto (ambos barridos hechos en esta sesión). El aislamiento entre proyectos, exigido por `.claude/rules/aislamiento-entre-proyectos.md` de icaco, está confirmado como cumplido en este par específico. La única relación entre ambos existe exclusivamente dentro de los recados de análisis (002, 003, 004), que son documentos de esta carpeta `recado/`, no artefactos de ninguno de los dos proyectos. No hay nada que desconectar — ya están desconectados.

---

## 12. Nueva identidad ZANTIA

INFERENCIA + RECOMENDACIÓN, evaluando coherencia contra 003 y 004:

- `003` (sección 18, principio 12) ya declaraba explícitamente: *"El núcleo de orquestación, estado y guardrails es agnóstico de dominio — solo el conocimiento, las tools y las reglas de negocio cambian si [el sistema] se extiende más allá de salud."* Esto es, en esencia, la misma premisa que ZANTIA CORE + dominios (Salud/Emergencias/Ventas/Atención ciudadana) — la nomenclatura propuesta no contradice esa decisión de diseño, la nombra formalmente por primera vez.
- `004` diseñó el `ConversationState` con solo dos campos explícitamente marcados como "propios del dominio salud" (`nivel_de_riesgo`/`señal_de_urgencia`, con el criterio de contenido marcado PENDIENTE de validación clínica) — coherente con la idea de que el *campo* pertenece al CORE (toda plataforma agéntica necesita poder modelar riesgo) mientras el *criterio/protocolo* de cada campo es específico de cada dominio (salud tendría un protocolo, emergencias otro, ventas quizás ninguno).
- No se detectó ninguna incoherencia entre la nomenclatura ZANTIA/ZANTIA CORE/ZANTIA HEALTH/ZANTIA EMERGENCY/ZANTIA SALES/ZANTIA CITIZEN y lo ya diseñado en 003/004.

PENDIENTE: si "ZANTIA EMERGENCY" implica un protocolo de riesgo/urgencia *distinto* del de "ZANTIA HEALTH", o si comparten el mismo campo del CORE con distinto contenido — no se puede determinar sin la validación clínica/de producto que ya estaba marcada como pendiente en `003` y `004`.

---

## 13. Matriz ICACO → ZANTIA

RECOMENDACIÓN — matriz de migración completa:

| Referencia | Ubicación | Tipo | Función | Dependencias | Riesgo | Acción recomendada |
|---|---|---|---|---|---|---|
| `# icaco` (títulos) | `PROJECT.md`, `README.md` | A | Nombre del documento/proyecto | Ninguna técnica | BAJO | 🟢 CAMBIAR |
| `— icaco` / "propia de `icaco`" | `CONTRIBUTING.md` | A/H | Identidad en prosa | Ninguna técnica | BAJO | 🟢 CAMBIAR |
| `# ... — icaco` (8 títulos) | `.ai/*.md` | A/H | Encabezados de memoria del proyecto | Ninguna técnica | BAJO | 🟢 CAMBIAR |
| `## Estrategia mínima viable para icaco` | `.ai/TESTING.md:16` | A/H | Subtítulo | Ninguna técnica | BAJO | 🟢 CAMBIAR |
| Fila de topología `\| icaco \| /Users/.../icaco \|...` | `.ai/ARCHITECTURE.md:15` | D + A mezclados | Documenta repo y ruta a la vez | Depende de que la ruta física exista tal cual | MEDIO | 🟡 CAMBIAR DESPUÉS DE VALIDAR — separar "nombre" de "ruta física" antes de tocar esta fila |
| "en la creación de `icaco`" / "Añadida al crear `icaco`" | `.claude/rules/proteccion-datos-personales.md:3,16` | K | Registra el origen histórico de la regla | Trazabilidad, no técnica | MEDIO | 🟡 CAMBIAR DESPUÉS DE VALIDAR — preservar la mención de que la regla nació como "icaco" |
| Carpeta física `icaco/` | `/Users/enzoalfonso/Orangutan/icaco` | D | Working directory activo | Ancla de la memoria de Claude Code | **CRÍTICO** | 🔴 NO CAMBIAR EN ESTA FASE |
| Carpeta de sesión/memoria Claude Code | `~/.claude/projects/-Users-...-icaco/` | C (generado automáticamente) | Almacena memoria persistente y transcript | 100% de la ruta física | **CRÍTICO** | 🔴 NO CAMBIAR (no es editable directamente) |
| Recados 001-004 | `/Users/enzoalfonso/recado/` | H | Registro histórico de decisiones | Ninguna técnica | BAJO (alto valor si se pierde) | 🔵 CONSERVAR |
| `PROJECT-TEMPLATE` | — | — | Sin referencias | N/A | N/A | ⚪ PENDIENTE (solo si se decide llevar el patrón ZANTIA a la plantilla, fuera de esta auditoría) |
| `orangutan-kit` | — | — | Sin referencias | N/A | N/A | 🔵 CONSERVAR (no requiere acción) |
| Dani (5 copias) | — | J | Sin referencias, confirma aislamiento | N/A | N/A | 🔴 NO CAMBIAR (no aplica) |
| `.claude/commands/*.md`, `.claude/agents/*.md` | `icaco/.claude/` | — | Ya agnósticos de nombre | Ninguna | BAJO | 🔵 CONSERVAR |
| Identificadores técnicos (`ICACO_API`, etc.) | — | C | No existen todavía | — | N/A | ⚪ PENDIENTE — si se crean al elegir stack, nacer directamente con nomenclatura ZANTIA evita una migración futura |
| URLs/dominios | — | E | No existen todavía | — | N/A | ⚪ PENDIENTE |
| Variables de entorno | — | F | No existen todavía | — | N/A | ⚪ PENDIENTE |
| Tests | `tests/README.md` | I | Genérico, sin menciones | Ninguna | BAJO | 🔵 CONSERVAR |

---

## 14. Riesgos

RECOMENDACIÓN — evaluación por categoría:

| Categoría | Nivel | Motivo |
|---|---|---|
| Documentación | BAJO | 20 hits, todos texto editable sin dependencias técnicas |
| Nombres de carpetas | **CRÍTICO** (solo la raíz `icaco/`) / BAJO (el resto) | La raíz ancla la memoria de Claude Code; ninguna subcarpeta interna lleva "icaco" en su nombre |
| Rutas | **CRÍTICO** | Misma razón — ruta física = ancla de la sesión activa |
| Variables | N/A | No existen todavía |
| Configuración | N/A | No existe configuración propia de icaco (ni `settings.json` ni `.env`) |
| Código | N/A | No existe ni una línea de código — es el momento más barato posible para este cambio |
| Docker | N/A | No existe |
| Servicios | N/A | `CURRENT_STATE.md` confirma que no hay nada desplegado |
| URLs | N/A | No existen |
| Integraciones | BAJO | `INTEGRATIONS.md` no documenta integraciones reales todavía |
| Claude Code | **CRÍTICO** (dependencia ruta→memoria) / MEDIO (resto) | Reglas/agentes/comandos son agnósticos; la dependencia de ruta es la única crítica |
| PROJECT-TEMPLATE | N/A | Cero referencias, aislamiento ya correcto |
| orangutan-kit | N/A | Cero referencias |

---

## 15. Plan de migración

RECOMENDACIÓN — procedimiento por fases, **ninguna ejecutada en esta sesión**:

**Fase A — Preparación** (sin tocar el proyecto): confirmar con el usuario la nomenclatura final exacta (¿"ZANTIA" a secas o "ZANTIA HEALTH" para esta instancia?) y confirmar que la carpeta física permanece como `icaco/` por ahora (sección 16).

**Fase B — Respaldo**: dado que `icaco` no es todavía un repositorio git, RECOMENDACIÓN: inicializar git y hacer un primer commit del estado actual **antes** de cualquier cambio real — así cada fase siguiente queda respaldada y es reversible con `git revert`, coherente con la regla de protección de producción/código ya vigente en icaco.

**Fase C — Cambios de identidad conceptual** (bajo riesgo, tipo A/H — 18 de los 20 hits): actualizar título y prosa de "icaco" a la nomenclatura ZANTIA decidida, archivo por archivo, cada uno revisable de forma independiente.

**Fase D — Trazabilidad histórica** (los 2 hits tipo K en `proteccion-datos-personales.md`): no reemplazar el texto sin más — agregar una nota explícita de que la regla nació cuando el proyecto se llamaba "icaco", para no perder esa memoria de origen.

**Fase E — Decisión sobre la ruta física** (tipo D, la fila de `ARCHITECTURE.md:15` y la carpeta en sí): **no se ejecuta en esta fase.** Si en el futuro se decide un renombrado físico real, requeriría coordinar el cierre de la sesión activa de Claude Code, migrar manualmente la carpeta de memoria, y verificar que ninguna sesión quede huérfana — un procedimiento propio, separado de este plan.

**Fase F — Validación**: tras cada fase, releer los archivos cambiados y confirmar que ninguna referencia crítica (rutas, `PROJECT-TEMPLATE`, `orangutan-kit`, Dani, recados históricos) fue tocada por accidente.

**Fase G — Rollback**: con git ya inicializado (Fase B), cada fase de cambio es un commit independiente y reversible — nunca se usa `reset --hard` ni se reescribe historia, coherente con las reglas ya vigentes del proyecto.

---

## 16. Rutas que deben conservarse

RECOMENDACIÓN explícita: `/Users/enzoalfonso/Orangutan/icaco` debe conservarse **exactamente como está** en esta fase — no renombrar, no mover, no eliminar.

El nombre conceptual (ZANTIA / ZANTIA HEALTH) y el nombre físico de la carpeta (`icaco`) **no tienen que coincidir** — es perfectamente válido, y más seguro ahora mismo, que la carpeta siga llamándose `icaco` internamente mientras toda la documentación e identidad de cara al negocio ya hable de ZANTIA. No se debe asumir que "cambiar el nombre" implica necesariamente "renombrar la carpeta".

---

## 17. Estructura futura

RECOMENDACIÓN — evaluación de coherencia de la estructura propuesta (`core/`, `domains/{health,emergency,sales,citizen}/`, `agents/`, `channels/`, `knowledge/`, `tools/`, `memory/`, `state/`, `observability/`) contra `003` y `004`, **sin implementarla**:

| Carpeta propuesta | Coherencia con 003/004 |
|---|---|
| `core/` | Coherente con el Orquestador + Cerebro + Guardrails de `003` (sección 4) |
| `domains/health/` | Coherente — es exactamente el contenido de dominio ya diseñado en `003`/`004` (reglas, señales de riesgo, tools de salud) |
| `domains/emergency/`, `domains/sales/`, `domains/citizen/` | Coherentes conceptualmente, pero su contenido específico **no ha sido diseñado todavía** — solo salud fue cubierto hasta ahora |
| `agents/` | Coherente si se entiende como instancias del Cerebro (`003` sección 7) configuradas por dominio |
| `channels/` | Coherente con el campo `canal` de `ConversationState` (`004` sección 2) y el componente CANAL de `003` (sección 4) |
| `knowledge/` | Coherente directamente con `003` sección 9 (estático/dinámico/RAG/externo) |
| `tools/` | Coherente con `003` sección 10 y `004` sección 17 (READ/WRITE/NOTIFY) |
| `memory/` | Coherente con `003` sección 8 y `004` sección 3 (conversación/usuario/resumen) |
| `state/` | Coherente directamente con el `ConversationState` completo de `004` |
| `observability/` | Coherente con `003` sección 14 y `004` sección 13 (auditoría) |

**Hueco detectado**: la estructura propuesta no muestra dónde vivirían los **Guardrails** como componente propio — `003` los trata como componente de primer nivel, no como sub-parte de `core/`. PENDIENTE de decidir cuando se diseñe la implementación real (no se resuelve en esta auditoría).

Conclusión: la estructura es coherente con lo ya diseñado — es la primera vez que esa arquitectura conceptual se traduce a una posible organización de carpetas, pero sigue sin implementarse.

---

## 18. Cambios prohibidos

Confirmado explícitamente que **ninguno** de los siguientes ocurrió durante esta sesión: renombrar `icaco`; mover `icaco`; eliminar `icaco`; modificar código; modificar configuración; modificar Docker; modificar URLs; modificar variables; modificar Dani; modificar `PROJECT-TEMPLATE`; modificar `orangutan-kit`; modificar recados históricos (001-004); hacer commits; instalar dependencias.

---

## 19. Decisión final

**SÍ, CON CONDICIONES.**

Condiciones que deben resolverse antes de ejecutar cualquier cambio real:

1. Confirmar explícitamente que la carpeta física sigue llamándose `icaco` (no cambia en esta fase) — evita romper la memoria de Claude Code.
2. Decidir cómo preservar la trazabilidad histórica en los 2 hits de tipo K (`proteccion-datos-personales.md`) antes de tocarlos — no un simple reemplazo de texto.
3. Decidir la nomenclatura exacta de esta instancia: ¿"ZANTIA" a secas, o "ZANTIA HEALTH" como dominio específico bajo un futuro "ZANTIA CORE"? Esto determina el texto exacto de los 18 hits de tipo A/H.
4. Inicializar git antes de ejecutar cualquier cambio real (hoy no hay ni un commit) — para tener reversibilidad genuina.
5. Confirmar si se desea un recado adicional (`006`) que registre la migración ya ejecutada, separado de esta auditoría previa.

Con esas 5 condiciones resueltas, el cambio a nivel de documentación es de bajo riesgo técnico (no hay código, Docker, URLs ni variables que romper) y puede proceder.

---

## 20. Pendientes

- Confirmar nomenclatura exacta (ZANTIA vs. ZANTIA HEALTH para esta instancia).
- Decidir si/cuándo la carpeta física cambia de nombre (fuera de esta fase).
- Decidir cómo preservar trazabilidad histórica en `proteccion-datos-personales.md`.
- Decidir si `PROJECT-TEMPLATE` debe adoptar el patrón ZANTIA (core + dominios) como base para futuros proyectos — fuera de esta auditoría.
- Inicializar git antes de cualquier cambio real.
- NO CONFIRMADO: cualquier dependencia adicional de Claude Code sobre el nombre del proyecto, no observable desde el filesystem.
- PENDIENTE: contenido real de `domains/emergency`, `domains/sales`, `domains/citizen` — solo `health` fue diseñado hasta ahora (`003`/`004`).
- Si se decide proceder, crear posteriormente un recado `006` con el registro de la migración ya ejecutada.

---

## Potencial de formación

RECOMENDACIÓN de encuadre: esta sección no crea ningún curso ni módulo — identifica, sobre lo que **ya está investigado y escrito** en `002`, `003`, `004` y este mismo `005`, qué partes tienen valor pedagógico real para un futuro "ZANTIA ACADEMY". No se inventa contenido ficticio; donde no hay material real derivable, se dice explícitamente.

### Propiedad del conocimiento

Distinción pedida (instrucción 29), para no mezclar información específica de cliente/proyecto con conocimiento enseñable en general:

- **Conocimiento arquitectónico general** (reutilizable en cualquier curso, no depende de Dani ni de ZANTIA):
  - LLM propone / sistema decide y escribe — `004` secciones 8 y 16.
  - Estado explícito y persistido vs. estado inferido del historial — `003` sección 6, `004` completo.
  - Separación estado / memoria de conversación / resumen / conocimiento, para no duplicar información — `004` sección 3.
  - Jerarquía de fuente de verdad entre conocimiento dinámico y estático — hallado en Dani (`002`), generalizado en `003` sección 9.
  - Guardrails como capa de verificación posterior a la generación del LLM, no como instrucción de prompt — `003` sección 11, `004` sección 16.
  - Idempotencia y concurrencia en agentes con acciones transaccionales — `004` secciones 10-11.
  - Máquina de estados con interrupciones globales priorizadas — `004` secciones 6-7.
- **Conocimiento específico de Dani** (caso de estudio real, no patrón a copiar): las 14 secciones de su system prompt, el workflow de n8n, los hallazgos de la autopsia — sirven como ejemplo real y verificado de un sistema construido casi enteramente "por instrucción", sin guardrails ni estado persistido.
- **Conocimiento específico de ZANTIA** (no generalizable sin adaptar): el dominio salud, los campos `nivel_de_riesgo`/`señal_de_urgencia` con protocolo clínico pendiente, la nomenclatura ZANTIA CORE/HEALTH/EMERGENCY/SALES/CITIZEN.
- **Ejemplos concretos ya construidos**: los dos ejemplos completos de conversación de `004` sección 18 (flujo normal / interrupción de seguridad) — ya tienen forma directa de caso práctico.
- **Procedimientos ya documentados**: el plan de migración de este documento (sección 15, fases A-G) es en sí mismo un procedimiento generalizable — "cómo migrar la identidad de un sistema en producción temprana sin romper nada" — independiente de que el caso concreto sea ICACO→ZANTIA.
- **Patrones reutilizables ya en formato de checklist**: "Qué clonar / Qué adaptar / Qué descartar" (`002`) y la "Matriz Dani → ICACO" (`003` sección 17).

### Decisiones con valor pedagógico ya documentadas

Aplicando el formato pedido (CONCEPTO / PROBLEMA / SOLUCIÓN / DECISIÓN / EJEMPLO / ERROR FRECUENTE / REGLA) solo a las decisiones que de verdad lo ameritan — no a cada detalle:

**1. Estado explícito vs. estado inferido**
- CONCEPTO: el estado de una conversación puede vivir persistido, o puede reconstruirse cada turno leyendo el historial.
- PROBLEMA: si se re-infiere cada vez, información crítica puede "salirse" de la ventana de contexto y perderse.
- SOLUCIÓN: `ConversationState` explícito, con autoridad de escritura restringida (`004` sección 6, 8).
- DECISIÓN: el LLM lee el estado como entrada y propone cambios; nunca lo reconstruye.
- EJEMPLO: en Dani, una confirmación de compra podía "olvidarse" si pasaban más de 8 turnos (`002`).
- ERROR FRECUENTE: confiar en que "el modelo se va a acordar" de algo importante sin persistirlo.
- REGLA: todo dato del que depende una decisión de flujo debe persistirse, no inferirse.

**2. Señal de riesgo como interrupción determinista de máxima prioridad**
- CONCEPTO: una máquina de estados puede tener interrupciones globales, activables desde cualquier estado.
- PROBLEMA: si la interrupción depende solo de que el LLM "la reconozca bien", su fiabilidad no es verificable.
- SOLUCIÓN: `señal_de_urgencia` como booleano evaluado por regla determinista, no por el LLM directamente (`004` sección 2.3).
- DECISIÓN: prioridad fija — riesgo > escalamiento pedido > dato faltante > acción > conversación normal (`004` sección 7).
- EJEMPLO: el escenario resuelto en `004` sección 18 ("dolor en el pecho" interrumpe un flujo de agendamiento en curso).
- ERROR FRECUENTE: usar la misma interrupción global de Dani (señal de compra, para *acelerar*) como si sirviera igual para un caso donde la interrupción debe *proteger*.
- REGLA: toda condición de seguridad crítica se evalúa con código determinista, nunca solo con generalización semántica de un LLM.

**3. Separación de conocimiento dinámico y estático con jerarquía de verdad**
- CONCEPTO: no toda la información que usa un agente cambia con la misma frecuencia.
- PROBLEMA: si todo vive en el mismo prompt/documento, el agente puede alucinar datos que ya cambiaron.
- SOLUCIÓN: dos fuentes separadas, con una regla explícita de cuál gana si hay conflicto (`002`, hallado en Dani; generalizado en `003` sección 9).
- DECISIÓN: "si el dato puede cambiar, va a la fuente dinámica; si es profundidad rara vez consultada, va a la estática".
- EJEMPLO: `get_course_data` (dinámico) vs. `get_detailed_info` (estático) en Dani.
- ERROR FRECUENTE: mezclar ambos tipos de dato en el mismo documento sin jerarquía, confiando en que el LLM "sabrá cuál usar".
- REGLA: todo dato variable tiene una única fuente de verdad, con prioridad explícita sobre lo que el modelo "recuerda".

### Casos de estudio

Mapeo pedido (instrucción 24), usando exclusivamente lo ya investigado:

| Caso | Tipo de caso de estudio | Documento base |
|---|---|---|
| DANI | Agente comercial conversacional real, con debilidades reales documentadas | `002` |
| ICACO | Evolución arquitectónica: de un sistema "por instrucción" a uno con estado/guardrails explícitos | `003`, `004` |
| ZANTIA | Generalización de un agente de un dominio a una plataforma multi-dominio | `005` (este documento) |

El arco narrativo pedido ("Así estaba diseñado → Estos problemas encontramos → Esto aprendimos → Así lo rediseñamos → Esta es la arquitectura resultante") **ya existe, de hecho, distribuido en los documentos actuales** — no hace falta escribirlo de nuevo, solo señalar dónde vive cada etapa:

1. "Así estaba diseñado" → `002`, secciones "Arquitectura completa" y "System Prompt".
2. "Estos problemas encontramos" → `002`, secciones "Debilidades" y "Riesgos".
3. "Esto aprendimos" → `002`, sección "Qué clonar/adaptar/descartar"; `003`, sección 2 ("ADN heredado de Dani").
4. "Así lo rediseñamos" → `003` completo y `004` completo.
5. "Esta es la arquitectura resultante" → `003` + `004` combinados, con su extensión conceptual hacia plataforma multi-dominio en `005`.

INFERENCIA explícita, cumpliendo la instrucción de no ocultar errores: los errores reales ya documentados en `002` (sin estado persistido, sin guardrails de código, sin testing, sin observabilidad, identificadores operativos reales filtrados a plantillas de arranque) son, tal cual están escritos, material educativo legítimo — no requieren ser suavizados ni reformulados para poder enseñarse.

### Evolución del conocimiento

Traza pedida (instrucción 25), marcando qué eslabones ya existen como documento y cuáles son aspiracionales:

```
DANI                          → HECHO, documentado en 002
  ↓
AUTOPSIA                      → HECHO, es 002 en sí mismo
  ↓
ICACO (arquitectura)          → HECHO, documentado en 003
  ↓
CONTRATO DE ESTADO            → HECHO, documentado en 004
  ↓
ZANTIA (identidad + auditoría de migración) → HECHO, documentado en 005 (este documento)
  ↓
PLATAFORMA MULTIAGENTE        → PENDIENTE — no diseñada todavía (ver hueco de "multiagentes"
                                  más abajo); `005` solo evaluó coherencia de nomenclatura,
                                  no diseñó coordinación real entre dominios
  ↓
METODOLOGÍA PROFESIONAL       → PENDIENTE — esta misma sección es el primer paso consciente
                                  hacia ahí, no la metodología en sí
```

### Módulos potenciales de ZANTIA ACADEMY

Evaluación honesta de la lista de 15 módulos propuesta, distinguiendo cuáles ya tienen material real detrás y cuáles son huecos (instrucción 27: "no asumas que esta estructura es definitiva, solo identifica oportunidades reales"):

| Módulo propuesto | Estado del material |
|---|---|
| 1. Fundamentos de agentes de IA | Parcialmente cubierto — conceptos de LLM/orquestador/memoria/tools dispersos en `002` |
| 2. Arquitectura de agentes | Cubierto extensamente — `003` completo |
| 3. Diseño del cerebro | Cubierto — `003` sección 7, más el análisis del prompt de Dani en `002` |
| 4. Estado conversacional | **El más cubierto de todos** — `004` completo |
| 5. Memoria | Cubierto — `003` sección 8, `004` sección 3 |
| 6. Knowledge / RAG | Cubierto solo parcialmente — RAG se menciona conceptualmente (`003` sección 9) pero no se desarrolló en profundidad |
| 7. Tools | Cubierto — `003` sección 10, `004` sección 17 |
| 8. Guardrails | Cubierto — `003` sección 11, `004` secciones 15-16 |
| 9. Orquestación | Cubierto — `003` sección 5, `004` sección 15 |
| 10. Multiagentes | **Hueco real** — ZANTIA como plataforma multi-dominio es todavía solo conceptual (`005`); no existe diseño de coordinación entre agentes de distintos dominios |
| 11. Observabilidad | Cubierto — `003` sección 14, `004` sección 13 |
| 12. Testing | **Hueco real** — solo señalado como ausencia en Dani (`002`) y como principio (`003`), nunca desarrollado como tema propio |
| 13. Seguridad | Cubierto parcialmente — centrado en privacidad/datos (`003` sección 15, `004` sección 14), no en seguridad técnica de infraestructura |
| 14. Deployment | **Hueco real** — icaco no tiene stack ni deployment todavía (`.ai/DEPLOYMENT.md` vacío) |
| 15. Construcción de un agente profesional completo | Prematuro — depende de que exista una implementación real, no solo diseño |

### Material derivable ya identificable (instrucción 28)

- **Clase**: "Por qué un agente necesita estado explícito" — basada en `004` completo, contrastado con `002`.
- **Laboratorio**: "Diseña el `ConversationState` mínimo para un dominio distinto a salud" — usando `004` sección 4 (estado mínimo) como plantilla de partida.
- **Ejercicio**: resolver el escenario de prioridades de `004` sección 7 para un dominio distinto (ej. ventas) — el escenario ya está resuelto para salud, listo para adaptarse como ejercicio.
- **Caso de estudio**: Dani completo (`002`) — ya es, literalmente, un caso de estudio terminado.
- **Diagrama**: los diagramas ASCII de arquitectura (`003` sección 4) y de la máquina de estados (`004` sección 6) — reutilizables directamente como material visual.
- **Checklist**: "Qué clonar/adaptar/descartar" (`002`) y "Errores a evitar" (`004` sección 19).
- **Plantilla**: la tabla de campos de `ConversationState` (`004` sección 2) — reutilizable en blanco para otro dominio.
- **Evaluación**: **no hay material de evaluación derivable todavía** — sería contenido nuevo a crear, no algo ya producido por esta investigación. Se declara honestamente en vez de inventarlo.

### Regla permanente adoptada a partir de este documento

RECOMENDACIÓN, registrando la instrucción 31 como convención vigente desde ahora: toda decisión arquitectónica importante del ecosistema ZANTIA se documenta en dos niveles separados — **documentación técnica** (la ya existente: `.ai/*.md`, recados de arquitectura como `003`/`004`) necesaria para construir y mantener el sistema, y **documentación pedagógica** (esta misma sección, y las que sigan) necesaria para poder enseñar después cómo y por qué se construyó. Ambos niveles no se mezclan dentro del código ni dentro de la documentación técnica operativa — la pedagógica vive aparte. Este documento (`005`) es el primero en aplicar esa separación de forma explícita.
