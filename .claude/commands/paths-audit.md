---
description: Inventario de todas las referencias a una ruta/carpeta antes de moverla — para reorganizar sin romper referencias
argument-hint: "<ruta-o-carpeta-a-evaluar>"
---

Antes de mover, renombrar o reorganizar `$ARGUMENTS`, produce un informe de impacto de solo lectura. No muevas nada todavía.

Busca referencias al nombre literal de `$ARGUMENTS` (y variantes de mayúsculas/minúsculas) en, como mínimo:

- `Dockerfile`(s) — `COPY`, `WORKDIR`.
- Archivos de configuración de build (`alembic.ini`, `vite.config.*`, `tsconfig.json`, `package.json` — `main`, `scripts`).
- Código fuente: imports relativos, construcción de rutas (`os.path.join(__file__, ...)` o equivalente).
- `.env.example` (nombres de variable que parezcan contener una ruta o URL base).
- `.ai/*.md` y `.claude/rules/*.md` — referencias documentadas.
- `docs/operations/` — comandos con rutas relativas asumidas.
- Scripts en `scripts/`.
- Si el proyecto es multi-repo (ver `.ai/ARCHITECTURE.md`): repite la búsqueda en cada repo hermano documentado, no solo en el repo actual.

Para cada referencia encontrada, indica: archivo, tipo de referencia (build context / import / variable de entorno / documentación), y qué se rompería si `$ARGUMENTS` cambia de ubicación sin actualizar esa referencia. Clasifica cada una 🔴/🟠/🟡/🟢 igual que las rutas críticas de `.ai/ARCHITECTURE.md`.

Entrega el informe completo antes de sugerir si el movimiento es seguro. Si se decide proceder, recomienda probar el build/despliegue afectado en una rama aparte antes de fusionar (ver `.claude/rules/proteccion-produccion-y-codigo.md`).
