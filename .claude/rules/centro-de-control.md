# Modo "centro de control"

## Regla obligatoria

Cuando el usuario escriba literalmente "modo centro de control" (o una variante equivalente inequívoca, ej. "entra en modo centro de control"), Claude Code debe:

1. **Leer, en este orden, como fuente de verdad**:
   1. `.ai/RISKS.md`
   2. `.ai/ARCHITECTURE.md`
   3. `.ai/DECISIONS.md`
   4. `.ai/CURRENT_STATE.md` (si existe)
   5. El recado numerado más reciente en `/Users/enzoalfonso/recado/` (el de número más alto)
2. **Es un modo de SOLO LECTURA Y REPORTE** — no construir, no modificar ningún archivo, no ejecutar ninguna acción de escritura (commits, builds, despliegues, cambios de código). Comandos de solo lectura (`git status`, `git log`, `.venv/bin/pytest`) sí están permitidos y son parte esperada de la verificación del punto 4.
3. **Responder SIEMPRE con estos 4 bloques fijos, en este orden, sin bloques adicionales**:
   - **Estado actual**: qué está construido y verificado, con evidencia real (tests pasando con su conteo exacto, commits confirmados con hash) — distinguiendo SIEMPRE lo que corre contra infraestructura real/producción de lo que solo está probado localmente o con fixtures/mocks.
   - **Pendientes bloqueantes**: qué impide avanzar al siguiente paso lógico del proyecto (ej. un webhook sin registrar, un riesgo ABIERTO en `.ai/RISKS.md` que bloquea producción).
   - **Riesgos e incidentes abiertos**: los riesgos de `.ai/RISKS.md` que siguen `ABIERTO` o `PARCIALMENTE MITIGADO` — nunca listar uno `RESUELTO`/`MITIGADO` como si siguiera pendiente.
   - **Próximo paso recomendado**: UNO solo, concreto y accionable, basado en el estado real ya reportado arriba (no una lista de opciones).
4. **Verificar sincronización real antes de reportar, nunca asumirla**: correr `git status` (y `git log --oneline -1` si hace falta comparar contra `origin`) y comparar contra lo que digan los documentos leídos en el paso 1. Si algún archivo de esa lista no existe, o el estado de git (cambios sin commitear, commits no reflejados en la documentación) no coincide con lo documentado, decirlo EXPLÍCITAMENTE dentro del bloque "Estado actual" — nunca reportar como si todo estuviera sincronizado sin haberlo comprobado en esta misma respuesta.

## Origen de esta regla

Instalada el 2026-09-05 a pedido explícito del usuario, replicando la convención de "modo centro de control" que ya funciona en el proyecto hermano HRMM — adaptada a la documentación real de ZANTIA (`.ai/*.md` en vez de los equivalentes de HRMM, y los recados de `/Users/enzoalfonso/recado/` en vez de la fuente de historial que use ese otro proyecto). El propósito es tener un punto de entrada rápido y confiable al estado real del proyecto, sin tener que releer manualmente cada archivo de memoria por separado, y sin arriesgar que un reporte de estado se dé por buena una sincronización entre código/documentación/git que no se comprobó de verdad en esa sesión.
