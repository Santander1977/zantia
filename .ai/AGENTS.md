# AGENTES DE IA — ZANTIA

## agents/demo — agente de demostración del Core

**No es un agente de dominio real** — existe únicamente para validar que el Core (Orchestrator, ConversationState, Memory, Knowledge, Tools, Guardrails, Observability) funciona de extremo a extremo (prompt maestro, sección 27). No debe usarse como base de un dominio real sin rediseñar Brain, Tools y Knowledge para ese dominio.

- **Propósito**: probar el flujo "recibir → interpretar → consultar estado → razonar → validar → ejecutar tool → actualizar estado → registrar eventos → responder" (sección 40).
- **Entradas**: texto libre de un canal genérico (`canal="demo"`), sin canal real conectado.
- **Salidas**: texto de respuesta + `ConversationState` actualizado.
- **Brain**: `FakeBrain` (`core/brain.py`) — determinista, basado en palabras clave, no es NLU real.
- **Herramientas**: `get_demo_info` (READ), `schedule_event` (WRITE, idempotente), `notify_team` (NOTIFY) — todas con datos ficticios (`tools/demo_tools.py`).
- **Fuente de verdad**: `InMemoryKnowledgeSource` con datos ficticios (`knowledge/fixtures.py`).
- **Permisos**: ninguna tool WRITE se ejecuta sin `consentimiento_datos = true` en el estado (verificado por `guardrails/rules.py:ConsentimientoRequeridoParaWriteGuardrail`).
- **Riesgos**: ninguno real — es un demo con datos ficticios, sin conexión a ningún sistema externo.
- **Cuándo delega / pide intervención humana**: ante una señal de riesgo (palabras clave genéricas de ejemplo en `core/brain.py:RISK_KEYWORDS_DEMO`) escala de inmediato a `ESCALADO_URGENTE`, sin excepciones ni preguntas adicionales — ver `core/orchestrator.py`.

## Agentes de dominio real

Ninguno implementado todavía. `domains/{health,emergency,sales,citizen}/` contienen solo el contrato (`domains/contract.py`) — documentar aquí cada uno cuando exista, con el mismo formato de arriba.
