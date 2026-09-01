# Discovery antes de modificar

## Regla obligatoria

Antes de diseñar, planear o modificar cualquier componente de este proyecto, se debe comprender su estado real — nunca asumirlo. "Comprender" significa leer el código/configuración real, no inferir desde el nombre de un archivo o desde lo que un proyecto similar suele hacer.

## Clasificación obligatoria de toda afirmación técnica

Toda afirmación relevante que Claude Code haga sobre este proyecto (en `.ai/*`, en `docs/decisions/*`, o en una respuesta al usuario sobre arquitectura) se etiqueta con una de estas cuatro marcas:

- **`[CONFIRMADO]`** — verificado leyendo el archivo/comando directamente en esta sesión.
- **`[INFERIDO]`** — conclusión razonable a partir de evidencia indirecta (nombres, comentarios, patrones consistentes) — nunca se presenta como si fuera `[CONFIRMADO]`.
- **`[PROPUESTO]`** — arquitectura o cambio futuro, explícitamente no implementado todavía.
- **`[DESCONOCIDO]`** — no hay evidencia suficiente reunida; se dice explícitamente que no se sabe, en vez de rellenar el hueco con una suposición razonable.

## Prohibición explícita

- Nunca inventar una arquitectura, un contrato de API, o un dato de configuración que no se haya verificado o que no esté marcado `[PROPUESTO]`.
- Nunca presentar un `[INFERIDO]` como `[CONFIRMADO]` para que una respuesta suene más segura de lo que realmente es.
- Ante la duda entre investigar más o asumir, siempre investigar más — o marcar `[DESCONOCIDO]` y preguntar.

## Origen de esta regla

Extraída de un proceso de discovery en dos fases (auditoría de solo lectura → arquitectura target) aplicado con éxito en un proyecto real — separar "lo verificado" de "lo inferido" evitó que la arquitectura target propuesta se construyera sobre supuestos no confirmados.
