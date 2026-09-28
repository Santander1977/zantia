# 034 — Nombre del paciente, tono genuinamente humano, y evidencia de despliegue desactualizado

**Fecha**: 2026-09-06
**Continúa**: recados 026-033 (misma conversación real de Telegram + plan a futuro)
**Pendiente de aprobación de tono antes de commitear** — mismo proceso que recados anteriores.

## PARTE 1 — ¿Por qué persiste el síntoma si el fix ya está en `main`?

### No pude confirmar el commit desplegado — necesito que lo confirmes tú

No tengo ninguna herramienta que consulte EasyPanel directamente en esta sesión. Reviso a diario: sí puedo decir con certeza que `fdd94a9` (recado 032) está en `origin/main` (confirmado con `git ls-remote` en la sesión anterior), pero **no puedo saber si el servicio real corriendo en EasyPanel ya reconstruyó la imagen a partir de ese commit**, o si sigue corriendo una imagen más vieja. Por favor confirma en el panel (historial de despliegues → hash del build activo) o dispara un redeploy manual si EasyPanel no lo hace automáticamente en cada push — muchas plataformas de este tipo NO auto-despliegan sin un webhook configurado explícitamente, y no hay evidencia en este repo de que ese webhook exista.

### Evidencia real que apoya la hipótesis de "despliegue desactualizado" — no un bug de código nuevo

`[CONFIRMADO con una llamada real, de solo lectura]`: consulté de nuevo `GET /api/agenda/citas?documento_paciente=72302972` — apareció una **segunda** cita real con la firma exacta de una reserva creada por el flujo inbound de ZANTIA (sin nombre/teléfono):

```
CITA-b1d3def03d | fecha=2026-09-07 07:30 | servicio=Pediatria | estado=agendada | creada=2026-09-06T07:17:42
```

Cronología exacta:
- Commit `fdd94a9` (el fix) se pusheó a las **07:08:36 UTC** (`git log`, timestamp del commit).
- Esta cita se creó a las **07:17:42 UTC** — **9 minutos después** del push.
- `estado = "agendada"` — el mismo valor que el fix acaba de aprender a reconocer como éxito.

Si el servicio desplegado ya tuviera el fix, esta reserva debería haberse confirmado normalmente. El hecho de que la reserva se haya completado de verdad (otra vez) pero SIN confirmación es exactamente el síntoma que el fix ya corrige y que ya está probado — la explicación más simple y más coherente con la evidencia es que el contenedor en EasyPanel, 9 minutos después del push, todavía no había reconstruido la imagen. No encontré ningún otro camino de código nuevo que explique el mismo síntoma exacto — no significa que sea imposible, pero no hay evidencia de ello, y la evidencia de despliegue es más directa.

**Recomendación concreta**: antes de seguir invirtiendo en más diagnóstico de código, confirma/dispara el redeploy en EasyPanel y repite la prueba. Si el síntoma persiste CON el commit confirmado como desplegado, eso sí ameritaría logging temporal en producción (mismo patrón ya usado para el bug del webhook de Telegram, recado 023) — no se hizo en esta sesión porque haría falta saber primero si el código que corre es el que se está diagnosticando.

### 🔴 Segunda cita de prueba real que también convendría cancelar

`CITA-b1d3def03d` (2026-09-07 07:30, Pediatría, Consultorio 3, `estado=agendada`, sin nombre/teléfono) es, con la misma evidencia que la anterior (`CITA-4f8220b68f`, ya cancelada en el recado 032), un artefacto real de esta sesión de pruebas — no de un paciente real. Igual que la vez anterior, no la cancelé por mi cuenta: es una escritura real contra producción que requiere tu autorización explícita y el código de verificación llegaría a tu correo. Avísame si querés que la cancele con el mismo mecanismo.

## PARTE 2 — Nombre del paciente

### Diagnóstico confirmado

`identity_store.py` solo guardaba `telefono, documento, estado, verificado_en` — nunca el nombre, pese a que `buscar_paciente` (ya consultado durante el wizard de verificación) sí lo devuelve (`{"nombre_paciente":..., "telefono":...}`). Se descartaba en el camino.

### Decisión: se guarda UNA SOLA VEZ, nunca se re-consulta

Se agregó `IdentidadCanal.nombre: Optional[str]`, persistido en el momento de `marcar_verificado` (el único punto que escribe VERIFICADO) — nunca se vuelve a llamar a `buscar_paciente` solo para saludar en una conversación futura. Migración defensiva incluida (`ALTER TABLE ... ADD COLUMN`, con manejo explícito de "la columna ya existe" para una tabla recién creada) — por si el `ZANTIA_IDENTIDAD_DB_PATH` real ya tiene filas persistidas de antes de este recado.

### Dónde aparece el nombre (sin sobreusarlo)

1. **Saludo de reconocimiento automático** — un paciente con una fila `identity_store` ya VERIFICADA y vigente (nunca repite el wizard) ahora escucha: `"¡Hola, {nombre}! {resto de la respuesta normal}"`. Se calcula una sola vez, en el momento exacto en que se reconoce (no se repite en turnos siguientes de la misma conversación — verificado con test).
2. **Confirmar identidad por primera vez** (justo tras el wizard): `"¡Gracias, {nombre}! Ya confirmé tu identidad..."` en vez del genérico.
3. **Al reservar**: `"¡Perfecto, {nombre}! Dame un segundo, voy a dejarlo reservado."` (nunca se repite el nombre en el texto de confirmación que se concatena después, en el mismo turno — evita sobreusarlo dentro de un mismo mensaje).
4. **Al declinar** (despedida): `"Entiendo perfectamente, {nombre} — gracias por tu tiempo. Si más adelante cambias de opinión, aquí voy a estar."`

Sin nombre disponible (`MockAppointmentService`, o un paciente cuyo `buscar_paciente` no trae nombre), todos estos mensajes caen exactamente a la redacción genérica de antes — cero cambio de comportamiento.

## PARTE 3 — Tono genuinamente humano: variantes que rotan

### Mecanismo

Determinista, no al azar (mismo criterio de todo el archivo: palabras clave, nunca NLU real) — un contador en `datos_recopilados` avanza cada vez que se dispara ese tipo de fallback, y `variantes[contador % len(variantes)]` elige cuál usar. Con esto, dos equivocaciones seguidas del paciente en la MISMA conversación nunca reciben literalmente la misma frase — confirmado con test (`test_dos_fallbacks_de_si_no_seguidos_no_repiten_la_misma_frase`).

### Ejemplos — para tu aprobación

**Aclaración de sí/no** (3 variantes, rotan en este orden):
1. "No logré entender si es un sí o un no — ¿me confirmas si quieres que te ayude a agendar tu atención?"
2. "Vi tu mensaje, pero no me quedó claro si es un sí o un no — ¿podrías confirmármelo con esa palabra, así te ayudo a agendar?"
3. "Perdona, no logré identificar si tu respuesta es un sí o un no — ¿me lo confirmas así puedo seguir ayudándote a agendar?"

**Servicio no identificado** (2 variantes):
1. "No logré identificar cuál de estos prefieres: {opciones}. ¿Me confirmas el nombre tal como aparece en la lista?"
2. "Perdona, no reconocí cuál de estos servicios quieres: {opciones}. ¿Me lo repites tal cual aparece ahí?"

**Selección de turno no identificada** (2 variantes):
1. "No logré identificar cuál prefieres — ¿me confirmas si es la 1, la 2 o la 3?"
2. "No estoy seguro de haber entendido cuál elegiste — ¿me dices si es la 1, la 2 o la 3?"

La variante #2 de "aclaración de sí/no" reconoce explícitamente que el paciente escribió algo ("Vi tu mensaje...") — pedido explícito #2 del usuario — sin citar el texto literal (evita problemas con mensajes muy largos o con caracteres inesperados).

### "Voy a reservarlo — dame un momento"

Reescrito a `"¡Perfecto[, {nombre}]! Dame un segundo, voy a dejarlo reservado."`, seguido en el MISMO mensaje (turno síncrono, la confirmación real llega en el mismo turno desde el recado 032) por `"¡Listo! Quedó confirmado: ..."` — leído completo: *"¡Perfecto, Enzo! Dame un segundo, voy a dejarlo reservado. ¡Listo! Quedó confirmado: medicina general el 2026-09-10 a las 09:00 en Consultorio 3."* — se lee como alguien que narra su propia acción rápida y vuelve con el resultado, no como una promesa que quede suspendida (eso depende de que la Parte 1 esté resuelta en producción, no de la redacción).

## Garantías de fondo — sin cambios

Ningún guardrail, verificación de identidad, ni lógica de negocio se tocó — confirmado con `test_guardrail_de_promesa_de_contacto_sigue_intacto` (nuevo) y la suite completa de guardrails/identidad sin cambios.

## Verificación

- 8 tests nuevos (`tests/domains/health/test_nombre_y_tono_humano.py`): ciclo completo con nombre, saludo solo para paciente ya persistido (nunca para uno nuevo), el saludo no se repite en el turno siguiente, dos fallbacks seguidos no repiten frase, la rotación de 3 variantes es real (no solo "una vez distinto"), una variante reconoce el mensaje del paciente, y el guardrail de promesa de contacto sigue intacto.
- Suite completa: **226 tests pasando + 2 deshabilitados a propósito** (antes de esta sesión: 218). Cero regresiones.
- Tests de identidad/guardrails corridos explícitamente por separado: 27 pasando + 1 deshabilitado.

## Pendiente de tu respuesta

1. **Confirmar/disparar el redeploy en EasyPanel** y repetir la prueba real — es el paso más urgente y el más probable de resolver el síntoma sin ningún cambio de código adicional.
2. **¿Cancelo `CITA-b1d3def03d`** (segunda cita de prueba real, mismo mecanismo que la anterior)?
3. **Aprobar el tono** de las variantes de arriba antes de commitear — mismo proceso que los recados 027/028.
