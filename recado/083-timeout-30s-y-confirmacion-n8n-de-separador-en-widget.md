# 083 — Timeout de 10s→30s (insuficiente en la práctica) + confirmación de que el separador \n\n SÍ llega al widget

**Fecha**: 2026-09-12/13 (continuación directa del recado 082, misma noche/madrugada)
**Tipo**: corrección real, probada (código + tests + reproducción real contra hrmm-backend), **NO desplegada** — a la espera de que el usuario redespliegue en EasyPanel.
**Repo**: `/Users/enzoalfonso/Orangutan/icaco` (ZANTIA)
**Continúa**: recado `082` (mismo commit local `b0539a0`, ya pusheado a `origin/main`, sin desplegar todavía) y recado `080` (separador `\n\n`).

## 1. Parte A — el timeout de 10s seguía siendo insuficiente

Tras confirmar que el commit `b0539a0` (recado 082) llegó a `origin/main`, se reprodujo la conversación completa contra el servicio YA desplegado (`https://curson8n-zantia.byrp3l.easypanel.host/webhook/web`, `sessionId` nuevo cada vez) — **el error genérico seguía apareciendo**, porque el fix de captura todavía no estaba desplegado en EasyPanel (esperado, el usuario no había redesplegado aún).

Para confirmar si además el timeout de 10s (ya capturado con gracia por el fix de 082, pero seguía disparándose) era o no la causa real y si 10s alcanza hoy, se reprodujo localmente de nuevo con las credenciales reales de producción: **el fallo ocurrió a los 10.8s**, justo en el límite configurado — confirma que hrmm-backend/n8n SIGUE respondiendo más lento que eso en este momento (consistente con el reinicio de n8n del recado 082).

**Causa raíz de por qué 10s no alcanza, confirmada leyendo `hrmm-backend/app/api/agenda.py` (otro repo, solo lectura)**: `enviar_codigo_verificacion` llama a `httpx.post(N8N_WEBHOOK_CODIGO_URL, ..., timeout=20)` — hrmm-backend puede tardar hasta ~20-22s en responder (éxito o su propio `enviado: false`) ANTES de que ZANTIA le corte la espera a los 10s.

**Corrección**: `RealHttpClient.timeout_seconds` default subido de `10.0` a `30.0` (`domains/health/hrmm_http.py`) — deja margen sobre el máximo conocido de hrmm-backend (~20-22s) sin ser arbitrariamente largo. Es un único valor compartido por TODAS las llamadas de este cliente (catálogo, disponibilidad, reservas, verificación) — decisión deliberada, documentada en el docstring de la clase: el resto de esas llamadas no depende de n8n y responde rápido de por sí, así que el techo más alto no las hace más lentas en el caso normal.

### Verificación

- Test nuevo (`test_timeout_por_defecto_es_30_segundos`) que fija el valor como decisión de producto, no como detalle de implementación.
- Suite completa: **609 passed + 15 skipped** (608 previas + 1 nueva), cero regresiones.
- **Reproducción real, end-to-end, con el timeout nuevo, contra hrmm-backend real**: el segundo turno tardó **21.0s** y esta vez SÍ recibió respuesta de hrmm-backend antes del límite — `"No pudimos enviar el código — intenta de nuevo en un momento."` (el mensaje honesto de hrmm-backend, recado 081, ya NO el error genérico de ZANTIA). Confirma que 30s es suficiente para que hrmm-backend complete su propio ciclo de espera a n8n, y que el problema de fondo (n8n/hrmm-backend sin poder enviar el correo todavía, ver recado 081 — workflow `codigo-recuperacion` inactivo) sigue siendo un problema de infraestructura de HRMM, no de ZANTIA.

## 2. Parte B — el separador `\n\n` SÍ está presente en la respuesta real; el "pegado" visual es del widget, no de ZANTIA

El usuario reportó que el saludo y la pregunta de documento seguían viéndose pegados en `chat.semcolombia.com`, pese al fix del recado 080. Se verificó con evidencia directa, no supuesta:

```
Cuerpo JSON crudo de /webhook/web (repr de Python, sin interpretar los \n):
'{"reply":"Buenos días. Soy Andrés...5. Salir / terminar\\n\\n¡Hola! Antes de seguir..."}'
```

**El `\\n\\n` (es decir, un `\n\n` real dentro del JSON) SÍ está presente** en la respuesta cruda del servicio YA desplegado — el fix de ZANTIA del recado 080 sigue funcionando correctamente, no hubo ninguna regresión de este lado.

**Conclusión, con alta confianza**: si el usuario sigue viendo el texto pegado en el navegador, la causa está del lado del HTML/CSS de `eis-chat-hrmm` — texto plano insertado en el DOM (ej. `element.textContent = reply` o `innerHTML` sin preservar espacios en blanco) no convierte `\n` en un salto de línea visual salvo que el contenedor tenga `white-space: pre-line`/`pre-wrap` (CSS) o el código reemplace `\n` por `<br>` antes de insertarlo. **No es algo que se pueda corregir desde el código de ZANTIA** — el contrato ya cumple lo acordado (`{reply: string}` con `\n\n` como separador de párrafo). Se documenta aquí para que el usuario lo lleve a la sesión de `eis-chat-hrmm` (repo `~/Orangutan/EIS CLINIC IA 360 /operacion/chat/eis-chat-hrmm`) — probablemente en `public/index.html`, revisar cómo se inserta `data.reply` en el DOM del widget.

## 3. Archivos tocados

- `domains/health/hrmm_http.py` (timeout default + docstring).
- `tests/domains/health/test_hrmm_http.py` (1 test nuevo).

## 4. Siguiente paso

Mismo commit pendiente de push que el recado 082 debía cerrar — este cambio se suma al mismo ciclo (commit nuevo sobre `b0539a0`). Pedir al usuario: (a) confirmar el redeploy en EasyPanel, (b) llevar el hallazgo de la Parte B a la sesión de `eis-chat-hrmm` — no se puede resolver ni verificar desde aquí.
