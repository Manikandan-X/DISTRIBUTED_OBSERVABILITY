from datetime import datetime

import pytest

from app.schemas.log import LogPayload
from app.services.log_normalization import dedup_hash, message_fingerprint, normalize_severity


@pytest.mark.parametrize("raw,expected", [
    ("info", "INFO"), ("warn", "WARNING"), ("Warning", "WARNING"), ("err", "ERROR"),
    ("fatal", "CRITICAL"), ("CRITICAL", "CRITICAL"), ("debug", "INFO"),
])
def test_severity_normalisation(raw, expected):
    assert normalize_severity(raw) == expected


def test_unknown_severity_rejected():
    with pytest.raises(ValueError):
        normalize_severity("loud")


def test_unstructured_message_defaults():
    payload = LogPayload.model_validate({"message": "  something happened  "})
    assert payload.severity == "INFO" and payload.message == "something happened" and payload.span_id is None


def test_empty_message_rejected():
    with pytest.raises(ValueError):
        LogPayload.model_validate({"message": "   "})


def test_fingerprint_groups_same_kind_of_message():
    a = message_fingerprint("Order 17 failed after 3.2s for 'alice'")
    b = message_fingerprint("Order 18 failed after 5s for 'bob'")
    assert a == b
    assert a != message_fingerprint("Payment provider rejected the transaction")


def test_dedup_hash_ignores_event_id_but_not_content():
    ts = datetime(2026, 1, 1)
    base = dedup_hash("svc", "t1", "s1", "ERROR", "boom", ts)
    assert base == dedup_hash("svc", "t1", "s1", "ERROR", "boom", ts)
    assert base != dedup_hash("svc", "t1", "s1", "ERROR", "boom!", ts)
