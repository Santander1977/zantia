# ARQUITECTURA — icaco

> Memoria comprimida, siempre vigente. Se lee completa al empezar una sesión. El detalle largo que no quepa aquí vive en `docs/architecture/`, enlazado desde este archivo — nunca duplicado.

## Identidad rápida

Ver `PROJECT.md` para el contexto completo de negocio. Resumen: agente conversacional (tipo de proyecto confirmado el 2026-08-31; stack aún sin decidir).

## Topología

Monorepo único (decisión confirmada el 2026-08-31, no se asume por defecto).

| Repo | Ruta | Remoto | Rol |
|---|---|---|---|
| icaco | `/Users/enzoalfonso/Orangutan/icaco` | — (aún no inicializado como repo git) | único repo del proyecto |

## Componentes

[Completar cuando se elija el stack — todavía no se ha creado ningún componente de código, solo el andamiaje heredado de `PROJECT-TEMPLATE`.]

| Componente | Tecnología | Rol | Repo/carpeta |
|---|---|---|---|
| | | | |

## Capas (si aplica al tipo de proyecto)

- **Experiencia**: canal conversacional de cara al usuario final (ej. WhatsApp/Telegram u otro — canal exacto pendiente de confirmar, ver `.ai/INTEGRATIONS.md`).
- **Aplicaciones**: lógica del agente conversacional (dominio de negocio pendiente de completar en `PROJECT.md`).
- **Integración**: mensajería externa — ver `.ai/INTEGRATIONS.md`.
- **Datos**: datos de conversación y de contacto de usuarios finales — sujetos a `.claude/rules/proteccion-datos-personales.md`; ver `.ai/DATA_MODEL.md`.
- **Inteligencia**: agente de IA de dominio — se documenta en `.ai/AGENTS.md` solo cuando exista un agente real implementado (por ahora permanece vacío por diseño).

## Dependencias entre componentes

[Completar: diagrama o tabla de quién consume a quién.]

## Rutas críticas

[Completar: qué archivos/carpetas rompen el sistema si se mueven o modifican sin cuidado — clasificar 🔴/🟠/🟡/🟢 igual que en el `/audit`.]
