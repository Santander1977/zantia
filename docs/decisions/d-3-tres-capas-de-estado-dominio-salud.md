# D-3 — Tres capas de estado separadas para el dominio salud

**Decisión**: `ConversationState.fase_actual` (Core), `Activity.status` (ciclo de vida grueso) y `Activity.management_status` (progreso granular de gestión) son tres capas de estado independientes, ninguna se infiere de las otras, y solo `domains/health/agent.py` tiene autoridad para escribir las dos últimas.

**Motivo**: el prompt maestro de construcción del agente de demanda inducida (prompt 007, sección 6) exige explícitamente separar el lifecycle de la Activity del estado operacional de la gestión, y determinar qué pertenece al `ConversationState` del Core y qué al dominio, documentando la decisión.

**Alternativas consideradas**:
- **Mapear `management_status` directamente sobre `ConversationState.fase_actual`**: descartada — el Core está diseñado para ser agnóstico de dominio (003, principio 12); forzar 15 valores específicos de salud dentro de la máquina de estados genérica del Core habría acoplado el Core a este dominio, exactamente lo que el prompt 007 prohíbe ("no coloques dentro del Core protocolos médicos específicos").
- **Fusionar `Activity.status` y `Activity.management_status` en un único campo**: descartada — mezclaría un ciclo de vida de alto nivel (¿la unidad de trabajo sigue viva?) con un progreso de gestión de grano fino (¿en qué paso del contacto/reserva/recordatorio está?); son preguntas distintas con audiencias distintas (el sistema originador necesita la primera, la operación interna necesita la segunda).

**Ventajas**: el Core permanece intacto y reutilizable para cualquier dominio futuro; el dominio salud puede tener su propio vocabulario de estado sin negociar con el Core; cada capa es testeable de forma aislada (ver `tests/domains/health/test_activity.py` vs. `tests/state/test_machine.py`).

**Desventajas**: tres fuentes de estado a mantener sincronizadas manualmente (por la capa de orquestación de dominio) en vez de una sola — riesgo de desincronización si `domains/health/agent.py` tiene un error (mitigado con tests de integración end-to-end, ver `tests/domains/health/test_end_to_end.py`).

**Riesgo**: bajo — cubierto por tests; la sincronización es código determinista simple (comparaciones de etapa + resultado de tool), no lógica compleja.

**Impacto**: cualquier dominio futuro (`emergency`, `sales`, `citizen`) debería seguir el mismo patrón — un lifecycle grueso + un progreso granular propios del dominio, nunca forzados dentro de `ConversationState`.

**Estado**: IMPLEMENTADA (2026-09-01) — ver `domains/health/models.py` y `/Users/enzoalfonso/recado/007-agente-demanda-inducida-zantia.md`.
