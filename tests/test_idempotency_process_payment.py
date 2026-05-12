"""W41-A Idempotency-Integration-Tests fuer direct-booking-engine [CRUX-MK].

K_0-CRITICAL: process_payment ist confirm_with_charge (Stripe-Charge).
Test-Pflicht: Booking-Race + Payment-Ledger-Schutz (Codex-Top-Patch-1).
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _df_common.idempotency_keys import IdempotencyStore  # noqa: E402
from _df_common.idempotency_adapter_wrapper import (  # noqa: E402
    idempotency_check,
    store_cached_response,
)
from src.direct_booking_engine import (  # noqa: E402
    BookingRequest, DirectBookingEngine,
)


@pytest.fixture
def store(tmp_path):
    return IdempotencyStore(db_path=tmp_path / "idem.db")


@pytest.fixture
def engine():
    return DirectBookingEngine(sandbox_mode=True)


def _payment_with_idempotency(engine, store, response_db, payload, charge_intent):
    """confirm_with_charge mit Idempotency-Check (Doppel-Charge-Schutz)."""
    result = idempotency_check(
        tenant_id=payload["hotel_id"],
        adapter_name="heylou-direct-booking",
        operation="process_payment",
        payload=payload,
        store=store,
        response_db=response_db,
        ttl_seconds=86400,
    )
    if result.status == "duplicate" and result.cached_response is not None:
        return result.cached_response, "cached"
    # Real-Workflow: reserve + confirm_with_charge
    req = BookingRequest(
        hotel_id=payload["hotel_id"],
        room_type=payload["room_type"],
        guest_first_name=payload["guest_first_name"],
        guest_last_name=payload["guest_last_name"],
        guest_email=payload["guest_email"],
        check_in=payload["check_in"],
        check_out=payload["check_out"],
        total_eur=payload["total_eur"],
    )
    conf = engine.reserve(req)
    confirmed = engine.confirm_with_charge(conf.booking_id, charge_intent)
    response = {
        "booking_id": confirmed.booking_id,
        "charge_id": confirmed.charge_id,
        "state": confirmed.state.value,
    }
    store_cached_response(response_db, result.key_hash, response)
    return response, "fresh"


def test_duplicate_call_returns_cached(engine, store, tmp_path):
    """1. payment: fresh + charge_id. 2. gleicher Payload: cached."""
    payload = {
        "hotel_id": "hildesheim", "room_type": "STANDARD-DOUBLE",
        "guest_first_name": "Max", "guest_last_name": "Mustermann",
        "guest_email": "max@kemmer.de",
        "check_in": "2026-06-01", "check_out": "2026-06-02",
        "total_eur": 99.0,
    }
    intent = {"amount": 9900, "currency": "eur"}
    response_db = tmp_path / "resp.db"

    r1, s1 = _payment_with_idempotency(engine, store, response_db, payload, intent)
    r2, s2 = _payment_with_idempotency(engine, store, response_db, payload, intent)

    assert s1 == "fresh"
    assert s2 == "cached"
    assert r1["charge_id"] == r2["charge_id"]
    assert r1["charge_id"].startswith("ch_test_")


def test_different_keys_independent(engine, store, tmp_path):
    response_db = tmp_path / "resp.db"
    p_a = {
        "hotel_id": "hildesheim", "room_type": "STANDARD-DOUBLE",
        "guest_first_name": "A", "guest_last_name": "X",
        "guest_email": "a@x.de",
        "check_in": "2026-06-01", "check_out": "2026-06-02",
        "total_eur": 99.0,
    }
    p_b = {**p_a, "hotel_id": "munich", "guest_email": "b@x.de"}
    intent = {"amount": 9900, "currency": "eur"}
    r_a, s_a = _payment_with_idempotency(engine, store, response_db, p_a, intent)
    r_b, s_b = _payment_with_idempotency(engine, store, response_db, p_b, intent)
    assert s_a == s_b == "fresh"
    assert r_a["charge_id"] != r_b["charge_id"]


def test_expired_key_recomputes(engine, store, tmp_path):
    import time as _t
    payload = {
        "hotel_id": "munich", "room_type": "PREMIUM-SUITE",
        "guest_first_name": "X", "guest_last_name": "Y",
        "guest_email": "x@y.de",
        "check_in": "2026-07-01", "check_out": "2026-07-02",
        "total_eur": 189.0,
    }
    res = idempotency_check(
        tenant_id=payload["hotel_id"], adapter_name="heylou-direct-booking",
        operation="process_payment", payload=payload, ttl_seconds=1, store=store,
    )
    assert res.status == "fresh"
    _t.sleep(1.5)
    res2 = idempotency_check(
        tenant_id=payload["hotel_id"], adapter_name="heylou-direct-booking",
        operation="process_payment", payload=payload, ttl_seconds=1, store=store,
    )
    assert res2.status == "fresh"


def test_concurrent_call_safe(engine, store, tmp_path):
    """K_0-CRITICAL: 50 parallele payment-Calls -> nur 1 echter Charge."""
    payload = {
        "hotel_id": "hildesheim", "room_type": "STANDARD-DOUBLE",
        "guest_first_name": "Concurrent", "guest_last_name": "Test",
        "guest_email": "concurrent@x.de",
        "check_in": "2026-08-01", "check_out": "2026-08-03",
        "total_eur": 198.0,
    }
    statuses: list[str] = []
    lock = threading.Lock()

    def worker():
        r = idempotency_check(
            tenant_id=payload["hotel_id"], adapter_name="heylou-direct-booking",
            operation="process_payment", payload=payload, store=store,
        )
        with lock:
            statuses.append(r.status)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses.count("fresh") == 1, "K_0-VIOLATION: Mehrfach-Charge moeglich"
    assert statuses.count("duplicate") == 49
