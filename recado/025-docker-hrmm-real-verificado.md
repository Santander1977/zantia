# RECADO PARA CHATGPT

Fecha: 2026-09-05
Proyecto: ZANTIA (carpeta física `/Users/enzoalfonso/Orangutan/icaco`)
Tema: Build/run real de Docker con credenciales reales de hrmm-backend + Telegram, sin Chatwoot (D-8) — validación real de `HRMM_BACKEND_SECRET`
Objetivo: Documentar el resultado de las 3 verificaciones pedidas y un hallazgo operativo real encontrado en el camino.

Convenciones: HECHO = verificado ejecutando algo o leyendo código real en esta sesión. PENDIENTE = no resuelto, nunca inventado.

---

## Resumen ejecutivo

HECHO: build y run reales de Docker con `HRMM_BACKEND_URL`/`HRMM_BACKEND_SECRET`/`TELEGRAM_BOT_TOKEN`/`TELEGRAM_WEBHOOK_SECRET` reales del usuario, SIN ninguna variable de Chatwoot (probando D-8 con credenciales reales de producción por primera vez, no solo placeholders).

**Las 3 verificaciones pedidas, con evidencia real**:
1. Arranca sin Chatwoot, solo el warning esperado (sin fail-fast) — confirmado, logs mostrados.
2. `GET /health` → `200 {"status":"ok"}` — confirmado.
3. Conexión a hrmm-backend real funciona — confirmado con MÁS rigor del pedido explícitamente (ver hallazgo abajo).

## Hallazgo real: `GET /api/agenda/disponibilidad` NO valida `HRMM_BACKEND_SECRET`

Investigado y confirmado en sesiones anteriores (recado 009): ese endpoint es PÚBLICO — `HrmmAppointmentService.get_availability()` no manda ningún header de autenticación. Se ejecutó igual, real, contra producción (`svc.get_availability('Medicina General')` → 0 slots libres, respuesta real sin error) — pero esto por sí solo NO demuestra que `HRMM_BACKEND_SECRET` sea válido, solo que la URL es alcanzable.

Para cerrar el pedido de verdad ("confirmar que HRMM_BACKEND_SECRET es válido"), se hizo ADEMÁS una llamada real a un endpoint que SÍ exige el secreto: `GET /api/agenda/citas` (`get_patient_appointments`, con `X-Backend-Secret`), usando un documento de prueba claramente marcado (`ZANTIA-TEST-VALIDACION-SECRETO`, nunca un paciente real) → **200, 0 citas** — confirma que el secreto es correcto (un secreto inválido habría respondido `401`, confirmado ese comportamiento leyendo `trusted_auth.py` en recado 009).

También se confirmó, como efecto colateral de que el proceso arrancara: la sincronización de catálogo al arrancar (`build_appointment_service`) trajo **5 servicios reales** de hrmm-backend — otra llamada real exitosa, necesaria para que el proceso siquiera llegue a "Application startup complete".

## Hallazgo operativo real: `HRMM_BACKEND_ENV=` vacía ≠ no configurada

El `.env` real del usuario tiene la línea `HRMM_BACKEND_ENV=` presente pero VACÍA (no borrada). `build_appointment_service()` usa `os.environ.get("HRMM_BACKEND_ENV", "mock")` — con la variable PRESENTE-pero-vacía, Python devuelve `''` (no el default `"mock"`), y el proceso falla al arrancar con `HealthConfigError("HRMM_BACKEND_ENV='' no es un valor reconocido")`. Para esta prueba se forzó `HRMM_BACKEND_ENV=production` explícitamente vía `-e` de Docker (es literalmente lo que el usuario quería probar). Documentado en `.env.example` para que no muerda en un despliegue real: si no se va a usar hrmm-backend real, hay que BORRAR la línea completa, no dejarla con el `=` solo.

## Evidencia real (comandos y salida)

```
$ docker build -t zantia:local-test .
[...]
#11 naming to docker.io/library/zantia:local-test done

$ docker run -d --name zantia-test-hrmm --env-file <archivo temporal, solo HRMM_BACKEND_URL/SECRET, TELEGRAM_BOT_TOKEN/WEBHOOK_SECRET reales + HRMM_BACKEND_ENV=production> -p 8010:8000 zantia:local-test
$ docker logs zantia-test-hrmm
CHATWOOT_URL/CHATWOOT_ACCOUNT_ID no configuradas — canal de Chatwoot deshabilitado (POST /webhook/chatwoot responderá 503 si se invoca). Ver .env.example y .ai/RISKS.md R-4.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000

$ curl http://localhost:8010/health
{"status":"ok"}  HTTP 200

$ docker exec zantia-test-hrmm python -c "... svc.get_availability('Medicina General') ..."
Servicios sincronizados desde hrmm-backend real: 5
Slots libres devueltos: 0

$ docker exec zantia-test-hrmm python -c "... svc.get_patient_appointments('ZANTIA-TEST-VALIDACION-SECRETO') ..."
HRMM_BACKEND_SECRET VALIDO -- respuesta 200, citas encontradas: 0
```

Contenedor y archivo temporal con secretos eliminados al finalizar (`docker stop`/`rm`, `rm -f` del env de prueba) — nunca se imprimió ningún valor real de secreto en esta sesión.

## Documentación actualizada

`.ai/RISKS.md` R-6 (nota de lecturas reales ejercitadas, sigue ABIERTO para escritura), `.env.example` (advertencia sobre `HRMM_BACKEND_ENV=` vacía vs. no configurada).

## Pendiente (no resuelto aquí, ni inventado)

- Escritura real contra hrmm-backend (reservar/reprogramar/cancelar) — sigue sin ejercitarse, R-6 sigue ABIERTO para ese alcance.
- El usuario debe corregir `HRMM_BACKEND_ENV=` en su `.env` real (borrar la línea o poner `production` explícito) antes de desplegar — no se cambió su archivo real, solo se documentó el hallazgo.
- Registrar el webhook de Telegram y desplegar en EasyPanel — sigue pendiente, sin relación con este cambio.

RECADO GENERADO: /Users/enzoalfonso/recado/025-docker-hrmm-real-verificado.md
