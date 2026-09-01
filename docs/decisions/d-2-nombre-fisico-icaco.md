# D-2 — Conservar el nombre físico de carpeta `icaco` bajo la identidad conceptual ZANTIA

**Decisión**: la carpeta física del proyecto permanece en `/Users/enzoalfonso/Orangutan/icaco`, sin renombrarse, mudarse ni recrearse, aunque la identidad conceptual y de producto pasó a ser "ZANTIA".

**Motivo**: auditoría de migración de identidad (`/Users/enzoalfonso/recado/005-migracion-icaco-a-zantia.md`) encontró que Claude Code deriva automáticamente su carpeta de memoria/sesión (`~/.claude/projects/-Users-enzoalfonso-Orangutan-icaco/`, que ya contiene el protocolo RECADO guardado) del nombre físico exacto de la ruta del proyecto. Renombrar la carpeta huerfanaría esa memoria.

**Alternativas consideradas**:
- **Renombrar la carpeta física a `zantia`**: descartada por ahora — requeriría coordinar el cierre de la sesión activa, migrar manualmente la memoria de Claude Code, y verificar que ninguna sesión quede huérfana; no es una operación de "construcción", es un procedimiento aparte, fuera del alcance de esta fase (ver plan de migración en `005`, sección 15, Fase E).
- **Crear una carpeta nueva `zantia/` y mover el contenido**: descartada — mismo problema de raíz (pérdida de memoria de sesión), además de duplicar temporalmente el proyecto.

**Ventajas**: cero riesgo de romper la sesión de trabajo actual ni la memoria ya guardada; el cambio de identidad conceptual (que es lo que de verdad importa de cara al producto/negocio) procede sin bloquear en esta decisión técnica.

**Desventajas**: cierta disonancia entre el nombre físico (`icaco`) y el nombre de producto (`ZANTIA`) — mitigada documentándolo explícitamente en `PROJECT.md`, `README.md` y aquí, para que nadie lo confunda con un descuido.

**Riesgo**: bajo — es puramente una decisión de nomenclatura, reversible en cualquier momento futuro si se decide ejecutar el renombrado físico siguiendo el procedimiento ya diseñado en `005`.

**Impacto**: ninguna ruta, import de Python, ni configuración de este proyecto depende del nombre "icaco" como string (confirmado en la auditoría `005` — cero identificadores técnicos encontrados); el único acoplamiento real es la ruta física en sí, que esta decisión precisamente preserva intacta.

**Estado**: APROBADA e IMPLEMENTADA (2026-09-01, por instrucción explícita del prompt maestro de construcción: "NO renombres físicamente esta carpeta").
