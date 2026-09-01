# Fuente de verdad

## Regla obligatoria

Para cada dominio de datos relevante del proyecto (ej. "clientes", "pedidos", "usuarios"), debe existir una respuesta explícita y documentada a la pregunta "¿quién manda sobre este dato?" — en `.ai/DATA_MODEL.md`. Nunca se asume que la respuesta es obvia.

## Por qué es obligatoria

Un dominio sin fuente de verdad documentada tiende a duplicarse silenciosamente: dos tablas, dos servicios o dos archivos de configuración terminan respondiendo la misma pregunta de forma distinta, y nadie lo nota hasta que algo falla en producción.

## Cómo aplicarla

- Antes de crear una tabla, servicio o archivo de configuración nuevo, verificar si ya existe algo que cumple ese rol.
- Si dos elementos parecen cubrir el mismo dominio con nombres similares, documentar explícitamente la distinción en `.ai/DATA_MODEL.md` (qué representa cada uno, por qué son distintos) — no dejarlo implícito.
- Si de verdad son duplicados accidentales, proponerlo como decisión en `docs/decisions/` (nunca resolverlo de forma silenciosa sin que quede registrado).

## Origen de esta regla

Encontrada como hallazgo real durante la auditoría de un proyecto en producción: dos tablas distintas en dominios diferentes, ambas llamadas conceptualmente igual (el mismo sustantivo de negocio), con propósitos distintos pero sin ninguna documentación que aclarara la diferencia — fuente real de confusión para cualquier persona nueva en el proyecto.
