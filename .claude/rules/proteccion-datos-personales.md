# Protección de datos personales (habeas data)

> Regla de dominio adicional a las obligatorias de `PROJECT-TEMPLATE`, añadida en la creación de `icaco` porque el proyecto es un agente conversacional que procesa mensajes y datos de usuarios finales reales.

## Reglas obligatorias

- Todo dato personal capturado por el canal conversacional (nombre, teléfono, identificación, contenido de la conversación) tiene un propósito explícito documentado antes de recolectarse — nunca se recolecta "por si sirve después".
- El usuario final tiene siempre disponible, dentro del propio flujo conversacional, la forma de saber qué datos se guardan de él y de pedir su eliminación o corrección — no basta con que exista solo en un documento legal externo.
- Ningún dato personal se reenvía a un sistema externo (integración de mensajería, automatización, analítica) sin que ese destino esté registrado en `.ai/INTEGRATIONS.md` con su propósito.
- Se define una política de retención explícita por tipo de dato (cuánto tiempo se conserva una conversación, un dato de contacto) antes de tener usuarios reales en producción — se documenta en `.ai/DATA_MODEL.md`.
- Cualquier acceso, exportación o eliminación de datos de un usuario final queda registrado en el mecanismo de auditoría del proyecto (ver `.claude/rules/documentacion-y-memoria.md`), no solo en logs de aplicación.
- La jurisdicción/marco legal exacto aplicable (ej. Ley 1581 de 2012 en Colombia, u otro según dónde operen los usuarios finales) se confirma explícitamente con el usuario/cliente y se documenta aquí o en `docs/CLIENT.local.md` — nunca se asume.

## Origen de esta regla

Añadida al crear `icaco` con `/new-project`: el tipo de proyecto (agente conversacional) implica manejo directo de datos personales de usuarios finales desde el primer mensaje, por lo que la protección de datos no puede quedar pospuesta como "tarea futura".
