"""Activity creation, validation, lifecycle, acceptance (sección 36)."""
import pytest
from pydantic import ValidationError

from domains.health import Activity, ActivityStatus, ManagementStatus, MockActivitySource, accept_activity


def test_activity_creation(activity_factory):
    source = MockActivitySource()
    activity = source.create(activity_factory("ACT-100"))
    assert activity.activity_id == "ACT-100"
    assert activity.status == ActivityStatus.PENDING
    assert activity.management_status == ManagementStatus.NOT_CONTACTED


def test_activity_creation_is_idempotent(activity_factory):
    source = MockActivitySource()
    a1 = source.create(activity_factory("ACT-101", objective="primero"))
    a2 = source.create(activity_factory("ACT-101", objective="segundo"))
    assert a1.objective == a2.objective == "primero"  # no se sobreescribe


def test_activity_validation_requires_mandatory_fields():
    with pytest.raises(ValidationError):
        Activity(activity_id="ACT-102")  # faltan campos obligatorios


def test_activity_lifecycle_transitions(context):
    assert context.activity.status == ActivityStatus.PENDING
    accept_activity(context)
    assert context.activity.status == ActivityStatus.IN_PROGRESS


def test_activity_acceptance_persists_via_source(context, services):
    accept_activity(context)
    recuperada = services["source"].get(context.activity.activity_id)
    assert recuperada.status == ActivityStatus.IN_PROGRESS
