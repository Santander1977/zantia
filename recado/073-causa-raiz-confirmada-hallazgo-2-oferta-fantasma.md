# 073 — Causa raíz CONFIRMADA del Hallazgo 2 (oferta fantasma de reprogramación)

**Fecha**: 2026-09-11
**Estado**: Causa raíz confirmada con evidencia directa de código (no supuesta). **Ninguna corrección aplicada todavía** — reporto antes de corregir, como en el recado 072, dado que es un hallazgo nuevo y potencialmente amplio.

---

## Contexto

Commit `0b89286` (recados 070/071/072) ya está comiteado y pusheado — `git rev-parse HEAD` y `git ls-remote origin refs/heads/main` coinciden. Pendiente que confirmes el redeploy en EasyPanel para re-verificar el Hallazgo 1 contra el entorno real (paso 2 de tu pedido, sigo esperando tu confirmación).

Mientras tanto, investigué el Hallazgo 2 con la transcripción completa que compartiste.

---

## La transcripción, turno por turno

```
07:07 ZANTIA: "Fue un gusto atenderte. En 2 minutos estaremos disponibles..."
07:08 Enzo:   "Gracias"
07:08 ZANTIA: "Fue un gusto atenderte..." (bug del enfriamiento, ya explicado — recado 072)
07:08 Enzo:   "Hola"
07:08 ZANTIA: "¡Buenos días! ¿Puedo ayudarte en algo más?"
07:08 Enzo:   "Y pasaron los 2 minutos"
07:08 ZANTIA: "Aquí tienes otras opciones: 1. Viernes 11 de septiembre, 07:30, Consultorio 5
               2. Viernes 11 de septiembre, 08:00, Consultorio 5
               3. Viernes 11 de septiembre, 08:30, Consultorio 5
               ¿Cuál prefieres?"
07:08 Enzo:   "Eso que es"
07:08 ZANTIA: "No identifiqué cuál opción prefieres — ¿me confirmas 1, 2 o 3?"
07:09 Enzo:   "De que servicio es ?"
07:09 ZANTIA: "No identifiqué cuál opción prefieres — ¿me confirmas 1, 2 o 3?"
07:09 Enzo:   "No exit"
07:09 ZANTIA: "De acuerdo, no seguimos con esto por ahora. ¿En qué más te ayudo?\n[menú]"
07:09 Enzo:   "5"
07:09 ZANTIA: "Fue un gusto atenderte..."
```

## Primer paso: identificar EXACTAMENTE qué función produjo cada mensaje

Comparé el texto EXACTO de cada respuesta contra el código, sin asumir cuál función lo generó:

- `"Aquí tienes otras opciones:\n{lista}\n¿Cuál prefieres?"` — coincide letra por letra con `gateway.py::_iniciar_verificacion_para_gestion` (el wizard de reprogramar/cancelar CON verificación por código/2FA). **No** coincide con `HealthBrain._iniciar_reprogramacion` (esa dice "Claro que sí, aquí tienes otras opciones..." y termina en "¿Cuál te queda mejor?", distinto).
- `"No identifiqué cuál opción prefieres — ¿me confirmas 1, 2 o 3?"` — coincide letra por letra con `gateway.py::_procesar_intento_de_codigo`, rama `stage == "esperando_seleccion"` (el texto ANTES de mi fix del recado 070, que sigue siendo el texto real porque esto viene de una prueba contra el commit `73d3349`, todavía sin desplegar en ese momento).
- `"De acuerdo, no seguimos con esto por ahora. ¿En qué más te ayudo?\n[menú]"` — coincide letra por letra con la rama `"salir"` de esa misma función.

**Confirmado sin ambigüedad**: las 3 respuestas vienen del wizard de verificación por código de `gateway.py` (`_pending_verifications`) — el mismo mecanismo usado para reprogramar/cancelar una cita YA reservada con 2FA. La pregunta real es: ¿qué hizo que ese wizard se **activara** con el mensaje "Y pasaron los 2 minutos"?

## Causa raíz — confirmada ejecutando el código real, no supuesta

`gateway.py::_interpretar_opcion_menu` (la función que revisa PRIMERO de todo, antes incluso de la despedida, si el mensaje coincide con una opción del menú) hace, para cada opción, `re.search(rf"\b{ordinal}\b", texto_norm)` — busca el dígito como TOKEN suelto, en cualquier parte del mensaje, **sin ningún límite de longitud del mensaje completo**.

`_MENU_OPCIONES` mapea `"2"` a `RequestIntent.REPROGRAMAR_CITA`. El mensaje "Y pasaron los 2 minutos" contiene el token suelto "2" (rodeado de espacios). Lo comprobé directamente:

```python
>>> from domains.health.gateway import _interpretar_opcion_menu
>>> _interpretar_opcion_menu("Y pasaron los 2 minutos")
RequestIntent.REPROGRAMAR_CITA
```

**Esa es la causa raíz completa, confirmada.** El paciente escribió una frase completamente ajena ("ya pasaron los 2 minutos", refiriéndose al enfriamiento), y el dígito "2" suelto dentro de ella se interpretó como si hubiera elegido la 2da opción del menú ("Reprogramar una cita") — con una cita real en su historial (`appointment_id` real), esto disparó de verdad `_iniciar_verificacion_para_gestion`, que consultó disponibilidad REAL y ofreció horarios REALES de reprogramación, sin que el paciente pidiera nada de eso.

A partir de ahí, el resto de la transcripción es 100% consistente y explicado: cada respuesta siguiente es el wizard de verificación funcionando exactamente como se diseñó (pidiendo aclaración, reconociendo "exit" para salir) — el problema nunca estuvo en el wizard en sí, sino en cómo se activó.

## Por qué esto NO es lo mismo que el hallazgo ya corregido en el recado 067

El recado 067 encontró y corrigió el mismo PATRÓN de bug (un dígito suelto dentro de una oración larga y ajena, mal interpretado como una selección) — pero específicamente en `_elegir_opcion`/`_elegir_opcion_ordinal` (la función que interpreta la respuesta a "¿cuál de estas 3 opciones prefieres?", DESPUÉS de que ya se ofreció una lista). El fix de ese recado (`_indice_ordinal_seguro`, límite de 8 palabras) **nunca se aplicó** a `_interpretar_opcion_menu` (`gateway.py`) — una función DISTINTA, que interpreta el PRIMER mensaje de una solicitud nueva contra el menú principal (1-5), sin ninguna conversación abierta todavía. Nadie audit贸 en su momento si el mismo patrón de vulnerabilidad existía también ahí — y sí existía.

## Alcance confirmado — no es solo la opción "2"

Probé las 5 opciones del menú con frases largas y completamente ajenas, cada una con el dígito correspondiente suelto en algún punto:

```python
>>> _interpretar_opcion_menu("tengo una duda, nos vemos el 3 de este mes")
RequestIntent.CANCELAR_CITA
>>> _interpretar_opcion_menu("mi hijo cumple 4 años la otra semana")
RequestIntent.CONSULTAR_CITA
>>> _interpretar_opcion_menu("llego en 1 hora aprox")
RequestIntent.PROGRAMAR_CITA
```

**Las 5 opciones son vulnerables por igual** — cualquier mensaje que mencione de pasada un número del 1 al 5 (una hora, una fecha, una cantidad, una calificación) puede disparar una acción real no pedida, incluyendo — el caso más delicado — iniciar una reprogramación/cancelación real de una cita existente.

## Por qué el mecanismo de LLM asistido NO es la causa (probado, no descartado por suposición)

Antes de llegar a esta causa raíz, consideré si la clasificación asistida por LLM del menú (`_clasificar_solicitud_nueva_via_llm`, recado 064) pudo confundirse con el "2" de "2 minutos". Lo probé con una llamada REAL a la API de Anthropic contra las 7 categorías reales:

```
'Y pasaron los 2 minutos' -> option=None
'ya pasaron los 2 minutos' -> option=None
'pasaron 2 minutos' -> option=None
'listo ya pasaron los 2 minutos, hola de nuevo' -> option=None
```

El LLM real NUNCA propuso una categoría para estas frases — se descarta como causa. La causa real es puramente determinista, en `_interpretar_opcion_menu`, la PRIMERA función que se revisa (antes incluso de que el LLM tenga oportunidad de intervenir).

---

## Estado: sin corregir, a la espera de tu decisión

No implementé ningún fix todavía. La corrección natural (mismo patrón ya aplicado en el recado 067) sería: exigir que el mensaje completo tenga como mucho N palabras para que un dígito SUELTO cuente como opción de menú — igual que `_indice_ordinal_seguro` ya exige para la selección de una lista ya ofrecida. Pero antes de tocar código quiero tu confirmación, dado que:

1. Es un hallazgo nuevo, no pedido explícitamente para corregir en este mensaje.
2. Toca `_interpretar_opcion_menu`, una función usada en el camino MÁS transitado de todos (cualquier mensaje sin conversación abierta) — quiero tu visto bueno antes de tocarla, no asumir alcance.

Dime si quieres que lo corrija ahora (puedo hacerlo con el mismo rigor: reproducir, corregir, test de regresión, correr la suite completa) o si prefieres esperar a evaluarlo junto con la decisión sobre el rediseño estructural que planteaste.
