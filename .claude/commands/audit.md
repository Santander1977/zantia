---
description: Auditoría de solo lectura del proyecto — inventario factual completo, sin proponer arquitectura todavía
argument-hint: "[alcance opcional, ej. 'solo el backend' — por defecto audita todo el proyecto]"
---

Ejecuta una auditoría de **solo lectura**. No modifiques, muevas, renombres ni elimines nada. No hagas commit ni push.

Sigue el proceso validado (fase 1 del discovery de dos fases usado en este proyecto):

1. **Raíz real**: confirma la ruta absoluta del proyecto, raíz de git, repos hermanos si los hay (revisa `.ai/ARCHITECTURE.md` primero — si ya documenta una topología multi-repo, verifícala en vez de asumir que sigue igual).
2. **Estructura actual**: inventario de carpetas y archivos relevantes, con propósito de cada componente.
3. **Contrato de ejecución**: cómo se instala, ejecuta en dev, ejecuta en producción, qué puertos/comandos/Dockerfiles existen — sin ejecutar nada que pueda iniciar/detener servicios.
4. **Rutas críticas**: clasifica 🔴/🟠/🟡/🟢 qué archivos rompen el sistema si se tocan sin cuidado.
5. **Memoria e instrucciones de IA**: revisa `.ai/*`, `.claude/rules/*`, `PROJECT.md` — detecta información desactualizada, contradictoria o duplicada frente a lo que encuentres realmente en el código.
6. **Documentación**: clasifica lo que encuentres en `docs/` (activa / histórica / diseño / evidencia / backup / archivo temporal / desconocido).
7. **Archivos sospechosos**: duplicados, `.bak`, versiones v1/v2/v3, temporales — indica qué parecen ser y el riesgo de tocarlos, sin tocarlos.
8. **Dependencias**: mapa de qué componente depende de cuál, basado en lo que encuentres, nunca inventado.
9. **Git y seguridad**: estado, rama, remoto, `.gitignore`, y si hay algún posible secreto en un archivo trackeado — si lo hay, repórtalo como "POSIBLE SECRETO DETECTADO EN: [ruta]", nunca muestres el valor.

Etiqueta cada hallazgo con `[CONFIRMADO]`/`[INFERIDO]`/`[PROPUESTO]`/`[DESCONOCIDO]` (ver `.claude/rules/discovery-antes-de-modificar.md`).

Al terminar: escribe los hallazgos crudos en `.ai/DISCOVERIES.md` (con fecha) y entrega el informe al usuario. No actualices `.ai/ARCHITECTURE.md`/`.ai/CURRENT_STATE.md` todavía — eso es tarea de `/architecture` o de `memory-keeper`, una vez que el usuario confirme qué hallazgos son estables.
