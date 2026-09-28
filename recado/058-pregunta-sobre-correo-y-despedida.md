# 058 — Pregunta sobre el correo recién enviado + despedida real, en el detector centralizado

**Fecha**: 2026-09-07
**Estado**: Implementado y probado. 480 passed, 8 skipped (468 previas + 12 nuevas). Cero regresiones. **Pendiente de tu aprobación de tono antes de comitear**, tal como pediste.

---

## Reproducción exacta de tu transcripción

```
1. "...Te enviamos un correo de confirmación con todos los detalles."
2. Paciente: "confirmame si me enviastes el email"
   → Antes: saludo corto + directo a preguntar servicio (arrancaba una reserva nueva).
   → Ahora: "Buena pregunta — ese mensaje es un texto automático que te muestro apenas tu
     cita queda registrada, pero hoy no tengo forma de confirmarte si el correo específico
     ya llegó a tu bandeja. Si no te llegó, avísame y lo revisamos con el equipo."
3. Paciente: "no gracias ya termine"
   → Antes: "No logré identificar cuál de estos prefieres: ... ¿Me confirmas el nombre tal
     como aparece en la lista?"
   → Ahora: "¡Con gusto! Que tengas buen día. Aquí estaré si necesitas algo más."
```

## Hallazgo adicional encontrado verificando la reproducción EXACTA (corregido en el mismo trabajo)

Al reproducir los 3 turnos seguidos (no cada uno por separado), la respuesta al correo (turno 2) funcionaba, pero la despedida INMEDIATAMENTE después (turno 3) seguía fallando. Causa: la ventana de gracia de un turno (recado 050, `gateway._recien_cerrada`) es de **un solo uso** — se consume (`pop`) en cuanto se evalúa, sin importar el resultado. El turno 2 la consumió, así que el turno 3 ya no tenía ninguna ventana que reevaluar y cayó al enrutamiento normal de "solicitud nueva".

**Corregido**: la ventana se **re-arma** cuando la interrupción detectada deja la etapa exactamente igual que antes de evaluarla (el caso de "quedarse donde estaba" — info no autorizada, pide info, consultar mis citas, la nueva pregunta sobre el correo) — nunca para las categorías de un solo turno a propósito (humano, no puede ahora, la nueva despedida) ni para la que abre un wizard completo (beneficiario, que ya reabre la conversación por su cuenta). Esto permite que una cadena de varios mensajes "de cortesía" tras un cierre se siga reconociendo correctamente, sin arrancar nunca una solicitud nueva por accidente.

## Diseño

Ambas categorías nuevas viven en el MISMO detector centralizado ya existente (`HealthBrain._detectar_interrupcion_de_contexto`, recados 047/053) — nunca un segundo camino de código, tal como pediste explícitamente (lección del recado 057).

### Categoría 1 — Pregunta sobre la acción recién completada

Reconoce variantes reales, incluida la forma coloquial "enviastes" (typo común, sin conjugación correcta) además de "enviaste": *"me enviaste/enviastes el correo/email"*, *"llegó/me llegó el correo/email"*, *"recibí el correo/email"*, *"confirmame si me enviaste/enviastes/llegó"*.

**Respuesta honesta, no una promesa reafirmada**: investigué si el recado 054 (envío real del correo de confirmación) ya se había implementado — **sigue sin implementarse** (`.ai/RISKS.md` R-21, y el propio recado 054 siguen abiertos: `HrmmAppointmentService.book_appointment` nunca envía `correo`, y ZANTIA nunca llama a `POST /citas/{id}/enviar-confirmacion`). Implementar esa capacidad completa (capturar el correo del paciente en la conversación, dispararlo, verificarlo) es un trabajo separado y más grande que este recado — por eso la respuesta de esta categoría es honesta sobre la limitación ACTUAL, en vez de fingir haber resuelto algo que no se resolvió: nunca dice "sí, se envió" como un hecho verificado.

`etapa`/`datos` no cambian — el paciente sigue disponible para lo que diga después.

### Categoría 2 — Despedida / dar por terminada la conversación

Reconoce combinaciones de 3+ palabras (nunca "gracias" o "listo" solas, para evitar falsos positivos sobre un agradecimiento de paso): *"no gracias ya termine"*, *"ya terminé"*, *"eso es/sería todo"*, *"nada más por ahora"*, *"listo, así está bien"*, *"ya no necesito más"*, etc. — comparadas sobre texto SIN puntuación, para que una coma real en medio de la despedida ("no gracias, ya terminé") no rompa el match.

**Reutiliza el mecanismo de "declinar" YA EXISTENTE** (`datos["decision"] = "DECLINED"` → `agent.py:_sincronizar_activity` → `ManagementStatus.DECLINED` → `gateway.py:_cerrar_si_definitivo` cierra la Activity de verdad) — nunca un mecanismo nuevo y paralelo. Respuesta: *"¡Con gusto[, {nombre}]! Que tengas buen día. Aquí estaré si necesitas algo más."*

## Verificación (los 4 puntos pedidos)

Todo en `tests/domains/health/test_pregunta_correo_y_despedida.py` (12 tests):

1. ✅ Reproducción EXACTA de la conversación real completa (3 turnos) — incluido el hallazgo de la ventana de gracia de un solo uso.
2. ✅ 5 formas reales de despedida (incluida con coma) — todas cierran correctamente.
3. ✅ La pregunta sobre el correo da una respuesta honesta (4 variantes) — nunca reafirma la promesa como hecho, documenta el estado real (recado 054 sin resolver).
4. ✅ Funciona igual con `HealthAnthropicBrain` activo (decisión idéntica, el LLM solo varía la calidez) y dentro de la ventana de gracia/cierre reciente.
5. ✅ Suite completa: **480 passed, 8 skipped** — cero regresiones.

## Archivos tocados

- `domains/health/brain.py`: `_PREGUNTA_SOBRE_CORREO_ENVIADO`/`_DESPEDIDA`/`_es_despedida` (nuevas), 2 categorías nuevas en `_detectar_interrupcion_de_contexto`.
- `domains/health/gateway.py`: `_evaluar_ventana_de_gracia` re-arma la ventana cuando la interrupción no cambia de etapa.
- Nuevo: `tests/domains/health/test_pregunta_correo_y_despedida.py` (12 tests).

## Pendiente de tu decisión

1. **Aprobación de tono** — pediste explícitamente confirmar antes de comitear. Los 2 textos clave: la respuesta honesta sobre el correo, y la despedida.
2. El recado 054 (envío real del correo de confirmación) sigue sin implementarse — si quieres priorizarlo, es un trabajo separado (capturar el correo del paciente + disparar `enviar-confirmacion` + verificar).
3. Revisar si quieres que commitee y pushee este trabajo.
