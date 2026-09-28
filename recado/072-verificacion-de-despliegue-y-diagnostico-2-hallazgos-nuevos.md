# 072 — Verificación de despliegue (NO hay commit del 071) + diagnóstico de 2 hallazgos nuevos

**Fecha**: 2026-09-11
**Estado**: SOLO diagnóstico, tal como pediste — **ninguna corrección aplicada en este recado**. Esperando tu decisión.

---

## PASO 1 — Verificación de despliegue: resultado inequívoco

```
$ git log -1 --format='%H %ci %s'
73d334953acd4974087b292b6f78731b5401ccd1 2026-09-10 22:32:11 -0500 fix: causa raíz de despedidas
cortas no reconocidas + texto/formato exactos (recado 069)

$ git rev-parse HEAD
73d334953acd4974087b292b6f78731b5401ccd1

$ git ls-remote origin refs/heads/main
73d334953acd4974087b292b6f78731b5401ccd1	refs/heads/main
```

**No existe ningún commit del recado 070 ni del 071.** El `HEAD` local y el `origin/main` remoto coinciden exactamente en `73d3349` — que es el commit del **recado 069**, el último que de verdad llegó a comitearse y pushearse.

Esto no es un problema de despliegue de tu lado. Es que **yo nunca comiteé el trabajo de los recados 070 y 071** — quedaron implementados y probados localmente (tal como reporté), pero el mensaje donde te presenté los resultados del 071 terminó esperando tu decisión, no pidiendo aprobación explícita para comitear, y tu siguiente mensaje fue directo a pedirme verificar el despliegue. Todo ese trabajo sigue como cambios sin comitear en este momento:

```
$ git status --short
 M .ai/CONVERSATION_COVERAGE.md
 M domains/health/brain.py
 M domains/health/gateway.py
 M tests/domains/health/test_auditoria_salida_y_cierre_formal.py
 M tests/domains/health/test_pregunta_correo_y_despedida.py
 M tests/domains/health/test_seleccion_asistida_por_llm.py
?? tests/domains/health/corpus_regresion/test_recado070_despedida_sin_conversacion_no_armaba_enfriamiento.py
?? tests/domains/health/corpus_regresion/test_recado070_horario_duplicado_entre_consultorios.py
?? tests/domains/health/corpus_regresion/test_recado070_seleccion_de_servicio_por_ordinal.py
?? tests/domains/health/test_aclaraciones_repiten_lista_completa.py
```

**Conclusión directa**: sea cual sea el hash que muestre el log de build de EasyPanel, **no puede ser** el del recado 071 — como mucho puede ser `73d3349` (recado 069) o algo más viejo. Confírmamelo cuando tengas el log si quieres, pero con la evidencia de arriba ya es matemáticamente imposible que el 070/071 esté corriendo en ningún lado todavía.

Por tu propia regla del PASO 1, punto 3: **esta es exactamente la causa raíz completa** — nunca llegó a desplegarse porque nunca llegó a comitearse. No hace falta ningún rediseño por esto solo; hace falta que yo comitee/pushee, y que tú redespliegues.

---

## PASO 2 — Diagnóstico de los 2 hallazgos (con la salvedad de que el despliegue NO está confirmado correcto)

Tu instrucción decía investigar solo "si el despliegue se confirma correcto" — no es el caso (ver arriba). Aun así, investigué ambos con el mismo rigor, porque la evidencia es valiosa para decidir sobre el rediseño de todas formas. Para hacerlo sin tocar el trabajo local sin comitear, usé un **git worktree separado y de solo lectura** apuntando exactamente al commit desplegado (`73d3349`) — así pude ejecutar el código EXACTO que corre en producción, sin contaminar ni arriesgar el trabajo pendiente en este directorio.

### Hallazgo 1 — "Gracias" mostró el saludo en vez de informar el enfriamiento

**Diagnóstico: completamente explicado, no es un hallazgo nuevo.** Es exactamente el bug del recado 070/071 (la rama `RequestIntent.SALIR` de `_resolver_por_intent`, alcanzada cuando el paciente se despide SIN conversación abierta, nunca armaba `gateway._cierre_reciente`) — sigue presente porque ese fix nunca se desplegó (ver Paso 1). Reproducido de nuevo contra `73d3349` en el worktree, confirmando el mismo síntoma:

```
R2 (despedida via '5'): 'Fue un gusto atenderte. En 2 minutos estaremos disponibles
                         nuevamente si necesitas algo más. ¡Hasta pronto!'
R3 (Gracias inmediato tras despedida): 'Fue un gusto atenderte. En 2 minutos
                         estaremos disponibles nuevamente si necesitas algo más.
                         ¡Hasta pronto!'
```

(Nota: en esta reproducción puntual, como "gracias" en sí mismo también es despedida, `73d3349` lo vuelve a tratar como un cierre nuevo en vez de mostrar el saludo — el síntoma exacto puede variar según el texto usado y cuánto tiempo real pasó entre mensajes, pero la causa raíz es la misma en ambos casos: `_cierre_reciente` nunca se arma en ese camino, así que NINGÚN mecanismo de enfriamiento se activa nunca.)

**No amerita "rediseño"** — es, literalmente, el fix que ya está listo y probado, solo pendiente de comitear/pushear/desplegar.

### Hallazgo 2 — "Hola" disparó una oferta de reprogramación fantasma ("Aquí tienes otras opciones: 1. Viernes 11... 2. Viernes 11... 3. Viernes 11...")

**Diagnóstico: NO pude reproducirlo con la información que tengo — necesito el resto de la transcripción, no una suposición de mi parte.**

Investigué con el mismo rigor, sin adivinar:

1. Confirmé que el texto exacto **"Aquí tienes otras opciones"** solo lo produce una función: `HealthBrain._iniciar_reprogramacion` (`brain.py`). Esa función solo se alcanza por 2 caminos:
   - `self._activity.appointment_id and _contains_any(texto, _REPROGRAMAR)` — requiere una cita YA reservada en la Activity, y el texto debe contener una de las frases curadas de `_REPROGRAMAR` (ninguna se parece a "Hola").
   - `_reanudar_tras_interrupcion("esperando_seleccion_reprogramacion", datos)` — solo alcanzable DESPUÉS de que el paciente declaró y CONFIRMÓ un beneficiario (una secuencia de varios turnos: "es para mi hija" → dar el documento → confirmar el nombre), interrumpiendo una reprogramación en curso.

2. Reproduje contra el código EXACTO de `73d3349` (worktree): con una Activity que SÍ tiene una cita real reservada, inicié una reprogramación (queda en `esperando_seleccion_reprogramacion`), me despedí ("gracias, ya no quiero nada más") a mitad de esa reprogramación, y confirmé que la despedida SÍ cierra correctamente (`etapa: finalizada, decision: DECLINED`).

3. Probé directamente si "Hola", evaluado contra la etapa vieja (`esperando_seleccion_reprogramacion`) por el mecanismo de "ventana de gracia" (`_detectar_interrupcion_de_contexto`, el que `_evaluar_ventana_de_gracia` reevalúa tras un cierre), coincide con alguna de las 5 categorías de interrupción:

   ```
   interrupcion detectada para 'Hola' en etapa vieja: None
   ```

   **No coincide con ninguna.** "Hola" no dispara la ventana de gracia, y por lo tanto tampoco `_reanudar_tras_interrupcion` — que además, confirmé leyendo el código, solo es alcanzable desde la confirmación explícita de un beneficiario (varios turnos), nunca desde un solo "Hola".

**Conclusión honesta**: con la información que tengo (2 mensajes aislados: "Gracias" y "Hola"), **no logré reproducir este hallazgo** ni con el catálogo ficticio ni recreando el escenario más plausible que se me ocurrió (reprogramación abandonada + despedida + "Hola"). Esto no significa que no sea real — significa que la causa exacta probablemente depende de turnos anteriores de esa misma conversación que no tengo (por ejemplo: si en algún momento anterior de esa sesión de pruebas se llegó a declarar y confirmar un beneficiario a mitad de una reprogramación, eso SÍ podría explicar el síntoma exacto, pero no lo puedo confirmar sin la transcripción completa).

**Lo que necesito de ti para poder cerrar esto con evidencia real, no con otra suposición**: la transcripción COMPLETA y literal de esa conversación real, turno por turno, desde el mensaje anterior a la despedida formal hasta el "Hola" — especialmente si en algún punto anterior se mencionó "es para mi hija"/un beneficiario, o si hay otro texto entre la despedida y el "Hola" que no esté en el resumen que me diste.

---

## Mi recomendación sobre el rediseño estructural (para que decidas con contexto, no en el vacío)

No la tomo como decisión — es tu llamada, como pediste. Pero con la evidencia reunida hasta ahora:

- El Hallazgo 1 (y, retrospectivamente, buena parte de la frustración de "la despedida sigue sin funcionar" en los recados 069-071) tiene una causa mucho más simple de lo que parecía: **el trabajo nunca llegó a desplegarse**, no que el diseño sea insuficiente. Cada vez que SÍ se probó el fix real (contra el commit correcto, con datos reales, con tiempo real), funcionó.
- El Hallazgo 2 sigue sin confirmar — no hay evidencia todavía de que sea un problema de arquitectura (múltiples caminos compitiendo) en vez de una secuencia de turnos específica que simplemente no he podido reconstruir.
- El patrón real de esta sesión (recados 067-071) sí muestra algo cierto: cada vez que se agrega un mecanismo nuevo (enfriamiento, ventana de gracia, wizards) sobre una estructura compartida (`_cierre_reciente`, `_detectar_interrupcion_de_contexto`), existe el riesgo de que una rama antigua de código no se actualice para tenerlo en cuenta — exactamente lo que pasó con el Hallazgo 1. Eso es un riesgo real de mantenimiento, pero es distinto de "la arquitectura está mal" — es más bien un argumento a favor de auditar explícitamente, en cada recado que toque uno de estos mecanismos compartidos, TODOS los caminos que escriben/leen esa misma estructura (no solo el que se está arreglando) — algo que puedo agregar como checklist explícito a `.ai/CONVERSATION_COVERAGE.md` si te sirve, sin que eso implique reescribir nada.

Mi sugerencia concreta: (1) comitear/pushear/desplegar lo que ya está listo y probado (070+071), (2) pedirme la transcripción completa para el Hallazgo 2, y (3) decidir sobre el rediseño después de ver si ese hallazgo tiene una causa puntual o si de verdad reaparece con evidencia real tras el despliegue correcto — no antes.

---

## Nada comiteado

Como pediste explícitamente, no implementé ninguna corrección en este recado. El estado de `git status` sigue siendo el mismo de antes de este mensaje (070+071 listos, sin comitear). Quedo a la espera de tu decisión.
