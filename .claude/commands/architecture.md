---
description: A partir de un /audit ya hecho, diseña/actualiza la arquitectura target — capas, dependencias, riesgos, decisiones propuestas. No implementa nada.
argument-hint: "[opcional: qué parte de la arquitectura revisar — por defecto, todo el sistema]"
---

Invoca (o delega en) el agente `project-architect`. Este comando es la fase 2 del discovery de dos fases — asume que ya existe un `/audit` reciente (en `.ai/DISCOVERIES.md` o en la conversación actual). Si no existe, sugiere correr `/audit` primero en vez de improvisar sobre supuestos.

Produce:
1. Mapa de arquitectura actual, distinguiendo qué ya existe `[CONFIRMADO]` de qué se propone `[PROPUESTO]`.
2. Mapa de dependencias entre componentes.
3. Registro de riesgos (ID, riesgo, impacto, probabilidad, componente, evidencia, mitigación, prioridad).
4. Decisiones arquitectónicas propuestas, todas en estado `PROPUESTA` — nunca se auto-aprueban.
5. Roadmap de evolución por fases, cada una con objetivo, riesgos, pruebas y rollback.

Al terminar, actualiza `.ai/ARCHITECTURE.md`, `.ai/RISKS.md` y añade entradas nuevas en `docs/decisions/` para cada decisión propuesta (indexadas desde `.ai/DECISIONS.md`). No modifiques código ni configuración.
