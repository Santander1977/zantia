"""
service/app.py — smoke test end-to-end del servicio HTTP (recado 012):
GET /health, y un webhook de Chatwoot completo traducido hasta
MockAppointmentService y de vuelta, sin red real hacia Chatwoot
(se sustituye `_canal.http_post` por un doble de prueba).

`app_module` configura CHATWOOT_URL/CHATWOOT_ACCOUNT_ID/TELEGRAM_WEBHOOK_SECRET
vía monkeypatch antes del import, nunca hardcodeados — Chatwoot en sí ya
NO es obligatorio para que el módulo importe (recado 024, D-8: opcional,
ver `test_arranque_funciona_sin_chatwoot_si_telegram_si_esta_configurado`
más abajo); Telegram (`TELEGRAM_WEBHOOK_SECRET`) SIGUE siendo fail-fast
(recado 023).
"""
import importlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


_TELEGRAM_SECRETO_PRUEBA = "secreto-webhook-de-prueba-no-real"


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.setenv("CHATWOOT_URL", "https://chatwoot-prueba.example.com")
    monkeypatch.setenv("CHATWOOT_ACCOUNT_ID", "1")
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "token-prueba-no-real")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", _TELEGRAM_SECRETO_PRUEBA)
    monkeypatch.delenv("HRMM_BACKEND_ENV", raising=False)  # default seguro: mock

    import service.app as modulo

    importlib.reload(modulo)  # fuerza recomposición con las env vars de este test
    return modulo


def test_health_responde_ok(app_module):
    client = TestClient(app_module.app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_webhook_chatwoot_flujo_completo_con_mock(app_module):
    llamadas = []

    def _http_post_fake(url, headers, body):
        llamadas.append({"url": url, "headers": headers, "body": body})

    with patch.object(app_module._canal, "http_post", _http_post_fake):
        client = TestClient(app_module.app)
        payload = {
            "event": "message_created",
            "id": 1,
            "content": "hola quiero programar una cita de medicina general",
            "message_type": "incoming",
            "conversation": {"id": 77, "contact_inbox": {"source_id": "573001112233"}},
            "sender": {"phone_number": "573001112233"},
        }
        r = client.post("/webhook/chatwoot", json=payload)

    assert r.status_code == 200
    assert r.json() == {"procesado": True, "respondido": True}
    assert len(llamadas) == 1
    assert llamadas[0]["url"] == "https://chatwoot-prueba.example.com/api/v1/accounts/1/conversations/77/messages"
    assert llamadas[0]["body"]["message_type"] == "outgoing"
    assert len(llamadas[0]["body"]["content"]) > 0


def test_webhook_fallo_al_responder_a_chatwoot_no_produce_500(app_module):
    """Regresión de un bug real encontrado con curl contra un servidor
    uvicorn vivo (recado 012): si `_canal.send()` falla (Chatwoot no
    responde), el endpoint debe devolver 200 con el fallo explícito en
    el body — el mensaje del paciente YA fue procesado por el dominio,
    solo la respuesta no llegó — nunca un 500 sin contexto."""
    from channels.chatwoot_channel import ChatwootChannelError

    def _http_post_que_falla(url, headers, body):
        raise ChatwootChannelError("simulado: Chatwoot no responde")

    with patch.object(app_module._canal, "http_post", _http_post_que_falla):
        client = TestClient(app_module.app)
        payload = {
            "event": "message_created",
            "id": 3,
            "content": "hola",
            "message_type": "incoming",
            "conversation": {"id": 90, "contact_inbox": {"source_id": "573005556666"}},
            "sender": {"phone_number": "573005556666"},
        }
        r = client.post("/webhook/chatwoot", json=payload)

    assert r.status_code == 200
    assert r.json()["procesado"] is True
    assert r.json()["respondido"] is False


def test_webhook_ignora_eco_de_mensaje_saliente(app_module):
    client = TestClient(app_module.app)
    payload = {
        "event": "message_created",
        "id": 2,
        "content": "esto lo mandamos nosotros",
        "message_type": "outgoing",
        "conversation": {"id": 77, "contact_inbox": {"source_id": "573001112233"}},
        "sender": {"phone_number": "573001112233"},
    }
    r = client.post("/webhook/chatwoot", json=payload)
    assert r.status_code == 200
    assert r.json() == {"procesado": False}


def test_webhook_telegram_flujo_completo_con_mock(app_module, monkeypatch):
    """Smoke test end-to-end del canal Telegram (recado 022): mismo
    patrón que test_webhook_chatwoot_flujo_completo_con_mock, pero sin
    necesitar ninguna variable de entorno estructural (TelegramChannel
    no tiene — ver service/app.py) — solo el token, para poder enviar."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-prueba-no-real")
    llamadas = []

    def _http_post_fake(url, body):
        llamadas.append({"url": url, "body": body})
        return {"ok": True, "result": {"message_id": 1}}

    with patch.object(app_module._canal_telegram, "http_post", _http_post_fake):
        client = TestClient(app_module.app)
        payload = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "chat": {"id": 555111222, "type": "private"},
                "text": "hola quiero programar una cita de medicina general",
            },
        }
        r = client.post(
            "/webhook/telegram", json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": _TELEGRAM_SECRETO_PRUEBA},
        )

    assert r.status_code == 200
    assert r.json() == {"procesado": True, "respondido": True}
    # Recado 056, Punto 4: al menos 1 `sendChatAction` (typing) ANTES del
    # `sendMessage` real — el procesamiento de este test es rápido
    # (Mock, sin red real), así que normalmente es exactamente 1, pero
    # no se asume un conteo exacto (la tarea de fondo podría alcanzar a
    # repetirlo si la máquina de CI va lenta).
    llamadas_typing = [l for l in llamadas if l["url"].endswith("/sendChatAction")]
    llamadas_mensaje = [l for l in llamadas if l["url"].endswith("/sendMessage")]
    assert len(llamadas_typing) >= 1
    assert llamadas_typing[0]["body"] == {"chat_id": 555111222, "action": "typing"}
    assert len(llamadas_mensaje) == 1
    assert llamadas_mensaje[0]["body"]["chat_id"] == 555111222
    assert len(llamadas_mensaje[0]["body"]["text"]) > 0
    # El indicador de escritura siempre llega ANTES que el mensaje real.
    assert llamadas.index(llamadas_typing[0]) < llamadas.index(llamadas_mensaje[0])


def test_webhook_telegram_repite_indicador_de_escritura_si_el_procesamiento_tarda(app_module, monkeypatch):
    """Recado 056, Punto 4 — si el procesamiento real (ej. latencia de un
    LLM) tarda más que un solo intervalo, el indicador de escritura debe
    repetirse — nunca desaparecer a mitad de una respuesta lenta.
    Intervalo acelerado a 0.05s (en vez de 4s reales) para no volver la
    prueba lenta; el procesamiento simulado tarda 0.17s (> 3 intervalos)."""
    import time

    monkeypatch.setattr(app_module, "_INTERVALO_INDICADOR_ESCRITURA_SEGUNDOS", 0.05)

    def _procesamiento_lento(*args, **kwargs):
        time.sleep(0.17)
        return "listo"

    monkeypatch.setattr(app_module, "handle_inbound_message", _procesamiento_lento)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-prueba-no-real")

    llamadas = []

    def _http_post_fake(url, body):
        llamadas.append(body)
        return {"ok": True, "result": {"message_id": 1}}

    with patch.object(app_module._canal_telegram, "http_post", _http_post_fake):
        client = TestClient(app_module.app)
        r = client.post(
            "/webhook/telegram",
            json={
                "update_id": 1,
                "message": {"message_id": 1, "chat": {"id": 555333111}, "text": "cualquier cosa"},
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": _TELEGRAM_SECRETO_PRUEBA},
        )

    assert r.status_code == 200
    llamadas_typing = [b for b in llamadas if b.get("action") == "typing"]
    assert len(llamadas_typing) >= 2, (
        f"debía repetir el indicador de escritura durante un procesamiento lento: {llamadas!r}"
    )


def test_webhook_telegram_ignora_update_sin_mensaje_de_texto(app_module):
    client = TestClient(app_module.app)
    payload = {"update_id": 2, "callback_query": {"id": "abc", "data": "algo"}}
    r = client.post(
        "/webhook/telegram", json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": _TELEGRAM_SECRETO_PRUEBA},
    )
    assert r.status_code == 200
    assert r.json() == {"procesado": False}


def test_webhook_telegram_fallo_al_responder_no_produce_500(app_module, monkeypatch):
    """Regresión análoga a test_webhook_fallo_al_responder_a_chatwoot_no_produce_500
    (recado 012) — mismo criterio aplicado a Telegram."""
    from channels.telegram_channel import TelegramChannelError

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-prueba-no-real")

    def _http_post_que_falla(url, body):
        raise TelegramChannelError("simulado: Telegram no responde")

    with patch.object(app_module._canal_telegram, "http_post", _http_post_que_falla):
        client = TestClient(app_module.app)
        payload = {
            "update_id": 3,
            "message": {"message_id": 11, "chat": {"id": 555111223}, "text": "hola"},
        }
        r = client.post(
            "/webhook/telegram", json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": _TELEGRAM_SECRETO_PRUEBA},
        )

    assert r.status_code == 200
    assert r.json()["procesado"] is True
    assert r.json()["respondido"] is False


def test_webhook_telegram_sin_secret_token_correcto_rechaza_con_401(app_module):
    """Cierra R-23 (recado 023): sin el header correcto, la petición se
    rechaza con 401 ANTES de procesar nada — ni siquiera llega a
    `handle_webhook_payload`/al dominio."""
    client = TestClient(app_module.app)
    payload = {
        "update_id": 4,
        "message": {"message_id": 12, "chat": {"id": 555111224}, "text": "hola"},
    }

    sin_header = client.post("/webhook/telegram", json=payload)
    assert sin_header.status_code == 401
    assert sin_header.json()["procesado"] is False

    con_header_incorrecto = client.post(
        "/webhook/telegram", json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "un-valor-cualquiera-inventado"},
    )
    assert con_header_incorrecto.status_code == 401
    assert con_header_incorrecto.json()["procesado"] is False


def test_webhook_telegram_con_secret_token_correcto_se_procesa_normal(app_module):
    """Contraparte del test anterior (recado 023, requisito #3): CON el
    header correcto, la petición se procesa con normalidad — mismo
    payload, único cambio es el header."""
    client = TestClient(app_module.app)
    payload = {
        "update_id": 5,
        "message": {"message_id": 13, "chat": {"id": 555111225}, "text": "hola quiero consultar mi cita"},
    }

    with patch.object(app_module._canal_telegram, "http_post", lambda url, body: {"ok": True}):
        r = client.post(
            "/webhook/telegram", json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": _TELEGRAM_SECRETO_PRUEBA},
        )

    assert r.status_code == 200
    assert r.json()["procesado"] is True


def test_arranque_falla_sin_telegram_webhook_secret(monkeypatch):
    """Fail-fast al importar el módulo (recado 023) — a diferencia de
    Chatwoot (opcional desde recado 024, ver tests abajo),
    TELEGRAM_WEBHOOK_SECRET sigue siendo obligatoria: sin ella, el
    proceso no debe arrancar con una superficie insegura expuesta."""
    monkeypatch.setenv("CHATWOOT_URL", "https://chatwoot-prueba.example.com")
    monkeypatch.setenv("CHATWOOT_ACCOUNT_ID", "1")
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "token-prueba-no-real")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("HRMM_BACKEND_ENV", raising=False)

    from domains.health.config import HealthConfigError

    import service.app as modulo

    with pytest.raises(HealthConfigError, match="TELEGRAM_WEBHOOK_SECRET"):
        importlib.reload(modulo)


# ---------------------------------------------------------------------
# Chatwoot opcional (recado 024, decisión D-8).
# ---------------------------------------------------------------------
def test_arranque_funciona_sin_chatwoot_si_telegram_si_esta_configurado(monkeypatch):
    """Requisito del pedido: un despliegue que solo use Telegram no debe
    depender de Chatwoot para arrancar. Confirma arranque limpio, canal
    de Chatwoot deshabilitado (`_canal is None`), y que Telegram
    funciona 100% normal en ese mismo proceso."""
    monkeypatch.delenv("CHATWOOT_URL", raising=False)
    monkeypatch.delenv("CHATWOOT_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CHATWOOT_API_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", _TELEGRAM_SECRETO_PRUEBA)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-prueba-no-real")
    monkeypatch.delenv("HRMM_BACKEND_ENV", raising=False)

    import service.app as modulo

    importlib.reload(modulo)  # no debe lanzar HealthConfigError

    assert modulo._canal is None

    client = TestClient(modulo.app)
    assert client.get("/health").status_code == 200

    llamadas = []

    def _http_post_fake(url, body):
        llamadas.append(body)
        return {"ok": True}

    with patch.object(modulo._canal_telegram, "http_post", _http_post_fake):
        r = client.post(
            "/webhook/telegram",
            json={
                "update_id": 1,
                "message": {"message_id": 1, "chat": {"id": 555999888}, "text": "hola quiero una cita"},
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": _TELEGRAM_SECRETO_PRUEBA},
        )

    assert r.status_code == 200
    assert r.json() == {"procesado": True, "respondido": True}
    # Recado 056, Punto 4: al menos 1 llamada de `sendChatAction` (typing)
    # + 1 de `sendMessage` real — ya no exactamente 1 en total.
    assert len(llamadas) >= 2
    assert any(b.get("action") == "typing" for b in llamadas)
    assert any("text" in b for b in llamadas)


# ---------------------------------------------------------------------
# WebChannel (recado 078/079) — contrato exacto {message, sessionId} -> {reply}.
# ---------------------------------------------------------------------
def test_webhook_web_contrato_exacto_message_sessionid_a_reply(app_module):
    """Prueba de contrato (regla de `.claude/rules/testing.md`): confirma
    la FORMA exacta que ya espera el Express de `eis-chat-hrmm` (recado
    077) — entrada `{message, sessionId}`, salida ÚNICAMENTE `{"reply": str}`,
    sin `success`/`sessionId` extra (a diferencia del contrato viejo con
    n8n) — si esta forma cambia sin querer, este test debe fallar."""
    client = TestClient(app_module.app)
    r = client.post("/webhook/web", json={"message": "hola", "sessionId": "1789169744021"})

    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo.keys()) == {"reply"}
    assert isinstance(cuerpo["reply"], str)
    assert len(cuerpo["reply"]) > 0


def test_webhook_web_sesion_persiste_entre_mensajes_del_mismo_sessionid(app_module):
    """Confirma la correlación de conversación (`find_open_context`) vía
    `sessionId` — dos peticiones HTTP separadas con el MISMO `sessionId`
    (tal como lo reenvía el Express de `eis-chat-hrmm` mensaje a mensaje,
    ahora persistente en localStorage del navegador) deben verse como la
    MISMA conversación, no dos independientes."""
    client = TestClient(app_module.app)
    session_id = "1789169799840"

    r1 = client.post("/webhook/web", json={"message": "hola", "sessionId": session_id})
    assert r1.status_code == 200
    assert "andrés" in r1.json()["reply"].lower() or "buenos" in r1.json()["reply"].lower() or "buenas" in r1.json()["reply"].lower()

    r2 = client.post("/webhook/web", json={"message": "1", "sessionId": session_id})
    assert r2.status_code == 200
    # Segundo turno: ya no debe repetir la presentación institucional
    # completa (`_saludo_primer_contacto` solo se antepone una vez).
    assert "soy andrés" not in r2.json()["reply"].lower()


def test_webhook_web_sin_message_responde_200_con_reply_generico(app_module):
    """Requisito explícito del pedido: nunca un 500 crudo que rompa el
    widget — un payload malformado (falta `message`, ej. un bug del lado
    de `eis-chat-hrmm` o cualquiera que descubra la URL sin secreto que
    verificar, ver `.ai/RISKS.md` R-26) responde 200 con un mensaje
    genérico, nunca un error crudo."""
    client = TestClient(app_module.app)
    r = client.post("/webhook/web", json={"sessionId": "1789169744021"})
    assert r.status_code == 200
    assert set(r.json().keys()) == {"reply"}
    assert len(r.json()["reply"]) > 0


def test_webhook_web_sin_session_id_responde_200_con_reply_generico(app_module):
    client = TestClient(app_module.app)
    r = client.post("/webhook/web", json={"message": "hola"})
    assert r.status_code == 200
    assert set(r.json().keys()) == {"reply"}


def test_webhook_web_body_no_json_responde_200_con_reply_generico(app_module):
    client = TestClient(app_module.app)
    r = client.post("/webhook/web", content=b"esto no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert set(r.json().keys()) == {"reply"}


def test_webhook_web_fallo_interno_no_produce_500(app_module, monkeypatch):
    """Regresión análoga a `test_webhook_fallo_al_responder_a_chatwoot_no_produce_500`
    (recado 012) y `test_webhook_telegram_fallo_al_responder_no_produce_500`
    (recado 022/023), pero para un fallo INTERNO genuino del dominio (no
    solo un fallo de canal al responder, que acá ni siquiera existe como
    llamada de red — ver `channels/web_channel.py`): simula que
    `handle_inbound_message` lanza una excepción no anticipada."""

    def _handle_inbound_message_que_falla(*args, **kwargs):
        raise RuntimeError("fallo simulado no anticipado del dominio")

    monkeypatch.setattr(app_module, "handle_inbound_message", _handle_inbound_message_que_falla)

    client = TestClient(app_module.app)
    r = client.post("/webhook/web", json={"message": "hola", "sessionId": "1789169744021"})

    assert r.status_code == 200
    assert set(r.json().keys()) == {"reply"}
    assert len(r.json()["reply"]) > 0


def test_webhook_web_flujo_completo_end_to_end(app_module):
    """Al menos 1 prueba real end-to-end (requisito explícito del pedido)
    simulando una conversación completa vía este canal nuevo, contra el
    Orchestrator/HealthBrain/guardrails REALES (sin ningún cambio ahí) —
    solo `MockAppointmentService` (el default de `app_module`, sin
    `HRMM_BACKEND_ENV`) evita red real hacia hrmm-backend, mismo criterio
    que `test_webhook_telegram_flujo_completo_con_mock`. Guion basado en
    el mismo catálogo/disponibilidad por defecto de `MockAppointmentService`
    (`domains/health/appointment_service.py:_seed_fictional_data`, un solo
    servicio real: "medicina general")."""
    client = TestClient(app_module.app)
    session_id = "1789169812626"

    # Turno 1 — saludo institucional de primer contacto, sin conversación
    # abierta todavía (mensaje sin intención reconocible).
    r1 = client.post("/webhook/web", json={"message": "hola", "sessionId": session_id})
    assert r1.status_code == 200
    r1_texto = r1.json()["reply"].lower()
    assert "andrés" in r1_texto
    assert "1. reservar una cita" in r1_texto

    # Turno 2 — responde al menú numerado ("1" = reservar), MISMO
    # sessionId: debe reconocerse como continuación, no un mensaje nuevo
    # sin contexto.
    r2 = client.post("/webhook/web", json={"message": "1", "sessionId": session_id})
    assert r2.status_code == 200
    r2_texto = r2.json()["reply"].lower()
    assert "fechas disponibles" in r2_texto or "medicina general" in r2_texto or "horarios disponibles" in r2_texto

    # Turno 3 — elige la primera fecha ofrecida.
    r3 = client.post("/webhook/web", json={"message": "1", "sessionId": session_id})
    assert r3.status_code == 200
    r3_texto = r3.json()["reply"].lower()
    assert len(r3_texto) > 0

    # Turno 4 — elige el primer horario ofrecido (si el turno anterior
    # ya ofreció horarios) o sigue el guion — en cualquier caso, la
    # conversación avanza sin caer en un error genérico ni en un 500.
    r4 = client.post("/webhook/web", json={"message": "1", "sessionId": session_id})
    assert r4.status_code == 200
    assert "no se pudo procesar" not in r4.json()["reply"].lower()
    assert "problema procesando" not in r4.json()["reply"].lower()


def test_webhook_chatwoot_sin_configurar_responde_503_explicito(monkeypatch):
    """Contraparte del test anterior: si SÍ se invoca /webhook/chatwoot
    sin que esté configurado, nunca un 500 ni un silencio — 503 explícito."""
    monkeypatch.delenv("CHATWOOT_URL", raising=False)
    monkeypatch.delenv("CHATWOOT_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CHATWOOT_API_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", _TELEGRAM_SECRETO_PRUEBA)
    monkeypatch.delenv("HRMM_BACKEND_ENV", raising=False)

    import service.app as modulo

    importlib.reload(modulo)

    client = TestClient(modulo.app)
    r = client.post(
        "/webhook/chatwoot",
        json={
            "event": "message_created", "id": 1, "content": "hola", "message_type": "incoming",
            "conversation": {"id": 1, "contact_inbox": {"source_id": "573000000000"}},
            "sender": {"phone_number": "573000000000"},
        },
    )
    assert r.status_code == 503
    assert r.json()["procesado"] is False
