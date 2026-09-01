# docs/ — documentación humana extendida

Este `docs/` es el archivo humano, exhaustivo y bajo demanda — distinto de `.ai/`, que es la memoria comprimida que se lee completa cada sesión. Regla: nunca duplicar contenido entre ambos — `.ai/*.md` resume y enlaza aquí cuando el detalle no cabe en una lectura rápida.

## Estructura

- **`CLIENT.local.md`** (gitignored, se crea desde `CLIENT.local.md.example`) — contexto y credenciales del cliente/proyecto. Nunca se commitea.
- **`architecture/`** — detalle largo de arquitectura que no cabe en `.ai/ARCHITECTURE.md` (diagramas, exploraciones, comparativas de stack).
- **`decisions/`** — un archivo por decisión arquitectónica (formato ADR: decisión, motivo, alternativas, ventajas/desventajas, riesgo, impacto, estado). `.ai/DECISIONS.md` solo indexa.
- **`operations/`** — runbooks, guías de instalación, troubleshooting, cómo desplegar y cómo hacer rollback.
- **`guides/`** — guías para humanos: onboarding, convenciones de código, cómo contribuir en detalle.
- **`changelog/`** — historial cronológico completo, un archivo por período (ver `.claude/rules/documentacion-y-memoria.md`). Se destila hacia `.ai/CURRENT_STATE.md` cuando un período se cierra.

## Origen de este ADN

Esta estructura y las reglas que la acompañan fueron destiladas de la auditoría arquitectónica de un proyecto real de Orangutan ya en producción, generalizando los mecanismos que resolvieron problemas concretos (memoria en capas, providers intercambiables, auth de dos niveles, discovery en dos fases) y descartando todo lo específico de ese dominio de negocio. `PROJECT-TEMPLATE` es completamente independiente de ese proyecto de origen y debe seguir siendo usable sin ninguna referencia a él.
