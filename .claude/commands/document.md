---
description: Destila el trabajo reciente hacia .ai/CURRENT_STATE.md y docs/changelog/ — invoca al agente memory-keeper
---

Invoca al agente `memory-keeper` con el trabajo realizado en esta sesión (o desde la última vez que se ejecutó este comando, lo que sea más reciente) como contexto.

No inventes qué se hizo — básate en `git log`/`git status` reales y en lo efectivamente conversado/ejecutado en la sesión. Si algo no se puede verificar, se marca `[DESCONOCIDO]`, no se asume.

Este comando es el que cierra el ciclo de trabajo — úsalo antes de terminar una sesión que haya generado cambios significativos (nuevo componente, decisión arquitectónica, fix relevante, hallazgo de auditoría), para que la próxima sesión no tenga que reconstruir el contexto leyendo commits o preguntando de nuevo.
