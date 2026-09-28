# Recados de ZANTIA

Documentos de intercambio numerados, uno por investigación o cambio relevante. **No son documentación oficial**: la memoria vigente del proyecto vive en `.ai/` y las decisiones en `docs/decisions/`. Aquí queda el historial sesión por sesión.

- Hasta el 2026-09-28 vivían en una carpeta compartida fuera del repo (`/Users/enzoalfonso/recado/`), mezclados con recados de otros proyectos. Ese día se movieron aquí los de ZANTIA (003–093) a pedido del usuario, después de que dos sesiones de proyectos distintos crearan un `092` cada una el mismo día.
- La numeración continúa desde el número más alto de esta carpeta.

## Números que no tienen archivo aquí

| Número | Estado | Evidencia |
|---|---|---|
| 001, 002 | Existen, pero **no están aquí**: auditorías del agente previo "Dani", clasificadas como multi-proyecto. Siguen en `/Users/enzoalfonso/recado/`, con destino pendiente de decisión. | Las lecciones que el código cita como "(002)" salen de ahí. |
| 017, 018, 019 | **Nunca existieron**: salto de numeración, no trabajo perdido. | Ningún recado, commit ni archivo los menciona. 016 y 020 se crearon con dos minutos de diferencia (2026-09-03). |
| 077 | Existe, pero es **de hrmm** y se quedó en `/Users/enzoalfonso/recado/` (lo cita `channels/web_channel.py`). | — |
| 081 | **El número existió, pero el documento se perdió.** No se reconstruyó a propósito. | El trabajo sí se hizo: commit `43dc026` ("no confirmar envío de código de verificación cuando hrmm-backend dice enviado=false (recado 081)"), citado también por los recados 082 y 083. |
| 088–091 | Son **de hrmm** y se quedaron en `/Users/enzoalfonso/recado/`. | — |

El 092 que vive en `/Users/enzoalfonso/recado/` (`092-investigacion-numeracion-duplicada-…`) es de hrmm. El 092 de ZANTIA es `092-especificacion-extraccion-patrones-ia-a-paquete-reutilizable.md`, en esta carpeta.

## Número con dos archivos

- **036**: `036-tolerancia-a-errores-de-tipeo-en-eleccion-de-servicio.md` es el recado principal. `036-mensajes-ambiguedad-texto-exacto.md` es su apéndice generado por script (así lo confirma la auditoría del recado 061); no es un duplicado.
