# CORE_REUSABLE_PATTERNS — qué hereda un dominio futuro

> Sucesor con evidencia real del plan `[PROPUESTO]` del recado 033
> (`/Users/enzoalfonso/recado/033-plan-extraer-identidad-al-core-y-adn-heredable.md`).
> Ese recado listaba, en 2026-09-06, lo que *se planeaba* extraer al Core
> "cuando `domains/health/` terminara de estabilizarse". Este documento
> es distinto en un punto importante: cataloga lo que **ya existe,
> probado, en el Core hoy** — no un plan. Se actualiza en el MISMO
> cambio que se agrega o modifica un componente genérico (mismo
> criterio que `.ai/API_CONTRACTS.md`/`.ai/CONVERSATION_COVERAGE.md`).

## Cómo leer esta tabla

Cada fila es un componente de `core/` (o `guardrails/`, que es agnóstico
de dominio por diseño desde su creación) que un dominio nuevo puede usar
TAL CUAL, sin reescribirlo. "Evidencia real" es el dominio (hoy, siempre
`domains/health/`) que ya lo ejercita en producción o con tests reales
— nunca un componente sin ningún uso real se marca como "probado".

| Componente | Qué hace | Evidencia real | Recado |
|---|---|---|---|
| `core/agent_contract.py` (`AgentDefinition`, `build_orchestrator`) | Contrato mínimo para registrar un agente nuevo (Brain + herramientas + configuración) sin código nuevo del Core. | `domains/health/agent.py` lo usa para construir el `Orchestrator` real de ZANTIA. | Prompt maestro sección 8 |
| `core/orchestrator.py` (`Orchestrator`) | Único componente con autoridad para escribir `ConversationState`. Aplica la prioridad de interrupciones (riesgo > escalamiento > dato faltante > acción > conversación normal) y el flujo LLM propone → guardrails validan → orquestador decide/ejecuta → estado persiste. | Corre CADA turno real de ZANTIA. | 004 |
| `core/brain.py` (`Brain` Protocol, `FakeBrain`, `AnthropicBrain`) | Contrato Cerebro↔Orquestador: el Brain SIEMPRE propone (`BrainOutput`), nunca escribe estado directo. | `HealthBrain`/`HealthAnthropicBrain` lo implementan; `FakeBrain` es el default de tests. | 004 |
| `core/config.py` (`ZantiaConfig`) | Config separada del código — solo nombres de variables de entorno. | `domains/health/config.py` sigue el mismo patrón para sus propias variables (`HRMM_BACKEND_*`, `HEALTH_BRAIN_TYPE`). | Prompt maestro sección 17 |
| `core/selection.py` (`SelectionOption`, `SelectionProposer`, `interpret_selection`) | Interpretación de selección asistida por LLM, agnóstica de dominio — el Core nunca sabe qué es una "fecha" ni una "cita"; solo verifica que la propuesta del LLM corresponda EXACTAMENTE a una opción real ya ofrecida. | `domains/health/brain.py`/`gateway.py` lo usan para fecha, horario, reprogramación, y el fallback de menú principal (recados 052/064). | 052 |
| `guardrails/` (`DatoInventadoGuardrail`, `ConfirmacionEstructuradaRequeridaParaWriteGuardrail`, `TipoDePreguntaAlteradaGuardrail`, `FueraDeAlcanceGuardrail`, `OpinionPersonalGuardrail`, `SeleccionAsistidaPorLLMNoVerificadaGuardrail`, etc.) | Capa de verificación agnóstica de dominio sobre lo que un Brain con LLM propone — nunca decide contenido, solo lo verifica contra reglas estructurales. | `domains/health/llm_brain.py` los usa todos contra `HealthAnthropicBrain`. | 037 |
| **`core/timed_state.py` (`TimedStateStore`, `VentanaDeTiempo`, `ModoVentana`) — NUEVO** | Estado con timestamp real + ventana de tiempo configurable, con comportamiento distinto dentro/fuera de la ventana. Ver sección dedicada abajo. | `domains/health/gateway.py` lo usa (recado 076, refactor sin cambio de comportamiento) para el saludo corto de 30 min y el enfriamiento de 2 min tras una despedida. | **076** |

## `core/timed_state.py` — extraído hoy, con evidencia real de 3 recados previos

### Qué resuelve

Un patrón que `domains/health/gateway.py` construyó, sin generalizar,
a lo largo de 4 recados reales:
- **Recado 057**: saludo corto (30 min) si el paciente escribe de nuevo
  poco después de cerrar una interacción.
- **Recado 067**: enfriamiento de 2 minutos tras una despedida formal —
  bloquea cualquier mensaje nuevo, informando el tiempo restante.
- **Recado 069**: el tiempo restante se CALCULA en tiempo real contra
  el timestamp guardado en cada consulta — nunca un cronómetro que se
  actualiza solo.
- **Recado 071**: un camino real (despedida sin conversación abierta)
  nunca armaba el enfriamiento — el hallazgo que confirmó que 2
  mecanismos construidos en momentos distintos sobre la MISMA
  estructura (`_cierre_reciente`) necesitaban auditarse juntos.

Todo esto vivía como `Dict[str, Tuple[datetime, Optional[str], bool]]`
construido a mano, específico de `HealthGateway`. `core/timed_state.py`
extrae la parte genérica: un registro `clave -> (momento real, payload
arbitrario)`, y el cálculo de "¿estoy dentro de esta ventana?" / "¿cuánto
falta?" contra cualquier `VentanaDeTiempo` configurada. El Core nunca
sabe qué es "una cita", "una despedida" ni "un caso" — el dominio decide
qué representa la clave y qué lleva el payload.

### Los dos modos de uso — documentados explícitamente (requisito del recado 076)

`ModoVentana` es metadata puramente descriptiva — `TimedStateStore`
nunca la lee para cambiar su propio comportamiento; es el DOMINIO
llamador quien decide qué hacer al estar dentro de una ventana.

- **`ModoVentana.BLOQUEO`** — dentro de la ventana, no se procesa NADA
  nuevo; el dominio solo informa cuánto tiempo falta. Único modo con
  uso real en producción hoy (el enfriamiento de ZANTIA).
- **`ModoVentana.ABIERTA`** — dentro de la ventana, el contenido nuevo
  SÍ se acepta y se acumula contra el mismo evento, SIN reiniciar el
  plazo original. Sin ningún uso real todavía — previsto para el
  dominio futuro de seguridad ciudadana (ver ejemplo completo abajo).
  El mecanismo YA lo soporta estructuralmente: `actualizar_payload`
  reemplaza el payload de una entrada existente preservando su
  `momento` — confirmado con tests (`tests/core/test_timed_state.py`),
  aunque ninguna lógica de negocio real de ese dominio existe todavía
  en ningún archivo de este proyecto.

Un tercer caso real (el saludo corto de 30 min de ZANTIA) no necesita
declarar ninguno de los dos modos — solo usa `dentro_de_ventana()`
directo para elegir qué texto mostrar, sin bloquear ni acumular nada.
`VentanaDeTiempo.modo` es opcional exactamente por esto.

### Ejemplo de diseño — dominio futuro "seguridad ciudadana" (SOLO diseño, nada implementado)

Flujo pedido explícitamente para documentar (recado 076): crear caso →
confirmar → ventana de 5 minutos ABIERTA para adjuntar evidencia →
cierre formal. Ningún código de este flujo existe todavía — esto es
el diseño de CÓMO se apoyaría en `TimedStateStore`, para cuando se
retome ese proyecto.

```python
# --- Ilustrativo, NO implementado en este proyecto ---

from core.timed_state import TimedStateStore, VentanaDeTiempo, ModoVentana
from datetime import timedelta

VENTANA_EVIDENCIA = VentanaDeTiempo(
    duracion=timedelta(minutes=5), modo=ModoVentana.ABIERTA, nombre="evidencia_caso"
)

# 1. Crear caso: el dominio arma su propio registro de negocio (con su
#    propio store/ID, fuera del alcance de TimedStateStore) y, al
#    CONFIRMARLO, registra el evento temporal:
casos_recientes = TimedStateStore()
casos_recientes.registrar(
    caso_id,
    payload={"evidencia": [], "resumen": "..."},
)

# 2. Mientras `dentro_de_ventana(caso_id, VENTANA_EVIDENCIA)` sea True,
#    cada evidencia nueva que el ciudadano adjunte se acumula SIN
#    reiniciar el plazo:
payload = casos_recientes.obtener_payload(caso_id)
payload["evidencia"].append(nueva_evidencia)
casos_recientes.actualizar_payload(caso_id, payload)

# 3. Pasados los 5 minutos (`dentro_de_ventana` ya False), el dominio
#    decide el cierre formal — con el payload acumulado disponible tal
#    cual quedó, nunca perdido:
if not casos_recientes.dentro_de_ventana(caso_id, VENTANA_EVIDENCIA):
    evidencia_final = casos_recientes.obtener_payload(caso_id)["evidencia"]
    # ... cierre formal real del caso, fuera del alcance de este módulo.
```

**Lo que NO decide `TimedStateStore` en este ejemplo** (a propósito,
mismo principio que el resto del Core): qué es "evidencia" válida, cómo
se almacena de verdad (archivos, base de datos), el texto exacto del
cierre formal, ni cuándo exactamente el dominio decide dejar de aceptar
contenido — todo eso es responsabilidad del dominio futuro, cuando se
construya con evidencia real (mismo criterio que el resto de este
proyecto: nunca inventar comportamiento de negocio sin un caso real
que lo confirme).

## Qué NO se hereda — se reconstruye para cada dominio nuevo

Sin cambios respecto al recado 033, sección 4:

- El **adaptador al sistema externo real** (equivalente a
  `HrmmAppointmentService`) — específico de cada integración.
- El **catálogo de negocio específico** (`CatalogMirror`) — un dominio
  de seguridad ciudadana no tiene "servicios y médicos".
- El **Brain del dominio** (`HealthBrain`) — la máquina de etapas y las
  reglas de negocio son propias de cada dominio.

## Estado del plan original del recado 033 (identidad al Core)

Sigue **`[PROPUESTO]`, sin retomar** — el criterio de "listo para
retomar" de ese recado (un período de uso real sin bugs de conversación
nuevos en `domains/health/`) todavía no se cumple: esta misma sesión
encontró y corrigió hallazgos reales nuevos (recados 070-074). La
extracción de `core/timed_state.py` (este documento) es un caso
DISTINTO — no mueve un mecanismo específico de salud con supuestos
propios del dominio, sino que generaliza un patrón ya estabilizado
(4 recados de evidencia real) y deliberadamente mínimo/sin opiniones de
dominio — el mismo riesgo que motivó "esperar" en el recado 033 no
aplica aquí de la misma forma, pero sigue siendo una decisión que vale
la pena revisar caso por caso, no una regla general de "ya se puede
extraer todo".
