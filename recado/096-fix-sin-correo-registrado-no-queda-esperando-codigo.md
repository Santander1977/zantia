# RECADO PARA CHATGPT

Fecha: 2026-09-30
Proyecto: ZANTIA (repo `icaco`)
Tema: Corrección del bucle de verificación cuando hrmm-backend no envía el código (R-28, hallazgo 2 del recado 094)
Objetivo de la investigación: Desbloquear las pruebas reales por el chat web aplicando la opción (b) del recado 094.

## Resumen ejecutivo

- HECHO: el bucle que bloqueaba el chat web desde el primer paso estaba en el **gate de identidad** (`_iniciar_verificacion_de_identidad`), no solo en cancelar o reprogramar. Los dos caminos guardaban `stage: "esperando_codigo"` aunque hrmm-backend respondiera `enviado=false`.
- HECHO: corregido en `domains/health/gateway.py`. Si no se envió un código, **ningún wizard queda esperando uno** (se descarta `_pending_identity` o `_pending_verifications`), y el paciente recibe un mensaje que:
  - dice explícitamente que **no se envió ningún código** y que no necesita escribir uno;
  - en el caso "sin correo registrado", **nunca** sugiere reintentar, porque es una condición permanente;
  - ofrece los canales reales de `INFORMACION_HOSPITAL`: teléfono 607-6010104, el correo de citas y la sede.
- `_reenviar_codigo` se deja igual a propósito: ahí ya hubo un código real enviado antes, y seguir esperándolo tiene sentido.
- Evidencia: 2 tests de regresión nuevos (`tests/domains/health/corpus_regresion/test_recado096_sin_correo_registrado_no_queda_esperando_codigo.py`), uno por camino. **Fallan sin la corrección y pasan con ella.** Además comprueban que el texto libre del paciente ya no viaja a hrmm como `codigo`. Se actualizaron 2 aserciones de `test_envio_de_codigo_honesto.py` que exigían el comportamiento anterior (decisión del recado 081, reemplazada). Suite completa: **640 passed, 17 skipped**.

## Decisiones o conclusiones

- Como hrmm no devuelve un motivo estructurado, el caso "sin correo" se reconoce por su texto real (`"correo registrado"`, `hrmm/backend/app/api/agenda.py:252`). Esto es frágil ante un cambio de ese texto. Si pasa, el efecto es benigno: se muestra el mensaje de fallo transitorio, que también cierra el wizard y ofrece los mismos canales. La opción (a), un campo `motivo` en hrmm, sigue siendo la corrección de fondo y exige un cambio de contrato en otro repo.
- Tras el mensaje, el siguiente mensaje del paciente reinicia el flujo normal: en el chat web, el gate vuelve a pedir el documento.

## Pendiente

1. **Redeploy manual en EasyPanel** (regla fija, `.ai/DEPLOYMENT.md`).
2. Verificación en producción: repetir la prueba del chat web con el documento sin correo registrado. Debe aparecer el mensaje nuevo, y un mensaje siguiente no debe producir "Ese código no es válido". Si se confirma, R-28 pasa a RESUELTO.
3. Opción (a) del recado 094, coordinada con hrmm-backend.
