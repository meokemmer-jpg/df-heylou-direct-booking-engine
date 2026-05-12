"""Direct-Booking-Engine [CRUX-MK].

K_0-CRITICAL Pipeline:
Search → Reserve (Hold) → Confirm → Stripe-Charge → Audit.

Anti-OTA-Strategie: 0% Kommission vs 12-20% bei Booking/Expedia.

Pflicht-Schutz:
- Sandbox-Default (DF_HEYLOU_DIRECT_BOOKING_REAL_STRIPE_ENABLED=false)
- Idempotency-Key pro Booking (Doppel-Charge-Schutz)
- Reserve-Hold-TTL (default 15 Min)
- Cancellation-Policy-Pre-Check

Lambda-Honesty-Caveat:
- Phase-1 nutzt Stripe-Mock (kein echter PMS-Block, kein echter Charge)
- Phase-2: Real-Stripe + Real-PMS-Integration via Welle-36 PMS-Adapter

[CRUX-MK]
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class BookingState(str, Enum):
    """Booking-State-Machine."""
    SEARCHED = "searched"
    RESERVED = "reserved"  # Hold-only, no charge
    CONFIRMED = "confirmed"  # Charged
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass
class BookingRequest:
    """Booking-Request Input (PII-redacted bei Logging)."""
    hotel_id: str
    room_type: str
    guest_first_name: str
    guest_last_name: str
    guest_email: str
    check_in: str  # ISO YYYY-MM-DD
    check_out: str
    total_eur: float
    booking_id: str = field(default_factory=lambda: f"BK-{uuid.uuid4().hex[:12]}")

    def to_audit_dict(self) -> dict:
        """PII-redacted Dict fuer Audit (DSGVO)."""
        return {
            "booking_id": self.booking_id,
            "hotel_id": self.hotel_id,
            "room_type": self.room_type,
            "check_in": self.check_in,
            "check_out": self.check_out,
            "total_eur": self.total_eur,
            "guest_email_hash": hashlib.sha256(self.guest_email.encode()).hexdigest()[:16],
            "guest_name_hash": hashlib.sha256(
                f"{self.guest_first_name}{self.guest_last_name}".encode()
            ).hexdigest()[:16],
        }


@dataclass
class BookingConfirmation:
    """Booking-Confirmation Output."""
    booking_id: str
    state: BookingState
    charge_id: Optional[str] = None
    reserve_expires_ts: Optional[float] = None
    cancellation_policy_id: Optional[str] = None
    provenance: dict = field(default_factory=dict)


class DirectBookingEngine:
    """Direct-Booking-Pipeline.

    Sandbox-Mode nutzt Stripe-Test-Mocks. Real-Mode pending PHRONESIS_TICKET.
    """

    RESERVE_TTL_S = 15 * 60  # 15 Min

    def __init__(self, sandbox_mode: Optional[bool] = None):
        if sandbox_mode is None:
            sandbox_mode = (
                os.environ.get(
                    "DF_HEYLOU_DIRECT_BOOKING_REAL_STRIPE_ENABLED", "false"
                ).lower()
                != "true"
            )
        self.sandbox_mode = sandbox_mode
        self._bookings: dict[str, BookingConfirmation] = {}
        self._idempotency_keys: set[str] = set()

    def _check_real_mode_phronesis(self) -> None:
        """K_0-Schutz: Real-Mode erfordert PHRONESIS_TICKET."""
        if not self.sandbox_mode and not os.environ.get("PHRONESIS_TICKET"):
            raise PermissionError(
                "Real-Stripe-Mode requires PHRONESIS_TICKET. "
                "K_0-Pflicht-Phronesis Martin: Stripe-Echtgeld-Charge."
            )

    def search_availability(
        self,
        hotel_id: str,
        check_in: str,
        check_out: str,
    ) -> list[dict]:
        """Phase-1 Mock: liefert 2 verfuegbare Zimmertypen.

        Phase-2: Integration mit Welle-36 PMS-Adapter (real availability).
        """
        # Sandbox-Mock
        return [
            {
                "hotel_id": hotel_id,
                "room_type": "STANDARD-DOUBLE",
                "rate_eur": 99.0,
                "available": True,
            },
            {
                "hotel_id": hotel_id,
                "room_type": "PREMIUM-SUITE",
                "rate_eur": 189.0,
                "available": True,
            },
        ]

    def reserve(self, req: BookingRequest, idempotency_key: Optional[str] = None) -> BookingConfirmation:
        """Reserve-Hold (kein Charge).

        Idempotency-Key verhindert Doppel-Reservation.
        """
        self._check_real_mode_phronesis()

        if idempotency_key:
            if idempotency_key in self._idempotency_keys:
                # Idempotent: return previous booking
                for bk in self._bookings.values():
                    if bk.provenance.get("idempotency_key") == idempotency_key:
                        return bk
            self._idempotency_keys.add(idempotency_key)

        if req.total_eur <= 0:
            raise ValueError(f"Invalid total: {req.total_eur}")

        conf = BookingConfirmation(
            booking_id=req.booking_id,
            state=BookingState.RESERVED,
            reserve_expires_ts=time.time() + self.RESERVE_TTL_S,
            provenance={
                "engine": "DirectBookingEngine",
                "version": "0.1.0-SKELETON",
                "sandbox_mode": self.sandbox_mode,
                "idempotency_key": idempotency_key,
                "timestamp": time.time(),
            },
        )
        self._bookings[req.booking_id] = conf
        return conf

    def confirm_with_charge(
        self,
        booking_id: str,
        stripe_charge_intent: dict,
    ) -> BookingConfirmation:
        """Confirm + Stripe-Charge.

        Phase-1 Mock: Simuliert Charge mit mock_charge_id.
        Phase-2: Real-Stripe-API-Call via _df_common.stripe_hmac_verifier.
        """
        self._check_real_mode_phronesis()

        if booking_id not in self._bookings:
            raise KeyError(f"Booking not found: {booking_id}")
        conf = self._bookings[booking_id]

        if conf.state != BookingState.RESERVED:
            raise ValueError(f"Cannot confirm: state={conf.state}")
        if conf.reserve_expires_ts and time.time() > conf.reserve_expires_ts:
            conf.state = BookingState.EXPIRED
            return conf

        # Phase-1 Mock-Charge
        if self.sandbox_mode:
            charge_id = f"ch_test_{uuid.uuid4().hex[:24]}"
        else:
            # Phase-2: Real-Stripe-Charge via _df_common.stripe_hmac_verifier
            # from _df_common.stripe_hmac_verifier import create_charge
            # charge_id = create_charge(stripe_charge_intent)
            raise NotImplementedError(
                "Real-Stripe-Charge pending Phase-2 + PHRONESIS_TICKET"
            )

        conf.state = BookingState.CONFIRMED
        conf.charge_id = charge_id
        conf.provenance["confirm_ts"] = time.time()
        conf.provenance["stripe_intent_hash"] = hashlib.sha256(
            str(sorted(stripe_charge_intent.items())).encode()
        ).hexdigest()[:16]
        return conf

    def cancel(self, booking_id: str, reason: str = "") -> BookingConfirmation:
        """Cancel-Booking (Refund Phase-2)."""
        if booking_id not in self._bookings:
            raise KeyError(f"Booking not found: {booking_id}")
        conf = self._bookings[booking_id]
        conf.state = BookingState.CANCELLED
        conf.provenance["cancel_reason"] = reason
        conf.provenance["cancel_ts"] = time.time()
        return conf

    def get_booking(self, booking_id: str) -> Optional[BookingConfirmation]:
        return self._bookings.get(booking_id)
