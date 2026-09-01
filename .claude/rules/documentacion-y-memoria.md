# Documentación y memoria histórica

## Reglas obligatorias

- Todo cambio arquitectónico relevante (nuevo componente, nueva integración, decisión de stack) se refleja en `.ai/ARCHITECTURE.md`/`.ai/DECISIONS.md` en la misma sesión en que se decide, no como tarea pendiente.
- Si el proyecto crece a más de un repositorio, esa topología se documenta en `.ai/ARCHITECTURE.md` desde el momento en que se crea el segundo repositorio — nunca se descubre después por accidente.
- `docs/changelog/` se organiza por período (ej. un archivo por mes) — no se deja crecer un único archivo de historial sin límite.
- Cuando un período de `docs/changelog/` se cierra, su contenido todavía vigente se destila hacia `.ai/CURRENT_STATE.md` (tarea típica del agente `memory-keeper`) — el archivo del período queda como historial de consulta, no como memoria activa.
- Cualquier acción que modifique datos de terceros (clientes, usuarios finales) queda registrada en una tabla/mecanismo de auditoría propio del dominio, no solo en logs de aplicación.
- Toda decisión arquitectónica propuesta usa el formato: decisión, motivo, alternativas, ventajas, desventajas, riesgo, impacto, estado.
- Un cambio que rompe compatibilidad hacia atrás requiere un período de convivencia documentado, salvo aprobación explícita de una ruptura inmediata.
- Todo proyecto creado desde una versión de `PROJECT-TEMPLATE` registra esa versión en `PROJECT.md` desde el día 1; una actualización de la plantilla nunca se aplica retroactivamente en automático (ver el esquema de versionado en `docs/guides/` una vez documentado para este proyecto).

## Origen de estas reglas

En un proyecto real, el historial cronológico único alcanzó un tamaño inmanejable sin ninguna estrategia de rotación, y su hallazgo más importante (la topología multi-repo real del sistema) nunca llegó a destilarse a un lugar corto y siempre vigente — tuvo que reconstruirse por auditoría completa.
