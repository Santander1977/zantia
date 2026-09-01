# ZANTIA

> Identidad del proyecto: qué es, para quién, por qué existe. Debe ser seguro de compartir — nunca contiene secretos ni datos de cliente (esos van en `docs/CLIENT.local.md`, gitignored).

> **Nota de nomenclatura** (2026-09-01): la identidad conceptual de este proyecto cambió de "icaco" a "ZANTIA" — ver `/Users/enzoalfonso/recado/005-migracion-icaco-a-zantia.md` para la auditoría completa de esta migración. La carpeta física del proyecto sigue llamándose `icaco` deliberadamente (esa auditoría concluyó que el nombre conceptual y el nombre físico no tienen que coincidir, y que renombrar la carpeta rompería la memoria de Claude Code ya asociada a esta ruta).

## Qué es este proyecto

ZANTIA es una plataforma de inteligencia agéntica: un Core reutilizable (orquestador, estado conversacional, memoria, conocimiento, tools, guardrails, observabilidad) para crear y operar agentes conversacionales especializados por dominio, en lugar de un agente de un solo dominio construido a medida.

## Para quién

Interno de Orangutan, con primera instancia orientada al dominio de salud (dominio no implementado todavía — ver `domains/health/README.md`).

## Objetivo

Contar con un Core agéntico agnóstico de dominio, ya validado de extremo a extremo con un agente de demostración, sobre el cual se puedan construir dominios reales (salud, emergencias, ventas, atención ciudadana) sin reescribir la orquestación, el estado ni los guardrails en cada uno.

## Tipo de proyecto

Plataforma de inteligencia agéntica (Core multi-dominio). Nació como agente conversacional de un solo dominio bajo el nombre "icaco" — ver `docs/changelog/` y los recados 001-005 para la evolución completa.

## Topología

Monorepo único.

## Stack elegido

Python 3.9 + pydantic (contratos de datos) + pytest (tests) + `sqlite3` de la librería estándar (persistencia del `ConversationState`, sin servidor ni ORM). Elegido para el MVP del Core — ver `/Users/enzoalfonso/recado/006-construccion-zantia.md` para la justificación completa y las alternativas descartadas. El canal de mensajería, el modelo LLM de producción y la base de datos de un futuro dominio real siguen sin decidir.

## Reglas de dominio adicionales

Habeas data / protección de datos personales — ver `.claude/rules/proteccion-datos-personales.md`. El proyecto maneja datos personales de usuarios finales a través del canal conversacional.

## Creado desde

`PROJECT-TEMPLATE`, commit `6fd36c7` (2026-08-31) — no existe todavía un esquema de versionado `vX.Y.Z` documentado en `PROJECT-TEMPLATE` (`docs/guides/` está vacío a esa fecha); se registra el hash de commit como referencia exacta. Ver `.ai/ARCHITECTURE.md` para el ADN heredado y `docs/changelog/` para el historial de este proyecto.
