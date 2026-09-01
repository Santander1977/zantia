"""
Registro de solicitudes iniciadas por el paciente — mismo patrón que
`activity_source.py` (Protocol + Mock), pero para `PatientRequest` en
vez de `Activity`. Componente NUEVO, no modifica `ActivitySource`.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional, Protocol

from .models import PatientRequest


class PatientRequestSource(Protocol):
    def create(self, request: PatientRequest) -> PatientRequest: ...

    def get(self, request_id: str) -> Optional[PatientRequest]: ...

    def update(self, request: PatientRequest) -> PatientRequest: ...


class MockPatientRequestSource:
    def __init__(self) -> None:
        self._requests: Dict[str, PatientRequest] = {}
        self._lock = threading.Lock()

    def create(self, request: PatientRequest) -> PatientRequest:
        with self._lock:
            existente = self._requests.get(request.request_id)
            if existente is not None:
                return existente  # idempotente, igual que MockActivitySource
            self._requests[request.request_id] = request
            return request

    def get(self, request_id: str) -> Optional[PatientRequest]:
        return self._requests.get(request_id)

    def update(self, request: PatientRequest) -> PatientRequest:
        with self._lock:
            self._requests[request.request_id] = request
            return request

    def list_for_patient(self, patient_reference: str) -> List[PatientRequest]:
        return [r for r in self._requests.values() if r.patient_reference == patient_reference]
