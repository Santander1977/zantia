"""
TelegramChannel — tests con payloads FIJOS (fixtures), sin red real
(mismo criterio que test_chatwoot_channel.py, recado 012)."""
import pytest

from channels.telegram_channel import TelegramChannel, TelegramChannelError

_UPDATE_INCOMING = {
    "update_id": 100001,
    "message": {
        "message_id": 55,
        "from": {"id": 987654321, "is_bot": False, "first_name": "Juan"},
        "chat": {"id": 987654321, "type": "private"},
        "date": 1735689600,
        "text": "hola, quiero una cita",
    },
}

_UPDATE_EDITED_MESSAGE = {
    "update_id": 100002,
    "edited_message": {
        "message_id": 55,
        "chat": {"id": 987654321, "type": "private"},
        "text": "hola, quiero una cita (editado)",
    },
}

_UPDATE_SIN_TEXTO = {
    "update_id": 100003,
    "message": {
        "message_id": 56,
        "chat": {"id": 987654321, "type": "private"},
        "photo": [{"file_id": "ABC"}],
    },
}


@pytest.fixture
def llamadas_http():
    return []


@pytest.fixture
def channel(llamadas_http, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-de-prueba-no-real")

    def _http_post_fake(url, body):
        llamadas_http.append({"url": url, "body": body})
        return {"ok": True, "result": {"message_id": 999}}

    return TelegramChannel(http_post=_http_post_fake)


def test_update_con_texto_se_traduce_a_inbound_message(channel):
    mensaje = channel.handle_webhook_payload(_UPDATE_INCOMING)
    assert mensaje is not None
    assert mensaje.text == "hola, quiero una cita"
    assert mensaje.conversation_id == "987654321"
    assert mensaje.canal == "telegram"
    assert channel.receive() == mensaje


def test_update_sin_message_se_ignora(channel):
    """edited_message/callback_query/channel_post/etc. — cualquier
    Update que no tenga la clave "message" se ignora sin error."""
    mensaje = channel.handle_webhook_payload(_UPDATE_EDITED_MESSAGE)
    assert mensaje is None
    with pytest.raises(IndexError):
        channel.receive()


def test_update_sin_texto_se_ignora(channel):
    """Foto/sticker/audio sin texto — nada que este dominio pueda
    interpretar todavía, se ignora sin error (no es un payload malformado)."""
    mensaje = channel.handle_webhook_payload(_UPDATE_SIN_TEXTO)
    assert mensaje is None
    with pytest.raises(IndexError):
        channel.receive()


def test_update_con_texto_sin_chat_id_falla_explicito(channel):
    payload_sin_chat = {
        "update_id": 100004,
        "message": {"message_id": 57, "chat": {}, "text": "hola"},
    }
    with pytest.raises(TelegramChannelError, match="chat.id"):
        channel.handle_webhook_payload(payload_sin_chat)


def test_send_llama_a_sendmessage_con_el_chat_id_correcto(channel, llamadas_http):
    from channels.contract import OutboundMessage

    channel.handle_webhook_payload(_UPDATE_INCOMING)
    channel.send(OutboundMessage(conversation_id="987654321", text="Claro, ¿qué servicio necesitas?"))

    assert len(llamadas_http) == 1
    assert llamadas_http[0]["url"] == "https://api.telegram.org/bottoken-de-prueba-no-real/sendMessage"
    assert llamadas_http[0]["body"] == {"chat_id": 987654321, "text": "Claro, ¿qué servicio necesitas?"}
    assert channel.sent == [OutboundMessage(conversation_id="987654321", text="Claro, ¿qué servicio necesitas?")]


def test_send_sin_recibir_antes_tambien_funciona(channel, llamadas_http):
    """A diferencia de ChatwootChannel, TelegramChannel NO necesita
    haber recibido un mensaje antes de poder enviar — `chat_id` (el
    identificador de canal) es autosuficiente, no existe una tabla
    `_conversaciones_*` que poblar primero (ver docstring del módulo)."""
    from channels.contract import OutboundMessage

    channel.send(OutboundMessage(conversation_id="111222333", text="hola"))
    assert len(llamadas_http) == 1
    assert llamadas_http[0]["body"]["chat_id"] == 111222333


def test_send_sin_token_configurado_falla_explicito(channel, monkeypatch):
    from channels.contract import OutboundMessage

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(TelegramChannelError, match="TELEGRAM_BOT_TOKEN"):
        channel.send(OutboundMessage(conversation_id="987654321", text="hola"))


def test_send_respuesta_ok_false_falla_explicito(monkeypatch):
    from channels.contract import OutboundMessage

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-de-prueba-no-real")

    def _http_post_ok_false(url, body):
        return {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}

    channel = TelegramChannel(http_post=_http_post_ok_false)
    with pytest.raises(TelegramChannelError, match="sin éxito"):
        channel.send(OutboundMessage(conversation_id="987654321", text="hola"))


# ---------------------------------------------------------------------
# Verificación del secreto de webhook (recado 023, cierra R-23).
# ---------------------------------------------------------------------
def test_verificar_secreto_webhook_coincide(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secreto-webhook-de-prueba-no-real")
    channel = TelegramChannel()
    assert channel.verificar_secreto_webhook("secreto-webhook-de-prueba-no-real") is True


def test_verificar_secreto_webhook_no_coincide(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secreto-webhook-de-prueba-no-real")
    channel = TelegramChannel()
    assert channel.verificar_secreto_webhook("un-valor-cualquiera-inventado") is False


def test_verificar_secreto_webhook_header_ausente_no_coincide(monkeypatch):
    """El header puede llegar ausente (`None`, ej. una petición que ni
    siquiera lo manda) — nunca debe tratarse como si coincidiera con
    nada, ni lanzar un error de tipo por comparar contra `None`."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secreto-webhook-de-prueba-no-real")
    channel = TelegramChannel()
    assert channel.verificar_secreto_webhook(None) is False


def test_verificar_secreto_webhook_sin_variable_configurada_falla_explicito(monkeypatch):
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    channel = TelegramChannel()
    with pytest.raises(TelegramChannelError, match="TELEGRAM_WEBHOOK_SECRET"):
        channel.verificar_secreto_webhook("cualquier-cosa")
