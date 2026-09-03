"""
service/app.py — smoke test end-to-end del servicio HTTP (recado 012):
GET /health, y un webhook de Chatwoot completo traducido hasta
MockAppointmentService y de vuelta, sin red real hacia Chatwoot
(se sustituye `_canal.http_post` por un doble de prueba).

Requiere CHATWOOT_URL/CHATWOOT_ACCOUNT_ID en el entorno para que el
módulo pueda importarse (arranque fail-fast) — se inyectan vía
monkeypatch antes del import, nunca hardcodeados.
"""
import importlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.setenv("CHATWOOT_URL", "https://chatwoot-prueba.example.com")
    monkeypatch.setenv("CHATWOOT_ACCOUNT_ID", "1")
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "token-prueba-no-real")
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
