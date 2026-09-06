# D-8: Chatwoot pasa a ser OPCIONAL al arrancar el servicio

**Decisión**: `service/app.py` ya no exige `CHATWOOT_URL`/`CHATWOOT_ACCOUNT_ID` para arrancar. Si no están configuradas, el canal de Chatwoot queda deshabilitado (`_canal is None`, con un `logger.warning` explícito) y `POST /webhook/chatwoot` responde `503` si alguien lo invoca — el resto del servicio (incluido `TelegramChannel`) funciona con total normalidad.

**Motivo**: el usuario decidió (2026-09-05) usar únicamente el canal de Telegram por ahora — no va a conectar WhatsApp/Instagram vía Chatwoot en esta etapa. Exigir `CHATWOOT_URL`/`CHATWOOT_ACCOUNT_ID` como si fueran imprescindibles (diseño original de recado 011, cuando Chatwoot era el ÚNICO canal) ya no refleja la realidad del proyecto: ahora hay dos canales independientes (D-7), y ninguno debería depender del otro para poder operar.

**Alternativas consideradas**:
1. Mantener Chatwoot obligatorio y pedirle al usuario que configure valores ficticios permanentemente — descartada: ensucia la configuración real con datos falsos indefinidamente, y cualquier futuro intento real de usar Chatwoot heredaría esos placeholders por error si nadie los recuerda cambiar.
2. Quitar `ChatwootChannel`/el endpoint `/webhook/chatwoot` por completo mientras no se use — descartada: es un cambio más grande e innecesario (borra código funcional y probado), y reintroducirlo después repite trabajo. Chatwoot puede volver a activarse en cualquier momento solo configurando las 3 variables, sin tocar código.
3. (Elegida) Configuración opcional: `_canal` puede ser `None`, el endpoint lo maneja explícitamente.

**Ventajas de la opción elegida (3)**:
- Ningún despliegue que solo use Telegram depende de una integración que no va a usar — coherente con el principio general de este proyecto de no exigir configuración sin necesidad real (mismo espíritu que `HRMM_BACKEND_ENV` default seguro `mock`).
- Chatwoot sigue existiendo, probado y listo — reactivarlo en el futuro es solo configurar 3 variables, cero cambios de código.
- Nunca falla en silencio: `logger.warning` al arrancar sin Chatwoot, `503` explícito si se invoca el webhook sin configurar — mismo criterio del proyecto en toda esta capa.

**Desventajas**:
- `service/app.py` gana una rama condicional más (`_canal is None`) — complejidad menor, ya mitigada con un guard simple al inicio del endpoint.
- Si alguien configura mal `CHATWOOT_URL` (typo) en vez de omitirla del todo, el fallo se movería de "no arranca" (antes) a "arranca, pero Chatwoot intentará usar una URL incorrecta cuando se invoque" — mismo nivel de detección que ya existía para `CHATWOOT_API_TOKEN` (siempre fue perezoso, nunca fail-fast).

**Riesgo**: Bajo — `TelegramChannel` y `ChatwootChannel` son objetos completamente independientes dentro de `service/app.py` (ningún estado compartido salvo `_gateway`, que ninguno de los dos cambios toca) — confirmado con dos tests nuevos: arranque limpio sin Chatwoot con Telegram funcionando de punta a punta, y `503` explícito al invocar `/webhook/chatwoot` sin configurar.

**Impacto**: `service/app.py` (`_construir_canal_chatwoot` retorna `Optional[ChatwootChannel]`, guard en `webhook_chatwoot`). `.env.example` (comentario actualizado: ya no "obligatorias"). `.ai/DEPLOYMENT.md`, `.ai/RISKS.md` (R-4), `.ai/API_CONTRACTS.md`, `.ai/ARCHITECTURE.md`. Sin cambios en `ChatwootChannel`, `TelegramChannel`, `domains/health/`, ni en el contrato `Channel`.

**Estado**: IMPLEMENTADA (2026-09-05, recado `024`) — confirmado con Docker real que, con `CHATWOOT_URL`/`CHATWOOT_ACCOUNT_ID`/`CHATWOOT_API_TOKEN` sin configurar (o con placeholders ficticios) y `TELEGRAM_BOT_TOKEN`/`TELEGRAM_WEBHOOK_SECRET` reales, el proceso arranca limpio y `TelegramChannel` responde con normalidad — ver recado `023` (la verificación con Docker real precedió a este cambio y ya usaba placeholders para Chatwoot; este cambio simplemente hace que eso deje de ser necesario).
