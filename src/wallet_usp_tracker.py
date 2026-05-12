"""Wallet-USP-Tracker [CRUX-MK].

Per Martin-Direktive Welle-34 Item-5: Wallet-USP Stripe-Pattern.

Trackt Wallet-USP-Metriken pro Hotel + Guest:
- Direct-Booking-Anteil (vs OTA)
- Wallet-Bound-Wert (Pre-Paid + Future-Charges)
- Repeat-Direct-Booking-Rate

Phase-1: Lokale Metriken-Aggregation.
Phase-2: Integration mit Loyalty-Engine + Dashboard.

[CRUX-MK]
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field


@dataclass
class WalletUSPMetric:
    """Per-Hotel Wallet-USP-Metric."""
    hotel_id: str
    total_direct_bookings: int = 0
    total_direct_revenue_eur: float = 0.0
    avoided_ota_commission_eur: float = 0.0  # Geschaetzte 18% von total
    repeat_direct_bookings: int = 0
    unique_guests: set[str] = field(default_factory=set)
    last_update_ts: float = field(default_factory=time.time)

    @property
    def avg_booking_value_eur(self) -> float:
        if self.total_direct_bookings == 0:
            return 0.0
        return self.total_direct_revenue_eur / self.total_direct_bookings

    @property
    def repeat_rate_pct(self) -> float:
        if self.total_direct_bookings == 0:
            return 0.0
        return (self.repeat_direct_bookings / self.total_direct_bookings) * 100


class WalletUSPTracker:
    """Tracker fuer Wallet-USP-Metriken."""

    OTA_COMMISSION_PCT = 0.18  # 18% Booking.com Standard

    def __init__(self):
        self._metrics: dict[str, WalletUSPMetric] = {}

    def record_direct_booking(
        self,
        hotel_id: str,
        guest_email: str,
        amount_eur: float,
    ) -> WalletUSPMetric:
        """Direct-Booking erfassen.

        Args:
            guest_email: wird gehashed (DSGVO)
        """
        if amount_eur <= 0:
            raise ValueError(f"Invalid amount: {amount_eur}")

        guest_hash = hashlib.sha256(guest_email.encode()).hexdigest()[:16]

        m = self._metrics.get(hotel_id) or WalletUSPMetric(hotel_id=hotel_id)
        is_repeat = guest_hash in m.unique_guests
        if is_repeat:
            m.repeat_direct_bookings += 1
        m.unique_guests.add(guest_hash)
        m.total_direct_bookings += 1
        m.total_direct_revenue_eur += amount_eur
        m.avoided_ota_commission_eur += amount_eur * self.OTA_COMMISSION_PCT
        m.last_update_ts = time.time()

        self._metrics[hotel_id] = m
        return m

    def get_metric(self, hotel_id: str) -> WalletUSPMetric:
        return self._metrics.get(hotel_id) or WalletUSPMetric(hotel_id=hotel_id)

    def summary(self) -> dict:
        """Aggregierte Summary ueber alle Hotels."""
        total_bookings = sum(m.total_direct_bookings for m in self._metrics.values())
        total_revenue = sum(m.total_direct_revenue_eur for m in self._metrics.values())
        total_saved = sum(m.avoided_ota_commission_eur for m in self._metrics.values())
        return {
            "n_hotels": len(self._metrics),
            "total_direct_bookings": total_bookings,
            "total_direct_revenue_eur": round(total_revenue, 2),
            "total_avoided_ota_commission_eur": round(total_saved, 2),
            "ota_commission_pct": self.OTA_COMMISSION_PCT,
        }
