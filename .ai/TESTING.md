# TESTING — ZANTIA

> Snapshot de qué se prueba, en qué nivel, y qué falta. No es la suite en sí — es el mapa de cobertura.

| Componente | Framework | Niveles cubiertos | Qué falta |
|---|---|---|---|
| `state/` (modelo, store, máquina) | pytest | Unidad (creación, recuperación, persistencia real en SQLite, concurrencia optimista, transiciones válidas/inválidas) | Migración a un motor distinto de SQLite (si se decide) |
| `guardrails/` | pytest | Unidad (bloqueo, escalamiento, modificación de respuesta) | Reglas adicionales cuando exista un dominio real |
| `tools/` | pytest | Unidad (READ, WRITE, idempotencia, error simulado, NOTIFY) | Tools reales de un dominio (hoy son ficticias) |
| `core/orchestrator.py` | pytest | Integración end-to-end (flujo normal completo, interrupción por riesgo, prioridad riesgo>resto, no reprocesar tras escalado, idempotencia de mensaje) | Reintentos de tool con backoff real; `AnthropicBrain` en vivo |
| `observability/` | pytest | Unidad (eventos de transición y guardrail quedan registrados) | Persistencia de eventos entre procesos (hoy es solo en memoria) |

34/34 tests pasando a 2026-09-01 (`.venv/bin/pytest -q`). Ver `/Users/enzoalfonso/recado/006-construccion-zantia.md` para el detalle de qué reproduce cada test respecto a los documentos de arquitectura (002/003/004).

## Mínimos obligatorios (heredados de `PROJECT-TEMPLATE`)

- Todo componente nuevo nace con al menos un test de humo (smoke test).
- Todo contrato consumido por más de un componente tiene al menos una prueba de contrato.

Ver `.claude/rules/testing.md` para el detalle completo de las reglas.

## Estrategia mínima viable para ZANTIA

Framework y niveles de cobertura específicos pendientes hasta elegir el stack. Mínimo acordado el 2026-08-31: al menos un smoke test por componente desde el día en que ese componente nace (sin posponerlo) — sin nivel de cobertura adicional impuesto todavía, a decidir según la criticidad real del dominio conversacional.
