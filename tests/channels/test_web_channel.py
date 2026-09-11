"""
WebChannel — tests unitarios, sin red real (no hay ninguna función de
red en este canal, a diferencia de TelegramChannel/ChatwootChannel —
ver docstring de `channels/web_channel.py`)."""
import pytest

from channels.contract import OutboundMessage
from channels.web_channel import WebChannel, WebChannelError


@pytest.fixture
def channel():
    return WebChannel()


def test_handle_request_traduce_a_inbound_message(channel):
    mensaje = channel.handle_request(message="hola, quiero una cita", session_id="1789169744021")
    assert mensaje.text == "hola, quiero una cita"
    assert mensaje.conversation_id == "1789169744021"
    assert mensaje.canal == "web"
    assert channel.receive() == mensaje


def test_handle_request_sin_session_id_falla_explicito(channel):
    with pytest.raises(WebChannelError, match="sessionId"):
        channel.handle_request(message="hola", session_id="")
    with pytest.raises(WebChannelError, match="sessionId"):
        channel.handle_request(message="hola", session_id=None)


def test_handle_request_sin_message_falla_explicito(channel):
    with pytest.raises(WebChannelError, match="message"):
        channel.handle_request(message="", session_id="1789169744021")
    with pytest.raises(WebChannelError, match="message"):
        channel.handle_request(message=None, session_id="1789169744021")


def test_send_no_toca_red_solo_registra(channel):
    """A diferencia de TelegramChannel.send()/ChatwootChannel.send(), este
    `send()` nunca hace ninguna llamada HTTP — el handler de
    `service/app.py` ya tiene el texto en una variable local y lo
    devuelve directo en la misma respuesta; `send()` solo deja
    constancia en `sent` (auditoría, mismo criterio que los otros
    canales)."""
    channel.send(OutboundMessage(conversation_id="1789169744021", text="Claro, ¿qué servicio necesitas?"))
    assert channel.sent == [OutboundMessage(conversation_id="1789169744021", text="Claro, ¿qué servicio necesitas?")]


def test_receive_sin_mensajes_encolados_falla_como_los_demas_canales(channel):
    """Mismo comportamiento que MockChannel/TelegramChannel: `receive()`
    sin nada encolado propaga `IndexError` (deque vacío) — nunca inventa
    un mensaje ni devuelve `None` en silencio."""
    with pytest.raises(IndexError):
        channel.receive()


def test_cada_mensaje_recibe_un_message_id_distinto(channel):
    m1 = channel.handle_request(message="hola", session_id="s1")
    m2 = channel.handle_request(message="quiero una cita", session_id="s1")
    assert m1.message_id != m2.message_id
    assert channel.receive() == m1
    assert channel.receive() == m2
