"""Cancellation-Policy-Engine [CRUX-MK].

Hotel-spezifische Cancellation-Rules + Refund-Berechnung.

Phase-1: 4 Standard-Policies (free/strict/flex/non-refundable).
Phase-2: Custom-Policies pro Hotel via config.

K_0-Schutz: Refund-Berechnung muss DETERMINISTIC sein
(kein LLM, kein randomness, deterministisch ueberpruefbar).

[CRUX-MK]
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class CancellationPolicyType(str, Enum):
    FREE_24H = "free_24h"  # Free-Cancellation bis 24h vor Check-In
    FREE_48H = "free_48h"
    STRICT_7D = "strict_7d"  # Free bis 7 Tage vorher
    FLEX_50_50 = "flex_50_50"  # 50% Refund jederzeit
    NON_REFUNDABLE = "non_refundable"


@dataclass
class CancellationResult:
    """Resultat der Cancellation-Berechnung."""
    policy_type: CancellationPolicyType
    refund_eur: float
    refund_pct: float
    explanation: str


class CancellationPolicyEngine:
    """Deterministisches Refund-Modell."""

    def compute_refund(
        self,
        policy: CancellationPolicyType,
        total_eur: float,
        check_in_iso: str,
        cancel_iso: Optional[str] = None,
    ) -> CancellationResult:
        """Refund berechnen.

        Args:
            policy: Policy-Typ
            total_eur: Buchungssumme
            check_in_iso: Check-In Datum
            cancel_iso: Cancel-Datum (default: jetzt)
        """
        if total_eur < 0:
            raise ValueError(f"Invalid total: {total_eur}")

        check_in = datetime.fromisoformat(check_in_iso)
        cancel = datetime.fromisoformat(cancel_iso) if cancel_iso else datetime.now()
        hours_until = (check_in - cancel).total_seconds() / 3600

        if policy == CancellationPolicyType.FREE_24H:
            if hours_until >= 24:
                return CancellationResult(policy, total_eur, 1.0, "Free until 24h before")
            return CancellationResult(policy, 0.0, 0.0, "Within 24h-window: no refund")

        if policy == CancellationPolicyType.FREE_48H:
            if hours_until >= 48:
                return CancellationResult(policy, total_eur, 1.0, "Free until 48h before")
            return CancellationResult(policy, 0.0, 0.0, "Within 48h-window: no refund")

        if policy == CancellationPolicyType.STRICT_7D:
            if hours_until >= 24 * 7:
                return CancellationResult(policy, total_eur, 1.0, "Free until 7d before")
            return CancellationResult(policy, 0.0, 0.0, "Within 7d-window: no refund")

        if policy == CancellationPolicyType.FLEX_50_50:
            refund = round(total_eur * 0.5, 2)
            return CancellationResult(policy, refund, 0.5, "Flex 50%-Refund jederzeit")

        if policy == CancellationPolicyType.NON_REFUNDABLE:
            return CancellationResult(policy, 0.0, 0.0, "Non-refundable booking")

        raise ValueError(f"Unknown policy: {policy}")
