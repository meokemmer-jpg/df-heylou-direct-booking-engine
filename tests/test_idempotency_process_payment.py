"""Integration proof for df-heylou-direct-booking-engine payment idempotency."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.wallet_usp_tracker import DirectBookingPaymentEngine  # noqa: E402


@pytest.fixture
def engine(tmp_path):
    return DirectBookingPaymentEngine(tmp_path / "direct_booking.sqlite3")


def _direct_payload() -> dict:
    return {
        "hotel_id": "Hildesheim",
        "room_type": "standard-double",
        "guest_email": "max@kemmer.de",
        "check_in": "2026-08-01",
        "check_out": "2026-08-03",
        "amount_cents": 19800,
        "currency": "EUR",
        "booking_channel": "direct",
    }


def test_process_payment_is_idempotent_but_discriminates_opposite_channel(engine):
    direct_payload = _direct_payload()
    first = engine.process_payment(direct_payload)
    replay = engine.process_payment(dict(direct_payload))

    opposite_payload = {
        **direct_payload,
        "guest_email": "ota-guest@example.com",
        "booking_channel": "ota",
    }
    opposite = engine.process_payment(opposite_payload)

    assert first.idempotency_status == "fresh"
    assert replay.idempotency_status == "cached"
    assert replay.status == first.status
    assert replay.booking_id == first.booking_id
    assert replay.charge_id == first.charge_id

    assert opposite.idempotency_status == "fresh"
    assert opposite.key_hash != first.key_hash
    assert opposite.status != first.status
    assert opposite.booking_id != first.booking_id
    assert opposite.charge_id != first.charge_id
    assert opposite.charge_id is None

    assert engine.ledger_counts() == {
        "idempotency_keys": 2,
        "bookings": 1,
        "charges": 1,
    }


def test_process_payment_persists_cached_result_across_engine_instances(tmp_path):
    db_path = tmp_path / "direct_booking.sqlite3"
    payload = _direct_payload()

    first_engine = DirectBookingPaymentEngine(db_path)
    first = first_engine.process_payment(payload)

    second_engine = DirectBookingPaymentEngine(db_path)
    replay = second_engine.process_payment(payload)

    assert replay.idempotency_status == "cached"
    assert replay.as_dict() | {"idempotency_status": "fresh"} == first.as_dict()

    with sqlite3.connect(db_path) as conn:
        persisted_charges = conn.execute(
            "SELECT charge_id, amount_cents FROM payment_charges"
        ).fetchall()

    assert persisted_charges == [(first.charge_id, payload["amount_cents"])]
