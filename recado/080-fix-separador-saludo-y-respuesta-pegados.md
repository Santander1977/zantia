# 080 — Fix: saludo institucional y respuesta siguiente venían pegados sin separador

**Fecha**: 2026-09-11
**Tipo**: corrección real, probada (código + tests + E2E local), **NO desplegada** — a la espera de confirmación explícita para commitear/pushear/redesplegar.
**Repo**: `/Users/enzoalfonso/Orangutan/icaco` (ZANTIA)
**Origen**: reportado por el usuario a partir de una prueba end-to-end real (`curl` → `eis-chat-hrmm` local → ZANTIA real en EasyPanel, ver recado `079`), donde la respuesta llegó como:
> "...5. Salir / terminar ¡Hola! Antes de seguir, ¿me confirmas tu número de documento de identidad?..."

## 1. Investigación — la premisa del pedido original era incorrecta

El pedido asumía que `TelegramChannel` ya resolvía este mismo caso enviando **2 mensajes separados** de Telegram (recado 046/047), y que el arreglo debía ser específico de `WebChannel`. **Esto no es así, confirmado con evidencia real:**

- `handle_inbound_message()` (`domains/health/gateway.py`) **siempre devuelve un único `str`** — no existe en ningún punto del código un mecanismo que devuelva una lista de mensajes ni que separe una respuesta en varios envíos.
- Leyendo `service/app.py` completo: `webhook_telegram`, `webhook_chatwoot` y `webhook_web` llaman `handle_inbound_message()` **una sola vez** y hacen **un solo** `_canal.send(...)` con ese string — sin excepción, sin splitting, para los 3 canales.
- `git log -S'f"{_saludo_primer_contacto(None)}'` muestra que la línea nació con un **espacio simple** en el commit `f37e24d` ("recado 046 Parte 2") y nunca se modificó desde entonces. El propio encabezado del recado `046` dice textualmente: *"HEALTH_BRAIN_TYPE sigue sin activarse en ningún archivo, **no se probó Telegram**."*

**Conclusión**: esto **no es una regresión** — es un hueco que existió desde el día en que se implementó el saludo institucional (recado 046), nunca antes notado porque nadie había comparado visualmente el JSON crudo de una respuesta real con este caso específico (saludo + gate de identidad en el mismo turno). Afecta a **Telegram y Chatwoot exactamente igual** que a Web — WebChannel solo lo hizo visible porque el usuario inspeccionó el JSON crudo con `curl`.

## 2. Búsqueda exhaustiva de otros casos similares

Pedido explícito de revisar si hay otro punto igual en `gateway.py`/`brain.py`. Se buscaron TODOS los f-strings que interpolan 2+ variables (`grep -n 'f"' ... | grep -E '\{[a-zA-Z_]+\}.*\{[a-zA-Z_]+\}'`) más toda concatenación con `+`/`" ".join`. Resultado — **solo 2 casos reales** de "dos mensajes independientes pegados" (ambos corregidos, ver sección 3):

- `gateway.py:835` (antes) — saludo/menú + pregunta de documento.
- `gateway.py:912` (antes, línea 895 en la numeración previa al primer fix de esta sesión) — saludo/menú + primera respuesta real.

El resto de coincidencias (`gateway.py:337/338/397/409/1690/2052`, `brain.py:747/1276/1504/1780/1812`) se revisaron una por una y **no son el mismo bug** — son UNA sola frase con variables interpoladas (ej. `"¡{saludo_hora}, {tratamiento} {nombre}! ¿Qué desea hacer hoy?"`) o un patrón "intro: \n lista" ya usado consistentemente en el proyecto (ej. `f"{intro}\n{lista_citas}"`), donde un solo `\n` es la convención correcta y esperada (no un caso de mensajes pegados sin separación).

## 3. La corrección

`domains/health/gateway.py`, 2 líneas — cambio de separador de `" "` (espacio simple) a `"\n\n"` (salto de párrafo):

```python
# Antes (ambos puntos):
return f"{_saludo_primer_contacto(None)} {respuesta_identificacion}"
return f"{saludo_apertura} {respuesta}"

# Ahora:
return f"{_saludo_primer_contacto(None)}\n\n{respuesta_identificacion}"
return f"{saludo_apertura}\n\n{respuesta}"
```

Corrige la causa raíz compartida — **beneficia a los 3 canales por igual**, no solo a Web. Telegram ya renderiza `\n` correctamente hoy dentro de un mismo mensaje (el propio `_MENU_NUMERADO` usa `\n` entre sus 5 opciones, dentro del mismo `sendMessage`) — `\n\n` es el mismo mecanismo, un salto de línea más, no una función nueva que verificar.

## 4. Verificación

### 4.1 Tests nuevos (`tests/domains/health/test_separador_saludo_y_respuesta.py`, 6 tests)
- Reproduce el caso EXACTO reportado (saludo + pregunta de documento) parametrizado en 3 canales (`telegram`, `web`, `chatwoot`) — confirma `\n\n` presente, que el menú termina justo antes del separador, que la pregunta empieza limpia después, y que nunca hay triple salto ni espacios sueltos alrededor.
- Cubre el segundo punto de concatenación (saludo + primera respuesta real, canal sin gate de identidad).
- Confirma que `TelegramChannel.send()` y `WebChannel.send()` reciben y transmiten el string **exactamente igual**, sin volver a tocarlo — ninguno de los dos canales concatena ni reformatea nada por su cuenta (la corrección vive solo en `gateway.py`).

### 4.2 Suite completa
`python -m pytest -q` dentro del `.venv`: **598 passed + 15 skipped** (592 previas + 6 nuevas), **cero regresiones** — ningún test existente asumía el espacio simple como separador (todos usan `in respuesta.lower()` por substring, no comparación exacta).

### 4.3 Prueba end-to-end real, PRE-deploy (sin tocar producción)

Como el fix todavía no está desplegado en EasyPanel, repetir el `curl` contra la URL de producción real habría mostrado el bug SIN corregir. Para probar el fix de verdad antes de pedir el despliegue:

1. Se levantó ZANTIA **localmente** (`uvicorn service.app:app --port 8001`) con las MISMAS variables de entorno reales de producción (`HRMM_BACKEND_ENV=production`, `HRMM_BACKEND_URL`/`HRMM_BACKEND_SECRET` reales, sync de catálogo real contra hrmm-backend) — sin tocar EasyPanel.
2. `POST http://localhost:8001/webhook/web` directo, mismo payload que el usuario probó (`{"message":"hola","sessionId":"prueba-fix-separador-1"}`):
   ```json
   {"reply":"Buenas noches. Soy Andrés...5. Salir / terminar\n\n¡Hola! Antes de seguir, ¿me confirmas tu número de documento de identidad?..."}
   ```
3. Se apuntó **temporalmente** el `.env` de `eis-chat-hrmm` (`N8N_WEBHOOK_URL`) a `http://localhost:8001/webhook/web`, se reinició su servidor local, y se repitió el MISMO `curl` que usó el usuario para reportar el bug — mismo resultado, con `\n\n` presente en el campo `reply`, cadena completa vía Express real.
4. Se restauró el `.env` de `eis-chat-hrmm` a la URL real de producción (`https://curson8n-zantia.byrp3l.easypanel.host/webhook/web`) y se reinició su servidor apuntando de nuevo a producción — **estado dejado exactamente como estaba antes de esta prueba**. Se detuvo el proceso `uvicorn` local de prueba. `git status` de `eis-chat-hrmm` confirmado limpio (`.env` no está trackeado).

### 4.4 Confirmación visual real en Telegram (`@Zantia_test_bot`) — **PENDIENTE, requiere al usuario**

No pude ejecutar este paso yo mismo: `TELEGRAM_BOT_TOKEN` está vacío en el `.env` local de este repo (mismo hallazgo que documentó el recado 046: "no se probó Telegram" — nunca hubo credenciales reales en esta máquina), y aunque lo tuviera, la Bot API de Telegram no permite que un bot le escriba primero a un usuario — solo puede responder dentro de un chat que el usuario ya inició. El patrón ya establecido en este proyecto (recado `060`) es que **el usuario mismo prueba `@Zantia_test_bot` desde su teléfono** y reporta lo que ve — así se hizo la única vez que se verificó Telegram contra la Bot API real.

Lo que SÍ puedo garantizar con evidencia: (a) el test `test_telegram_channel_envia_el_string_ya_separado_sin_tocarlo` confirma que `TelegramChannel.send()` recibe y transmite el `\n\n` sin alterarlo — y (b) Telegram ya renderiza saltos de línea simples correctamente HOY en producción (el menú numerado de 5 opciones, mismo mecanismo) — `\n\n` es un salto de línea adicional, mismo mecanismo de renderizado, riesgo de que no se vea bien es bajo pero no cero. **Recomendación**: después de desplegar, pedirte que envíes "necesito una cita" (o cualquier mensaje sin identidad ya resuelta) a `@Zantia_test_bot` y confirmes visualmente el salto de línea entre el menú y la pregunta de documento.

## 5. Archivos tocados

- `domains/health/gateway.py` — 2 líneas funcionales (separador) + comentarios explicando el porqué (recado 080).
- `tests/domains/health/test_separador_saludo_y_respuesta.py` (nuevo, 6 tests).

## 6. Siguiente paso

Reportar al usuario: fix aplicado (2 líneas, causa raíz real en `gateway.py`, no en `WebChannel`), premisa original corregida (no es un problema exclusivo de Web, ni algo que Telegram ya resolvía — es un hueco compartido desde el origen de la funcionalidad), 6 tests nuevos, suite completa 598/598 + 15 skipped sin regresiones, prueba E2E real pre-deploy confirmada dos veces (ZANTIA local directo, y cadena completa vía `eis-chat-hrmm` local). Pedir: (a) confirmación para commitear/pushear/redesplegar, y (b) que confirme visualmente en `@Zantia_test_bot` después del despliegue, ya que ese paso no se puede hacer desde este entorno.
