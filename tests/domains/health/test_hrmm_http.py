"""
Recado 082 — hallazgo real de producción (documento 72302972, justo después
de que se reiniciara n8n): un timeout ESPERANDO la respuesta de
hrmm-backend (`http.client.HTTPResponse.begin()`, dentro de
`h.getresponse()`) se propagaba como `socket.timeout` crudo, no como
`HttpError` — confirmado con un traceback real. La razón: `urllib.request`
solo envuelve en `URLError` los fallos de `OSError` ocurridos mientras se
ENVÍA la solicitud (`AbstractHTTPHandler.do_open` solo tiene ese `try/except`
alrededor de `h.request(...)`, nunca alrededor de `h.getresponse()`) — un
timeout esperando/leyendo la respuesta queda fuera de ese `try` y se
propaga sin envolver.

Este archivo reproduce el fallo con un socket TCP real y local (sin red
externa, mismo criterio que el resto de `tests/domains/health/test_hrmm_*.py`
de preferir comportamiento real sobre mocks cuando es barato hacerlo) —
un servidor que acepta la conexión y nunca responde reproduce EXACTAMENTE
el mecanismo del timeout real de producción, no una aproximación.
"""
import socket
import threading

import pytest

from domains.health.hrmm_http import HttpError, RealHttpClient


def _puerto_de_servidor_que_nunca_responde() -> int:
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(1)
    puerto = servidor.getsockname()[1]

    def _aceptar_y_colgar():
        try:
            conexion, _ = servidor.accept()
            try:
                conexion.settimeout(5)
                conexion.recv(65536)  # lee la solicitud completa, nunca contesta nada
            except OSError:
                pass
            finally:
                conexion.close()
        except OSError:
            pass
        finally:
            servidor.close()

    threading.Thread(target=_aceptar_y_colgar, daemon=True).start()
    return puerto


def test_timeout_esperando_la_respuesta_se_convierte_en_http_error():
    puerto = _puerto_de_servidor_que_nunca_responde()
    cliente = RealHttpClient(base_url=f"http://127.0.0.1:{puerto}", timeout_seconds=0.5)

    with pytest.raises(HttpError):
        cliente.request("GET", "/cualquier-ruta")


def test_conexion_rechazada_tambien_se_convierte_en_http_error():
    """Control: un puerto cerrado (nadie escuchando) es otro tipo de
    OSError (`ConnectionRefusedError`) distinto del timeout de arriba —
    confirma que capturar `OSError` (en vez de solo `URLError`) cubre la
    familia completa de fallos de transporte, no un caso puntual."""
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.bind(("127.0.0.1", 0))
    puerto = servidor.getsockname()[1]
    servidor.close()  # puerto liberado, nadie escuchando ahí

    cliente = RealHttpClient(base_url=f"http://127.0.0.1:{puerto}", timeout_seconds=2)

    with pytest.raises(HttpError):
        cliente.request("GET", "/cualquier-ruta")
