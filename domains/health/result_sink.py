"""
Callback al sistema IPS (prompt 007, sección 26). El contrato queda
listo para `POST /activity-results`; el MVP usa `MockActivityResultSink`.

Idempotente por `(activity_id, result)`: reenviar el mismo resultado no
lo duplica en el sink (sección 28).
"""
from __future__ import annotations

import threading
from typing import List, Protocol

from .models import ActivityResult


class ActivityResultSink(Protocol):
    def send_result(self, result: ActivityResult) -> bool: ...


class MockActivityResultSink:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sent: List[ActivityResult] = []
        self._seen_keys: set = set()

    def send_result(self, result: ActivityResult) -> bool:
        clave = (result.activity_id, result.result.value)
        with self._lock:
            if clave in self._seen_keys:
                return True  # idempotente: ya se envió, no se duplica
            self._seen_keys.add(clave)
            self._sent.append(result)
            return True

    def results_for(self, activity_id: str) -> List[ActivityResult]:
        return [r for r in self._sent if r.activity_id == activity_id]
