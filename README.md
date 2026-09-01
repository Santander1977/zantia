# ZANTIA

> Quick-start técnico para un desarrollador nuevo. `PROJECT.md` explica el qué/para quién/por qué; este archivo explica el cómo correrlo. La carpeta física de este proyecto se sigue llamando `icaco` a propósito — ver la nota de nomenclatura en `PROJECT.md`.

## Requisitos

Python 3.9+ (se probó con 3.9.6).

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Ejecución (desarrollo)

No hay todavía un canal ni un servidor expuesto (decisión pendiente — ver `.ai/INTEGRATIONS.md`). Para probar el Core manualmente:

```python
from agents.demo.agent import build_demo_agent

orquestador = build_demo_agent()
resultado = orquestador.handle_message("conv-1", "demo", "msg-1", "quiero programar un evento")
print(resultado.response)
```

## Ejecución (tests)

```bash
.venv/bin/pytest -q
```

## Estructura del proyecto

Ver `.ai/ARCHITECTURE.md` para el mapa completo. Resumen rápido:

- `core/` — Orchestrator, Brain, configuración, contrato de agente
- `state/` — `ConversationState`, máquina de estados, persistencia (SQLite)
- `memory/`, `knowledge/`, `tools/`, `guardrails/`, `observability/` — mecanismos reutilizables del Core
- `agents/demo/` — agente de demostración (no es un dominio real)
- `domains/{health,emergency,sales,citizen}/` — contratos de dominio, todavía sin implementar
- `channels/` — contrato de canal, sin implementación real (canal aún no decidido)
- `tests/` — suite de pruebas (`.venv/bin/pytest -q`)
- `.ai/` — memoria comprimida para Claude Code (arquitectura, estado actual, decisiones, contratos, riesgos)
- `.claude/` — reglas, agentes y comandos de Claude Code para este proyecto
- `docs/` — documentación humana extendida (arquitectura, decisiones, operaciones, guías, historial)
- `docs/CLIENT.local.md` — contexto y credenciales del cliente (gitignored, se crea localmente desde `docs/CLIENT.local.md.example`)

## Documentación

- Contexto de negocio: `PROJECT.md`
- Arquitectura: `.ai/ARCHITECTURE.md`
- Cómo contribuir: `CONTRIBUTING.md`
