# Guía de contribución — icaco

## Flujo de trabajo

[Completar: convención de ramas, por ejemplo `feature/<area>/<descripcion-corta>`.]

1. Actualizar la rama base antes de empezar.
2. Crear rama nueva con el prefijo acordado.
3. Commits pequeños y descriptivos (qué cambia y por qué, no solo "fix").
4. Abrir Pull Request — no hacer push directo a la rama principal salvo que el equipo decida lo contrario explícitamente.
5. Esperar revisión antes de mergear.

## Reglas heredadas de `PROJECT-TEMPLATE`

Este proyecto hereda las reglas obligatorias de `.claude/rules/` (protección de producción, contratos API, secretos, testing, aislamiento, documentación) más una regla de dominio adicional propia de `icaco`: protección de datos personales / habeas data (`.claude/rules/proteccion-datos-personales.md`). Ver cada archivo en `.claude/rules/` para el detalle — no se repiten aquí para evitar que este archivo quede desactualizado frente a la fuente real.

## Seguridad y credenciales

- Nunca exponer API keys, tokens o contraseñas en código, commits, PRs o logs.
- Las credenciales de este proyecto viven en `docs/CLIENT.local.md` (gitignored) y/o en el gestor de secretos de la plataforma de despliegue — nunca hardcodeadas.
- Antes de un push, revisar el propio diff si se tocó algún archivo de configuración.
