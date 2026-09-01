# DECISIONES — ZANTIA

> Índice de decisiones arquitectónicas activas. El detalle completo de cada una (motivo, alternativas, ventajas/desventajas) vive en `docs/decisions/<slug>.md` — este archivo solo indexa y muestra el estado actual.

Estados posibles: `PROPUESTA` → `PENDIENTE DE APROBACIÓN` → `APROBADA` → `IMPLEMENTADA`. Ninguna decisión pasa a `IMPLEMENTADA` sin haber pasado por `APROBADA` explícitamente por quien tiene autoridad sobre el proyecto.

| ID | Decisión (una línea) | Estado | Detalle |
|---|---|---|---|
| D-1 | Stack del Core MVP: Python 3.9 + pydantic + pytest + `sqlite3` (stdlib) | IMPLEMENTADA | `docs/decisions/d-1-stack-core-mvp.md` |
| D-2 | Conservar el nombre físico de carpeta `icaco` bajo la identidad conceptual ZANTIA | IMPLEMENTADA | `docs/decisions/d-2-nombre-fisico-icaco.md` |
