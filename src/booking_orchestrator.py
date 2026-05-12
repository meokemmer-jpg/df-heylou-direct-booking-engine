"""Booking-Orchestrator [CRUX-MK].

LaunchAgent-Entry + main() fuer DF-HeyLou-Direct-Booking-Engine.

Pipeline: Health-Check → 1 Demo-Booking (Sandbox) → Audit.

[CRUX-MK]
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BookingOrchestratorResult:
    """End-to-End-Run Result."""
    booking_id: str
    charge_id: Optional[str]
    state: str
    sandbox_mode: bool
    duration_ms: float
    audit_hash: str


class BookingOrchestrator:
    """Main-Orchestrator (Health-Check + Demo-Booking)."""

    def __init__(self, sandbox_mode: Optional[bool] = None):
        from . import direct_booking_engine, stripe_integration, wallet_usp_tracker, audit_logger
        if sandbox_mode is None:
            sandbox_mode = (
                os.environ.get(
                    "DF_HEYLOU_DIRECT_BOOKING_REAL_STRIPE_ENABLED", "false"
                ).lower()
                != "true"
            )
        self.sandbox_mode = sandbox_mode
        self.engine = direct_booking_engine.DirectBookingEngine(sandbox_mode=sandbox_mode)
        self.stripe = stripe_integration.StripeIntegration(sandbox_mode=sandbox_mode)
        self.wallet = wallet_usp_tracker.WalletUSPTracker()
        self.audit = audit_logger.AuditLogger()

    def run_demo_booking(self) -> BookingOrchestratorResult:
        """1 Demo-Booking in Sandbox.

        Phase-1: nur Demo-Flow in Sandbox.
        Phase-2: Production-Flow via Real-PMS + Real-Stripe.
        """
        from .direct_booking_engine import BookingRequest

        t0 = time.time()
        if not self.sandbox_mode:
            raise PermissionError("Demo-Run nur in Sandbox-Mode erlaubt")

        req = BookingRequest(
            hotel_id="HILDESHEIM-PILOT-01",
            room_type="STANDARD-DOUBLE",
            guest_first_name="Demo",
            guest_last_name="Guest",
            guest_email="demo@heylou.example",
            check_in="2026-06-15",
            check_out="2026-06-17",
            total_eur=198.0,
        )

        reserve = self.engine.reserve(req, idempotency_key=f"idem_{req.booking_id}")
        charge_result = self.stripe.create_charge(
            amount_eur=req.total_eur,
            idempotency_key=f"idem_{req.booking_id}",
            booking_id=req.booking_id,
        )

        confirm = self.engine.confirm_with_charge(
            booking_id=req.booking_id,
            stripe_charge_intent={
                "amount": req.total_eur,
                "currency": "eur",
                "charge_id": charge_result.charge_id,
            },
        )

        # Wallet-USP-Tracking
        self.wallet.record_direct_booking(
            hotel_id=req.hotel_id,
            guest_email=req.guest_email,
            amount_eur=req.total_eur,
        )

        # Audit
        audit_hash = self.audit.append({
            "type": "direct_booking_demo",
            "booking": req.to_audit_dict(),
            "charge_id": charge_result.charge_id,
            "sandbox_mode": self.sandbox_mode,
            "state": confirm.state.value,
        })

        return BookingOrchestratorResult(
            booking_id=req.booking_id,
            charge_id=charge_result.charge_id,
            state=confirm.state.value,
            sandbox_mode=self.sandbox_mode,
            duration_ms=(time.time() - t0) * 1000,
            audit_hash=audit_hash,
        )


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO)
    stop_flag = Path("/tmp/df-heylou-direct-booking.stop")
    if stop_flag.exists():
        logger.info("STOP.flag detected")
        return 0
    orch = BookingOrchestrator()
    result = orch.run_demo_booking()
    logger.info(f"Demo-Booking done: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
