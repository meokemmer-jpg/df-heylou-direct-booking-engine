"""Tests fuer DF-HeyLou-Direct-Booking-Engine [CRUX-MK].

>=22 Tests Pflicht (K_0-CRITICAL).
Decken: Engine, Stripe-Integration, Cancellation-Policy, Wallet-USP,
Audit-Chain, Orchestrator, K_0-Schutz, Idempotency, DSGVO-PII-Redaction.

[CRUX-MK]
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.direct_booking_engine import (
    DirectBookingEngine,
    BookingRequest,
    BookingState,
)
from src.stripe_integration import StripeIntegration
from src.cancellation_policy_engine import (
    CancellationPolicyEngine,
    CancellationPolicyType,
)
from src.wallet_usp_tracker import WalletUSPTracker
from src.audit_logger import AuditLogger
from src.booking_orchestrator import BookingOrchestrator


# ============== Engine Tests ==============

def test_engine_default_sandbox():
    """Test 1: Default-Mode ist Sandbox (K_0-Schutz)."""
    e = DirectBookingEngine()
    assert e.sandbox_mode is True


def test_search_availability_returns_rooms():
    """Test 2: Search liefert verfuegbare Zimmer."""
    e = DirectBookingEngine()
    rooms = e.search_availability("H1", "2026-06-15", "2026-06-17")
    assert len(rooms) >= 1
    assert all(r["available"] for r in rooms)


def test_reserve_creates_hold():
    """Test 3: Reserve setzt State=RESERVED + Expiry."""
    e = DirectBookingEngine()
    req = BookingRequest(
        hotel_id="H1", room_type="DBL",
        guest_first_name="Max", guest_last_name="Mustermann",
        guest_email="max@example.com",
        check_in="2026-06-15", check_out="2026-06-17",
        total_eur=200.0,
    )
    conf = e.reserve(req)
    assert conf.state == BookingState.RESERVED
    assert conf.reserve_expires_ts > time.time()


def test_reserve_idempotency():
    """Test 4: Idempotency-Key verhindert Doppel-Reserve."""
    e = DirectBookingEngine()
    req = BookingRequest(
        hotel_id="H1", room_type="DBL",
        guest_first_name="A", guest_last_name="B", guest_email="x@y.com",
        check_in="2026-06-15", check_out="2026-06-17", total_eur=100.0,
    )
    c1 = e.reserve(req, idempotency_key="key-1")
    c2 = e.reserve(req, idempotency_key="key-1")
    assert c1.booking_id == c2.booking_id


def test_reserve_invalid_total_raises():
    """Test 5: Reserve mit total <= 0 raises."""
    e = DirectBookingEngine()
    req = BookingRequest(
        hotel_id="H1", room_type="DBL",
        guest_first_name="A", guest_last_name="B", guest_email="x@y.com",
        check_in="2026-06-15", check_out="2026-06-17", total_eur=0.0,
    )
    with pytest.raises(ValueError):
        e.reserve(req)


def test_confirm_with_charge_in_sandbox():
    """Test 6: Confirm in Sandbox = Mock-Charge."""
    e = DirectBookingEngine()
    req = BookingRequest(
        hotel_id="H1", room_type="DBL",
        guest_first_name="A", guest_last_name="B", guest_email="x@y.com",
        check_in="2026-06-15", check_out="2026-06-17", total_eur=200.0,
    )
    e.reserve(req)
    conf = e.confirm_with_charge(
        req.booking_id,
        {"amount": 200.0, "currency": "eur"},
    )
    assert conf.state == BookingState.CONFIRMED
    assert conf.charge_id is not None
    assert conf.charge_id.startswith("ch_test_")


def test_confirm_unknown_booking_raises():
    """Test 7: Confirm unknown booking_id raises."""
    e = DirectBookingEngine()
    with pytest.raises(KeyError):
        e.confirm_with_charge("nonexistent", {})


def test_cancel_booking():
    """Test 8: Cancel setzt State=CANCELLED."""
    e = DirectBookingEngine()
    req = BookingRequest(
        hotel_id="H1", room_type="DBL",
        guest_first_name="A", guest_last_name="B", guest_email="x@y.com",
        check_in="2026-06-15", check_out="2026-06-17", total_eur=100.0,
    )
    e.reserve(req)
    cancelled = e.cancel(req.booking_id, reason="user_request")
    assert cancelled.state == BookingState.CANCELLED
    assert cancelled.provenance["cancel_reason"] == "user_request"


def test_booking_request_pii_redaction():
    """Test 9: DSGVO - to_audit_dict hash't PII."""
    req = BookingRequest(
        hotel_id="H1", room_type="DBL",
        guest_first_name="Max", guest_last_name="Mustermann",
        guest_email="max.mustermann@example.com",
        check_in="2026-06-15", check_out="2026-06-17", total_eur=200.0,
    )
    d = req.to_audit_dict()
    assert "max.mustermann@example.com" not in str(d)
    assert "Max" not in str(d)
    assert "Mustermann" not in str(d)
    assert "guest_email_hash" in d
    assert "guest_name_hash" in d


def test_engine_real_mode_requires_phronesis():
    """Test 10: K_0-CRITICAL: Real-Mode ohne PHRONESIS_TICKET → PermissionError."""
    with patch.dict(os.environ, {"DF_HEYLOU_DIRECT_BOOKING_REAL_STRIPE_ENABLED": "true"}, clear=False):
        if "PHRONESIS_TICKET" in os.environ:
            del os.environ["PHRONESIS_TICKET"]
        e = DirectBookingEngine(sandbox_mode=False)
        req = BookingRequest(
            hotel_id="H1", room_type="DBL",
            guest_first_name="A", guest_last_name="B", guest_email="x@y.com",
            check_in="2026-06-15", check_out="2026-06-17", total_eur=100.0,
        )
        with pytest.raises(PermissionError, match="PHRONESIS_TICKET"):
            e.reserve(req)


# ============== Stripe-Integration Tests ==============

def test_stripe_create_charge_sandbox():
    """Test 11: Stripe-Charge in Sandbox = Mock-charge_id."""
    s = StripeIntegration(sandbox_mode=True)
    r = s.create_charge(amount_eur=100.0, idempotency_key="k1", booking_id="b1")
    assert r.charge_id.startswith("ch_test_")
    assert r.status == "succeeded"
    assert r.sandbox is True


def test_stripe_invalid_amount_raises():
    """Test 12: Charge mit amount <= 0 raises."""
    s = StripeIntegration()
    with pytest.raises(ValueError):
        s.create_charge(amount_eur=0.0, idempotency_key="k", booking_id="b")


def test_stripe_unsupported_currency_raises():
    """Test 13: Unsupported currency raises."""
    s = StripeIntegration()
    with pytest.raises(ValueError):
        s.create_charge(amount_eur=100.0, idempotency_key="k", booking_id="b", currency="btc")


def test_stripe_real_mode_requires_phronesis():
    """Test 14: K_0: Real-Stripe ohne PHRONESIS_TICKET raises."""
    with patch.dict(os.environ, {"DF_HEYLOU_DIRECT_BOOKING_REAL_STRIPE_ENABLED": "true"}, clear=False):
        if "PHRONESIS_TICKET" in os.environ:
            del os.environ["PHRONESIS_TICKET"]
        s = StripeIntegration(sandbox_mode=False)
        with pytest.raises(PermissionError):
            s.create_charge(100.0, "k", "b")


def test_stripe_webhook_verify_missing_signature():
    """Test 15: Webhook ohne Signature = invalid."""
    s = StripeIntegration()
    r = s.verify_webhook(b"payload", "")
    assert r["valid"] is False
    assert r["error"] == "missing_signature"


def test_stripe_webhook_verify_malformed():
    """Test 16: Malformed Signature = invalid."""
    s = StripeIntegration()
    r = s.verify_webhook(b"payload", "not_a_valid_format")
    assert r["valid"] is False


def test_stripe_webhook_verify_replay_defense():
    """Test 17: Timestamp > 300s = timestamp_too_old."""
    s = StripeIntegration()
    old_ts = int(time.time()) - 1000
    r = s.verify_webhook(b"p", f"t={old_ts},v1=abc")
    assert r["valid"] is False
    assert r["error"] == "timestamp_too_old"


# ============== Cancellation-Policy Tests ==============

def test_cancel_free_24h_outside_window():
    """Test 18: Free-24h policy: 48h before = full refund."""
    e = CancellationPolicyEngine()
    r = e.compute_refund(
        CancellationPolicyType.FREE_24H,
        total_eur=200.0,
        check_in_iso="2026-06-15T12:00:00",
        cancel_iso="2026-06-13T12:00:00",  # 48h before
    )
    assert r.refund_eur == 200.0


def test_cancel_free_24h_within_window():
    """Test 19: Free-24h innerhalb 24h = no refund."""
    e = CancellationPolicyEngine()
    r = e.compute_refund(
        CancellationPolicyType.FREE_24H,
        total_eur=200.0,
        check_in_iso="2026-06-15T12:00:00",
        cancel_iso="2026-06-15T06:00:00",  # 6h before
    )
    assert r.refund_eur == 0.0


def test_cancel_flex_50_50():
    """Test 20: Flex-50-50 immer 50% refund."""
    e = CancellationPolicyEngine()
    r = e.compute_refund(
        CancellationPolicyType.FLEX_50_50,
        total_eur=200.0,
        check_in_iso="2026-06-15T12:00:00",
        cancel_iso="2026-06-15T11:00:00",  # 1h before
    )
    assert r.refund_eur == 100.0
    assert r.refund_pct == 0.5


def test_cancel_non_refundable():
    """Test 21: Non-refundable = 0 EUR."""
    e = CancellationPolicyEngine()
    r = e.compute_refund(
        CancellationPolicyType.NON_REFUNDABLE,
        total_eur=200.0,
        check_in_iso="2026-06-15T12:00:00",
    )
    assert r.refund_eur == 0.0


# ============== Wallet-USP Tests ==============

def test_wallet_usp_records_booking():
    """Test 22: Wallet-USP record_direct_booking inkrementiert counter."""
    w = WalletUSPTracker()
    m = w.record_direct_booking("H1", "guest1@example.com", 200.0)
    assert m.total_direct_bookings == 1
    assert m.total_direct_revenue_eur == 200.0
    assert m.avoided_ota_commission_eur == 200.0 * 0.18


def test_wallet_usp_repeat_guest_detection():
    """Test 23: Wallet-USP erkennt repeat-guest via hash."""
    w = WalletUSPTracker()
    w.record_direct_booking("H1", "g@example.com", 100.0)
    m = w.record_direct_booking("H1", "g@example.com", 150.0)
    assert m.total_direct_bookings == 2
    assert m.repeat_direct_bookings == 1


def test_wallet_usp_pii_redaction():
    """Test 24: DSGVO - Guest-Email wird gehashed (not stored)."""
    w = WalletUSPTracker()
    w.record_direct_booking("H1", "very.private@example.com", 100.0)
    m = w.get_metric("H1")
    for guest_id in m.unique_guests:
        assert "very.private" not in guest_id
        assert "@" not in guest_id


# ============== Audit + Orchestrator Tests ==============

def test_audit_chain_in_direct_booking(tmp_path):
    """Test 25: Audit-Chain verifiziert."""
    a = AuditLogger(audit_path=tmp_path / "a.jsonl", secret="s")
    a.append({"e": "1"})
    a.append({"e": "2"})
    result = a.verify_chain()
    assert result["valid"] is True
    assert result["entries_verified"] == 2


def test_orchestrator_demo_run():
    """Test 26: Demo-Run end-to-end success."""
    o = BookingOrchestrator(sandbox_mode=True)
    r = o.run_demo_booking()
    assert r.state == "confirmed"
    assert r.charge_id is not None
    assert r.sandbox_mode is True
