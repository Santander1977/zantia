---
description: Crea un proyecto nuevo a partir del ADN de PROJECT-TEMPLATE (nunca a partir de otro proyecto existente) — estructura, reglas, agentes, memoria, documentación, aislamiento e inventario inicial
argument-hint: "<nombre-del-proyecto>"
---

Estás creando un proyecto nuevo llamado `$ARGUMENTS` **a partir de `PROJECT-TEMPLATE`**, nunca copiando o clonando otro proyecto existente. Este comando es independiente de cualquier stack tecnológico — no asumas Python, FastAPI, React, Node ni PostgreSQL como obligatorios; el stack lo decide el proyecto nuevo.

## Proceso (los 10 pasos del diseño de workflow)

1. **Nombre + slug**: confirma el nombre exacto y deriva un slug (`kebab-case`, sin acentos, sin espacios) para la carpeta/repo(s).
2. **Tipo de proyecto**: pregunta o confirma con el usuario — ¿es un agente conversacional? ¿una plataforma con API+frontends? ¿una automatización pura? ¿una integración puntual? Esto determina qué partes de la plantilla realmente aplican.
3. **Topología**: pregunta o confirma — ¿monorepo único, o multi-repo desde el día 1? Nunca lo decidas tú por defecto; es una decisión consciente del usuario. Documéntala de inmediato en `.ai/ARCHITECTURE.md` del proyecto nuevo.
4. **Arquitectura inicial**: de las capas (experiencia/aplicaciones/integración/datos/inteligencia), determina cuáles aplican al tipo de proyecto — no todas aplican siempre.
5. **Reglas**: copia `.claude/rules/*.md` de `PROJECT-TEMPLATE` tal cual (son las obligatorias) y pregunta si hay reglas de dominio adicionales a añadir (ej. habeas data, PCI).
6. **Memoria**: copia `.ai/*.md` de `PROJECT-TEMPLATE` **como esqueletos vacíos** — la memoria del proyecto nuevo empieza limpia, nunca hereda contenido de ningún otro proyecto. Copia `docs/CLIENT.local.md.example` y créalo como `docs/CLIENT.local.md` (recordando que queda gitignored) para rellenarlo con el discovery real del cliente nuevo.
7. **Componentes**: crea solo las carpetas/repos que el tipo de proyecto realmente necesita — nunca carpetas vacías especulativas "por si acaso".
8. **Integraciones**: pregunta qué sistemas externos tocará el proyecto (automatización, mensajería, pagos, etc.) y regístralos en `.ai/INTEGRATIONS.md` desde el inicio, aunque todavía no estén implementados.
9. **Testing**: define con el usuario la estrategia mínima viable desde el día 1 (al menos smoke test) y regístrala en `.ai/TESTING.md` — no la pospongas.
10. **Deployment**: documenta en `.ai/DEPLOYMENT.md` dónde y cómo se desplegará, incluso antes del primer deploy real.

## Qué copiar de `PROJECT-TEMPLATE` exactamente

- `.claude/rules/`, `.claude/agents/`, `.claude/commands/` → tal cual, completos.
- `.ai/*.md` → tal cual (ya son esqueletos vacíos).
- `docs/README.md`, `docs/CLIENT.local.md.example` (nunca su contenido, solo la plantilla vacía) y las subcarpetas `architecture/`, `decisions/`, `operations/`, `guides/`, `changelog/`.
- `scripts/verificar-aislamiento.sh` y `scripts/README.md` → tal cual (es genérico, sin nada hardcodeado).
- `.gitignore`, `PROJECT.md`, `README.md`, `CONTRIBUTING.md` → como esqueletos a completar.
- **`tests/validar-plantilla.sh` NO se copia** — es la auto-validación de `PROJECT-TEMPLATE` en sí (antes de su primer uso), no una herramienta que cada proyecto derivado deba cargar indefinidamente. Copia solo `tests/README.md` (explicando que los tests de contrato cruzados viven ahí cuando existan).

## Aislamiento — obligatorio antes de dar por terminada la creación

Ejecuta (o adapta) `scripts/verificar-aislamiento.sh` contra el proyecto recién creado, con los nombres/dominios de otros proyectos conocidos como entrada. Cero resultados esperados. Si aparece algo, detente y corrígelo antes de continuar — nunca entregues un proyecto nuevo con restos de otro.

## Checklist inicial que debes entregar al terminar

- [ ] Estructura creada (solo lo necesario según el tipo de proyecto elegido en el paso 2).
- [ ] `.claude/rules/`, `.claude/agents/`, `.claude/commands/` copiados desde `PROJECT-TEMPLATE`.
- [ ] `.ai/*` presentes como esqueletos vacíos, sin contenido de ningún otro proyecto.
- [ ] `docs/CLIENT.local.md` creado (vacío o con el discovery inicial) y confirmado en `.gitignore`.
- [ ] `PROJECT.md`/`README.md`/`CONTRIBUTING.md` con al menos la identidad básica completada (no en blanco).
- [ ] Checklist de aislamiento ejecutado, cero resultados.
- [ ] Versión de `PROJECT-TEMPLATE` usada, registrada en `PROJECT.md`.

## Lo que nunca haces

- Nunca copias código, datos, credenciales o documentación de ningún proyecto existente hacia el proyecto nuevo.
- Nunca asumes un stack por defecto sin que el usuario lo confirme.
- Nunca creas el proyecto nuevo dentro de otro repositorio existente sin que el usuario lo pida explícitamente — por defecto, nace como carpeta/repo propio, hermano de los demás.
