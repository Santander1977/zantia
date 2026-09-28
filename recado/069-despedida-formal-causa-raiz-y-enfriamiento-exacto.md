# 069 — Despedida formal: causa raíz de por qué 2 rondas de fixes no bastaron, y comportamiento exacto pedido

**Fecha**: 2026-09-10
**Rama**: `main` (base `0a64889`, recado 068 ya desplegado)
**Estado**: Implementado y probado automáticamente + con llamada real a la API de Anthropic. **Pendiente la prueba en vivo en Telegram con el usuario antes de comitear** (ver sección final).

---

## 1. El reporte del usuario

Tras los recados 057 (despedida corta + enfriamiento) y 067 (despedida formal + enfriamiento de 2 minutos + auditoría de "salir"), el usuario reportó en producción que **la despedida seguía sin funcionar**: despedidas reales como "gracias", "chao", "no gracias" seguían mostrando el menú institucional completo o preguntando "¿puedo ayudarte en algo más?", en vez de un único mensaje de cierre formal.

El usuario exigió, explícitamente, no aceptar otro "implementado y probado" sin la causa raíz de por qué 2 rondas previas no bastaron — no un tercer intento a ciegas.

---

## 2. Causa raíz confirmada (con evidencia real, no supuesta)

Antes de tocar nada, reproduje directamente en un REPL de Python (sin mocks de más) el primer mensaje de una conversación nueva con cada una de las frases que el usuario reportó:

```python
handle_inbound_message(gateway, ref, "demo", "m1", "gracias")       # -> menú institucional completo
handle_inbound_message(gateway, ref, "demo", "m1", "no gracias")    # -> menú institucional completo
handle_inbound_message(gateway, ref, "demo", "m1", "que descanses") # -> menú institucional completo
```

**Causa raíz exacta**: `domains/health/brain.py`, la lista `_DESPEDIDA` (antes de este fix, línea ~211 de la versión previa) solo reconocía **frases de 3 o más palabras** ("no gracias ya termine", "eso sería todo", etc.), con únicamente 3 excepciones sueltas: "chao"/"chau"/"adios". Esto fue una decisión deliberada del recado 059 para evitar falsos positivos (un "gracias" suelto en medio de una conversación normal no debía cerrarla). El problema: **nadie extendió esa excepción a las formas cortas MÁS comunes en español coloquial** — "gracias" solo, "no gracias" solo, "que descanses" solo — que son exactamente las que el paciente real usó.

Los recados 057 y 067 corrigieron problemas reales (saludo corto tras cierre, duplicación de mensajes, "salir" atrapado en wizards, período de enfriamiento) pero **ninguno de los dos tocó `_DESPEDIDA` ni agregó cobertura para despedidas cortas** — por eso 2 rondas de fixes no bastaron: estaban resolviendo síntomas alrededor de un detector que, para el caso más común reportado, nunca se activaba en absoluto. El mensaje nunca llegaba a la rama de despedida; cursaba como "intención no reconocida" y caía al menú.

Adicionalmente, el texto exacto usado en el cierre (recado 067: *"¡Con gusto[, nombre]! Que tengas buen día. Aquí estaré si necesitas algo más. En 2 minutos podremos atender otra solicitud..."*) no coincidía con el formato exacto pedido ahora por el usuario, y **"Aquí estaré si necesitas algo más" contradice directamente el enfriamiento real de 2 minutos** que sigue a ese mismo mensaje — un texto ambiguo sobre su propia disponibilidad inmediata.

---

## 3. Fix implementado

### 3.1 Detección de despedidas cortas (`domains/health/brain.py:277-296`)

Nueva función `_es_solo_despedida`, basada en tokens (no en frases fijas, para cubrir cualquier orden de palabras: "no ya gracias", "ya no gracias", "gracias ya"):

```python
_ANCLAS_DE_CIERRE = frozenset({"gracias", "descanses", "chao", "chau", "adios", "bye", "listo", "vemos"})
_PALABRAS_DE_CIERRE_SUELTAS = _ANCLAS_DE_CIERRE | {"no", "ya", "muchas", "que", "q", "hasta", "luego", "pronto", "nos"}

def _es_solo_despedida(texto_sin_tildes_y_puntuacion: str) -> bool:
    palabras = texto_sin_tildes_y_puntuacion.split()
    if not palabras:
        return False
    if not all(p in _PALABRAS_DE_CIERRE_SUELTAS for p in palabras):
        return False
    return any(p in _ANCLAS_DE_CIERRE for p in palabras)
```

Exige que **todas** las palabras del mensaje sean "relleno de cierre", y que **al menos una** sea una ancla inequívoca (nunca "no"/"ya"/"que" solos — demasiado ambiguos, "no" ya tiene su propio manejo como declinación). `_es_despedida` (línea 329) ahora combina la lista de frases larga (`_DESPEDIDA`, sin cambios) con este nuevo detector corto.

**Verificado directamente** (antes de escribir cualquier test automatizado) que activa: "gracias", "chao", "no gracias", "no ya gracias", "que descanses", "ya no gracias", "gracias ya", "muchas gracias" — y que sigue sin activarse (controles negativos) con: "gracias, ¿a qué hora es la cita?", "no puedo ahora".

### 3.2 Texto exacto de cierre (`domains/health/brain.py:354-368`)

```python
def _texto_despedida(nombre: Optional[str]) -> str:
    if nombre:
        return f"Fue un gusto atenderte, {nombre}. En 2 minutos estaremos disponibles nuevamente si necesitas algo más. ¡Hasta pronto!"
    return "Fue un gusto atenderte. En 2 minutos estaremos disponibles nuevamente si necesitas algo más. ¡Hasta pronto!"
```

Reemplaza el texto del recado 067. `handle_inbound_message` (`gateway.py:~715`) sigue garantizando que un cierre (`es_cierre=True`) **nunca** lleva un saludo antepuesto (mecanismo ya existente desde el recado 067, sin cambios) — así que este es el mensaje completo, único, sin nada antes ni después.

### 3.3 Mensaje de bloqueo durante el enfriamiento (`domains/health/gateway.py:309-318`)

```python
def _mensaje_enfriamiento(segundos_restantes: int) -> str:
    minutos, segundos = divmod(max(segundos_restantes, 0), 60)
    texto_minutos = f"{minutos} minuto" + ("s" if minutos != 1 else "")
    texto_segundos = f"{segundos} segundo" + ("s" if segundos != 1 else "")
    return f"Aún estamos en pausa — podremos atenderte de nuevo en {texto_minutos} y {texto_segundos}."
```

Reemplaza el "Aún faltan N segundos"/"Ya casi" del recado 067. El bloqueo (`gateway.py:661-666`) ocurre **antes** de tocar `find_open_context`/el Brain/el LLM — ningún mensaje durante el enfriamiento llega jamás a procesarse, sin excepción (verificado, ver sección 4).

---

## 4. Verificación automatizada

- Suite completa: **546 passed, 15 skipped, 0 failed** (`.venv/bin/pytest -q`). Los 35 fallos que aparecieron al cambiar el texto (assertions de tests previos que comparaban contra "con gusto"/"que tengas buen día"/"segundos para poder atenderte"/"ya casi") se corrigieron uno por uno en `tests/domains/health/test_auditoria_salida_y_cierre_formal.py` y `tests/domains/health/test_pregunta_correo_y_despedida.py` — nunca se relajó una aserción para que "pasara"; cada una ahora verifica el texto/comportamiento nuevo exacto.
- **Verificación adicional exigida por el usuario** ("revisa la lógica real, no asumas"): probé el bloqueo del enfriamiento con 12 mensajes de tipos deliberadamente variados durante la ventana de 2 minutos — saludo, número suelto ("1"), petición de otra cita, "salir", "gracias", pregunta genérica, mensaje urgente, opción de menú ("5"), "cancelar", símbolos sueltos, y mensaje vacío. **Los 12 recibieron, sin excepción, el mismo mensaje de bloqueo** — ninguno se procesó como una solicitud nueva.
- Verificación del límite exacto de los 2 minutos: a 119.9s transcurridos, sigue bloqueado ("0 minutos y 1 segundo" restante); a 120.1s, se trata como contacto nuevo (saludo corto, ventana de 30 minutos del recado 057 sigue activa).
- **Con el LLM real activo** (`HEALTH_BRAIN_TYPE=llm` + `ANTHROPIC_API_KEY` real, mismo `.env` de esta máquina que causó el bug del recado 068): llamada real a la API de Anthropic confirmando que el cierre sigue siendo un único mensaje sin menú ni pregunta ("¡Fue un gusto atenderte! En 2 minutos estaremos disponibles de nuevo por si necesitas algo más. ¡Hasta pronto!" — el LLM varía el tono, nunca el significado, tal como pide el usuario), y que el bloqueo del enfriamiento **nunca pasa por el LLM en absoluto** (retorna antes de tocar el Brain), así que el formato del mensaje de bloqueo es 100% determinista siempre, sin variación posible del LLM.

## 4.1 Límite conocido, fuera del alcance de este fix (documentado, no corregido sin pedirlo)

Dentro del wizard de código de verificación (cancelar/reprogramar una cita, `gateway.py:_procesar_intento_de_codigo`), la palabra "salir" **no** dispara la despedida formal — sale del wizard puntual y vuelve al menú general ("De acuerdo, no seguimos con esto por ahora. ¿En qué más te ayudo?"). Esto es un comportamiento deliberado de los recados 062/063 (evitar que el paciente quede atrapado en ESE sub-flujo específico, sin necesariamente terminar toda la conversación). No lo cambié porque el reporte del usuario fue específicamente sobre despedidas fuera de ese wizard, y cambiarlo unilateralmente podría reabrir el callejón sin salida que 062/063 resolvieron. Si el usuario quiere que "salir" DENTRO de ese wizard también dispare el cierre formal completo, avisar explícitamente y lo ajusto en un recado aparte.

---

## 5. VERIFICACIÓN EN VIVO EN TELEGRAM — instrucciones exactas

**No se ha comiteado nada todavía.** Antes de comitear, por favor prueba en vivo en `@Zantia_test_bot` (o el bot que tengas corriendo con este código local — si necesitas que redespliegue primero, dime y coordinamos). Pasos exactos:

### Paso 1 — Despedida corta simple
Escribe: `gracias`
**Debes ver**: un único mensaje, exactamente:
> Fue un gusto atenderte. En 2 minutos estaremos disponibles nuevamente si necesitas algo más. ¡Hasta pronto!

(o una variante de tono similar si el bot está en modo LLM — pero SIN pregunta "¿algo más?" y SIN el menú numerado 1-5).

### Paso 2 — Bloqueo inmediato
Inmediatamente después (dentro del mismo minuto), escribe cualquier cosa, por ejemplo: `hola`
**Debes ver**: un único mensaje tipo:
> Aún estamos en pausa — podremos atenderte de nuevo en 1 minuto(s) y XX segundos.
(el número exacto de minutos/segundos dependerá de cuánto hayas tardado en escribir — debe ir bajando cada vez que pruebes).

### Paso 3 — Bloqueo con cualquier tipo de mensaje
Prueba escribir, cada una en un mensaje separado, todavía dentro de los 2 minutos: `1`, `necesito una cita urgente`, `salir`, `5`
**Debes ver, en los 4 casos**: el mismo mensaje de "Aún estamos en pausa..." — nunca el menú, nunca una pregunta, nunca que procese la solicitud.

### Paso 4 — Pasado el enfriamiento
Espera a que pasen los 2 minutos completos desde el mensaje de despedida del Paso 1 (puedes usar el contador de "X minutos y Y segundos" del Paso 2/3 como referencia). Escribe: `hola`
**Debes ver**: un saludo corto normal (ej. "¡Buenas [tardes/noches]! ¿Puedo ayudarte en algo más?") — YA NO el mensaje de pausa. El sistema debe tratarlo como un contacto normal.

### Paso 5 — Otras formas de despedida (opcional, para más confianza)
Repite el Paso 1 con: `chao`, `no gracias`, `que descanses`, `5` (opción de menú), `salir` (sin conversación abierta) — todas deben producir el mismo mensaje único de cierre formal.

Por favor pégame la transcripción completa (mensaje por mensaje, con hora si es posible) de lo que veas — especialmente si algún paso NO coincide con lo esperado arriba.

---

## 6. Siguiente paso

Con tu confirmación de que la prueba en Telegram coincide con lo esperado, comiteo y pusheo este trabajo (recado 069) y confirmo con `git ls-remote` + comparación de hashes, como en cada recado anterior.
