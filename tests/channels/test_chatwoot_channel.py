"""
ChatwootChannel — tests con payloads FIJOS (fixtures), sin red real
(recado 012, límite explícito del usuario: nunca forzar una prueba
real si no hay un inbox de prueba disponible)."""
import pytest

from channels.chatwoot_channel import ChatwootChannel, ChatwootChannelError

_WEBHOOK_INCOMING = {
    "event": "message_created",
    "id": 999,
    "content": "hola, quiero una cita",
    "message_type": "incoming",
    "conversation": {"id": 42, "contact_inbox": {"source_id": "573001112233"}},
    "sender": {"phone_number": "573001112233"},
}

_WEBHOOK_OUTGOING_ECO = {**_WEBHOOK_INCOMING, "message_type": "outgoing", "id": 1000}


@pytest.fixture
def llamadas_http():
    return []


@pytest.fixture
def channel(llamadas_http, monkeypatch):
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "token-de-prueba-no-real")

    def _http_post_fake(url, headers, body):
        llamadas_http.append({"url": url, "headers": headers, "body": body})

    return ChatwootChannel(
        base_url="https://chatwoot-de-prueba.example.com",
        account_id="1",
        http_post=_http_post_fake,
    )


def test_webhook_incoming_se_traduce_a_inbound_message(channel):
    mensaje = channel.handle_webhook_payload(_WEBHOOK_INCOMING)
    assert mensaje is not None
    assert mensaje.text == "hola, quiero una cita"
    assert mensaje.conversation_id == "573001112233"
    assert mensaje.canal == "chatwoot"
    assert channel.receive() == mensaje


def test_webhook_eco_de_mensaje_saliente_se_ignora(channel):
    mensaje = channel.handle_webhook_payload(_WEBHOOK_OUTGOING_ECO)
    assert mensaje is None
    with pytest.raises(IndexError):
        channel.receive()  # nada encolado — el eco nunca se procesó


def test_webhook_sin_remitente_falla_explicito(channel):
    payload_sin_remitente = {
        "event": "message_created",
        "id": 1,
        "content": "hola",
        "message_type": "incoming",
        "conversation": {"id": 42, "contact_inbox": {}},
        "sender": {},
    }
    with pytest.raises(ChatwootChannelError, match="remitente"):
        channel.handle_webhook_payload(payload_sin_remitente)


def test_send_responde_a_la_conversacion_correcta(channel, llamadas_http):
    from channels.contract import OutboundMessage

    channel.handle_webhook_payload(_WEBHOOK_INCOMING)
    channel.send(OutboundMessage(conversation_id="573001112233", text="Claro, ¿qué servicio necesitas?"))

    assert len(llamadas_http) == 1
    assert llamadas_http[0]["url"] == "https://chatwoot-de-prueba.example.com/api/v1/accounts/1/conversations/42/messages"
    assert llamadas_http[0]["headers"]["api_access_token"] == "token-de-prueba-no-real"
    assert llamadas_http[0]["body"] == {"content": "Claro, ¿qué servicio necesitas?", "message_type": "outgoing"}


def test_send_sin_conversacion_previa_falla_explicito(channel):
    from channels.contract import OutboundMessage

    with pytest.raises(ChatwootChannelError, match="No hay conversación"):
        channel.send(OutboundMessage(conversation_id="573009998877", text="hola"))


def test_send_sin_token_configurado_falla_explicito(channel, monkeypatch):
    from channels.contract import OutboundMessage

    channel.handle_webhook_payload(_WEBHOOK_INCOMING)
    monkeypatch.delenv("CHATWOOT_API_TOKEN", raising=False)

    with pytest.raises(ChatwootChannelError, match="CHATWOOT_API_TOKEN"):
        channel.send(OutboundMessage(conversation_id="573001112233", text="hola"))
