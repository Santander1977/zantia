# 044 — Log temporal de diagnóstico: qué Brain se construye de verdad

**Fecha**: 2026-09-06
**Estado**: implementado, probado (305 passed, 3 skipped) — sin commitear todavía.
**Tipo**: diagnóstico temporal, mismo patrón que el commit `91c42a7` ("debug: log temporal de diagnóstico para 401 en /webhook/telegram") — **marcado explícitamente en el código para quitarlo una vez resuelto**, no es una verificación de seguridad real.

## Qué se agregó

`domains/health/config.py:build_health_brain()` ahora emite `logger.info("BRAIN CONSTRUIDO: tipo=%s, clase=%s", tipo, brain.__class__.__name__)` justo antes de cada `return` (los 3 caminos: determinista por default, determinista por fallback sin API key, y `HealthAnthropicBrain` real) — logger `zantia.health`.

Nunca expone ningún valor de secreto — solo el valor YA NORMALIZADO de `HEALTH_BRAIN_TYPE` (`tipo`) y el nombre de la clase que efectivamente se construyó.

## Por qué resuelve el diagnóstico que pediste

Con este log, en los logs de EasyPanel vas a poder distinguir con certeza entre 3 escenarios, verificados aquí con una corrida real:

| Log observado | Qué significa |
|---|---|
| `tipo=deterministico, clase=HealthBrain` | `HEALTH_BRAIN_TYPE` nunca llegó como `"llm"` a este punto del código (variable no configurada, mal escrita, o no llegó al proceso) |
| `tipo=llm, clase=HealthBrain` | `HEALTH_BRAIN_TYPE=llm` SÍ llegó, pero algo después falló (en la práctica hoy: falta `ANTHROPIC_API_KEY` — ya hay un `logger.warning` explícito justo antes que lo confirma) |
| `tipo=llm, clase=HealthAnthropicBrain` | Todo funcionó — el Brain real está activo |

## Verificación

Corrida real local (no en Docker, innecesario para esto): confirmé los 3 casos exactos de la tabla, con `logging.basicConfig` capturando la salida real del logger `zantia.health`. Suite completa: 305 passed, 3 skipped — cero regresiones (el log no cambia ningún comportamiento, solo agrega una línea informativa).

## Pendiente de tu decisión

1. ¿Comiteo y pusheo este log temporal ahora, para que quede en tu próximo deploy a EasyPanel?
2. Recordatorio explícito (igual que el commit `91c42a7`): este log debe **quitarse** una vez que confirmes en los logs reales cuál de los 3 escenarios está ocurriendo — avísame cuándo retomarlo para removerlo.
