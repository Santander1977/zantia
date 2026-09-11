"""
Recado 076 — mecanismo GENÉRICO (agnóstico de dominio) para "un evento
con timestamp real + una ventana de tiempo configurable, con
comportamiento distinto dentro vs. fuera de esa ventana". Extraído de
`domains/health/gateway.py:_cierre_reciente` (recados 057/067/069/071),
donde ya se probó en producción real.

Ejemplos deliberadamente NO relacionados con salud — un "trámite" de
soporte genérico para el modo BLOQUEO, y un "caso de seguridad
ciudadana" (el dominio futuro real que motivó esta extracción) para
confirmar que el modo ABIERTA es estructuralmente soportable — mismo
criterio ya usado en `tests/core/test_selection.py` (recado 052)."""
from datetime import datetime, timedelta, timezone

from core.timed_state import ModoVentana, TimedStateStore, VentanaDeTiempo


# ---------------------------------------------------------------------
# 1. Modo BLOQUEO — mismo patrón ya en producción real en ZANTIA
#    (enfriamiento de 2 minutos tras una despedida, recados 067/069/071).
#    Dominio ficticio: un "trámite" de soporte que, al cerrarse, deja
#    un enfriamiento de 5 minutos antes de aceptar un trámite nuevo.
# ---------------------------------------------------------------------
_VENTANA_ENFRIAMIENTO_TRAMITE = VentanaDeTiempo(
    duracion=timedelta(minutes=5), modo=ModoVentana.BLOQUEO, nombre="enfriamiento_tramite"
)


def _texto_bloqueo(restante: timedelta) -> str:
    """Simula lo que haría un dominio real (ej. `_mensaje_enfriamiento`
    en ZANTIA): decide el texto a partir del tiempo restante que el
    Core calculó — el Core nunca genera texto de dominio."""
    minutos, segundos = divmod(int(restante.total_seconds()) + 1, 60)
    return f"Trámite en pausa — disponible de nuevo en {minutos} min {segundos} s."


def test_bloqueo_informa_tiempo_restante_real_mientras_dura_la_ventana():
    store = TimedStateStore()
    store.registrar("USUARIO-1", payload={"motivo": "cierre_definitivo"})

    assert store.dentro_de_ventana("USUARIO-1", _VENTANA_ENFRIAMIENTO_TRAMITE)
    restante = store.tiempo_restante("USUARIO-1", _VENTANA_ENFRIAMIENTO_TRAMITE)
    assert restante is not None and restante <= timedelta(minutes=5)
    assert "Trámite en pausa" in _texto_bloqueo(restante)


def test_bloqueo_tiempo_restante_disminuye_con_tiempo_real_transcurrido():
    """Mismo requisito ya probado con tiempo real (no simulado) en
    ZANTIA (recado 070/071): el tiempo restante se CALCULA en cada
    consulta contra el timestamp guardado, nunca un cronómetro que se
    actualiza solo."""
    store = TimedStateStore()
    momento_inicial = datetime.now(timezone.utc) - timedelta(minutes=1)  # ya pasó 1 min real
    store.registrar("USUARIO-2", payload=None, ahora=momento_inicial)

    restante = store.tiempo_restante("USUARIO-2", _VENTANA_ENFRIAMIENTO_TRAMITE)
    assert restante is not None
    # De los 5 minutos, ya pasó ~1 — debe quedar razonablemente cerca de 4.
    assert timedelta(minutes=3, seconds=55) < restante <= timedelta(minutes=4, seconds=1)


def test_bloqueo_deja_de_aplicar_pasada_la_ventana():
    store = TimedStateStore()
    momento_viejo = datetime.now(timezone.utc) - timedelta(minutes=6)
    store.registrar("USUARIO-3", payload=None, ahora=momento_viejo)

    assert not store.dentro_de_ventana("USUARIO-3", _VENTANA_ENFRIAMIENTO_TRAMITE)
    assert store.tiempo_restante("USUARIO-3", _VENTANA_ENFRIAMIENTO_TRAMITE) == timedelta(0)


def test_transcurrido_y_dentro_de_ventana_none_si_nunca_se_registro():
    store = TimedStateStore()
    assert store.transcurrido("NUNCA-VISTO") is None
    assert store.tiempo_restante("NUNCA-VISTO", _VENTANA_ENFRIAMIENTO_TRAMITE) is None
    assert not store.dentro_de_ventana("NUNCA-VISTO", _VENTANA_ENFRIAMIENTO_TRAMITE)
    assert "NUNCA-VISTO" not in store


def test_registrar_reemplaza_por_completo_una_entrada_existente():
    store = TimedStateStore()
    store.registrar("USUARIO-4", payload="primero")
    store.registrar("USUARIO-4", payload="segundo")
    assert store.obtener_payload("USUARIO-4") == "segundo"


# ---------------------------------------------------------------------
# 2. Modo ABIERTA — SIN uso real todavía (ningún dominio de este
#    proyecto lo usa en producción), pero confirmado ESTRUCTURALMENTE
#    soportable: un dominio futuro puede ir acumulando contenido nuevo
#    (evidencia) contra el MISMO evento, sin reiniciar la ventana.
#
#    Ejemplo ilustrativo (el dominio futuro real): un caso de seguridad
#    ciudadana se crea y confirma; durante los 5 minutos siguientes, el
#    ciudadano puede seguir adjuntando evidencia (fotos, descripciones)
#    ANTES del cierre formal — a diferencia del enfriamiento de ZANTIA,
#    acá SÍ se procesa contenido nuevo mientras la ventana está abierta.
#    Ninguna lógica de negocio real de ese dominio vive acá — es
#    puramente una prueba de que el mecanismo genérico no le es
#    estructuralmente imposible (requisito explícito del recado 076).
# ---------------------------------------------------------------------
_VENTANA_EVIDENCIA_CASO = VentanaDeTiempo(
    duracion=timedelta(minutes=5), modo=ModoVentana.ABIERTA, nombre="ventana_evidencia"
)


def test_modo_abierta_acepta_contenido_nuevo_sin_reiniciar_la_ventana():
    store = TimedStateStore()
    momento_creacion = datetime.now(timezone.utc) - timedelta(minutes=2)  # el caso se creó hace 2 min
    store.registrar("CASO-100", payload={"evidencia": []}, ahora=momento_creacion)

    # Sigue dentro de la ventana de 5 min (solo pasaron 2) — el dominio
    # (simulado acá, no implementado de verdad) decide ACEPTAR la
    # evidencia nueva en vez de bloquear, justamente porque el modo es
    # ABIERTA — el Core nunca toma esa decisión por sí solo.
    assert store.dentro_de_ventana("CASO-100", _VENTANA_EVIDENCIA_CASO)

    payload_actual = store.obtener_payload("CASO-100")
    payload_actual["evidencia"].append("foto1.jpg")
    exito = store.actualizar_payload("CASO-100", payload_actual)
    assert exito is True

    # Clave: el momento ORIGINAL no cambió — adjuntar evidencia nueva
    # nunca extiende el plazo de la ventana (a propósito, para que un
    # ciudadano no pueda mantener un caso abierto indefinidamente solo
    # con seguir adjuntando contenido).
    assert store.momento_de("CASO-100") == momento_creacion
    assert store.obtener_payload("CASO-100")["evidencia"] == ["foto1.jpg"]

    # Una segunda pieza de evidencia, mismo criterio — se acumula.
    payload_actual = store.obtener_payload("CASO-100")
    payload_actual["evidencia"].append("descripcion.txt")
    store.actualizar_payload("CASO-100", payload_actual)
    assert store.obtener_payload("CASO-100")["evidencia"] == ["foto1.jpg", "descripcion.txt"]
    assert store.momento_de("CASO-100") == momento_creacion  # sigue sin cambiar


def test_modo_abierta_ventana_vencida_ya_no_deberia_aceptar_mas_contenido():
    """El mecanismo genérico solo INFORMA que la ventana venció — la
    decisión de dejar de aceptar contenido es del dominio (acá,
    simulada: si `dentro_de_ventana` es False, el llamador ficticio no
    llama a `actualizar_payload`). Confirma que el Core entrega la
    señal correcta para que esa decisión de dominio sea posible."""
    store = TimedStateStore()
    momento_creacion = datetime.now(timezone.utc) - timedelta(minutes=10)  # hace 10 min, venció (5 min)
    store.registrar("CASO-101", payload={"evidencia": ["foto_inicial.jpg"]}, ahora=momento_creacion)

    assert not store.dentro_de_ventana("CASO-101", _VENTANA_EVIDENCIA_CASO)
    # El payload sigue ahí, intacto (el Core nunca borra nada por su
    # cuenta) — es el dominio quien, al ver la ventana vencida, decide
    # cerrar el caso formalmente en vez de aceptar más evidencia.
    assert store.obtener_payload("CASO-101")["evidencia"] == ["foto_inicial.jpg"]


def test_actualizar_payload_no_crea_una_entrada_nueva_implicitamente():
    store = TimedStateStore()
    exito = store.actualizar_payload("CASO-INEXISTENTE", {"evidencia": ["algo"]})
    assert exito is False
    assert "CASO-INEXISTENTE" not in store


def test_limpiar_borra_la_entrada():
    store = TimedStateStore()
    store.registrar("CASO-102", payload="algo")
    store.limpiar("CASO-102")
    assert "CASO-102" not in store
    assert store.obtener_payload("CASO-102") is None
