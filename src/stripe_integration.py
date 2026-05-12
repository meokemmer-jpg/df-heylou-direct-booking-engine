"""Stripe-Integration [CRUX-MK].

Reuse _df_common.stripe_hmac_verifier (Welle-35-PLUS) fuer Webhook-Verification.
Phase-1: Mock-Charge-Creation. Phase-2: Real-Stripe-API.

K_0-Schutz:
- Sandbox-Default + Test-Keys only
- HMAC-SHA256-Verification gegen Replay
- Constant-Time-Comparison (timing-attack-resistant)
- Idempotency-Key Pflicht

[CRUX-MK]
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StripeChargeResult:
    """Result einer Stripe-Charge."""
    charge_id: str
    amount_eur: float
    currency: str
    status: str  # "succeeded" | "pending" | "failed"
    timestamp: float
    sandbox: bool
    provenance: dict


class StripeIntegration:
    """Wrapper um Stripe-Charge + Webhook-Verification.

    Phase-1: Mock-Mode (Test-Keys).
    Phase-2: Live-Mode (Real-Stripe-API + PHRONESIS_TICKET).
    """

    def __init__(self, sandbox_mode: Optional[bool] = None):
        if sandbox_mode is None:
            sandbox_mode = (
                os.environ.get(
                    "DF_HEYLOU_DIRECT_BOOKING_REAL_STRIPE_ENABLED", "false"
                ).lower()
                != "true"
            )
        self.sandbox_mode = sandbox_mode
        # K_0-Schutz: Keys nur aus ENV
        self.api_key = os.environ.get("STRIPE_API_KEY", "sk_test_skeleton")
        self.webhook_secret = os.environ.get(
            "STRIPE_WEBHOOK_SECRET", "whsec_test_skeleton"
        )

    def create_charge(
        self,
        amount_eur: float,
        idempotency_key: str,
        booking_id: str,
        currency: str = "eur",
    ) -> StripeChargeResult:
        """Stripe-Charge erstellen.

        Phase-1 Mock: simulierte Charge.
        Phase-2: stripe.Charge.create(amount=..., currency='eur', ...)
        """
        if amount_eur <= 0:
            raise ValueError(f"Invalid amount: {amount_eur}")
        if currency.lower() not in ("eur", "usd"):
            raise ValueError(f"Unsupported currency: {currency}")

        if not self.sandbox_mode:
            if not os.environ.get("PHRONESIS_TICKET"):
                raise PermissionError(
                    "Real-Stripe-Charge requires PHRONESIS_TICKET (K_0-Schutz)"
                )
            # Phase-2: Real-Stripe-API
            raise NotImplementedError("Real-Stripe-API pending Phase-2")

        # Mock-Charge
        charge_id = f"ch_test_{uuid.uuid4().hex[:24]}"
        return StripeChargeResult(
            charge_id=charge_id,
            amount_eur=amount_eur,
            currency=currency,
            status="succeeded",
            timestamp=time.time(),
            sandbox=True,
            provenance={
                "engine": "StripeIntegration-Mock",
                "version": "0.1.0-SKELETON",
                "idempotency_key": idempotency_key,
                "booking_id": booking_id,
                "api_key_prefix": self.api_key[:7],
            },
        )

    def verify_webhook(
        self,
        payload: bytes,
        signature_header: str,
    ) -> dict:
        """Webhook-Verification via _df_common.stripe_hmac_verifier.

        Phase-1: Inline-Verification (Skeleton).
        Phase-2: import from _df_common.stripe_hmac_verifier.
        """
        # Phase-2: from _df_common.stripe_hmac_verifier import verify_stripe_webhook
        # Phase-1 Inline (kompatibles Skeleton):
        import hmac as _hmac

        if not signature_header:
            return {"valid": False, "error": "missing_signature"}

        # Parse Stripe-Signature-Header: t=...,v1=...
        parts = {}
        for segment in signature_header.split(","):
            if "=" in segment:
                k, v = segment.strip().split("=", 1)
                parts[k] = v

        t = parts.get("t")
        sig = parts.get("v1")
        if not t or not sig:
            return {"valid": False, "error": "malformed_signature"}

        # Replay-Defense: Timestamp-Age < 300s
        try:
            age = time.time() - int(t)
        except (ValueError, TypeError):
            return {"valid": False, "error": "invalid_timestamp"}
        if age > 300:
            return {"valid": False, "error": "timestamp_too_old", "age_s": age}

        # HMAC-Compute
        expected = _hmac.new(
            self.webhook_secret.encode(),
            f"{t}.{payload.decode()}".encode(),
            hashlib.sha256,
        ).hexdigest()

        # Constant-Time-Compare
        valid = _hmac.compare_digest(expected, sig)
        return {
            "valid": valid,
            "timestamp": int(t),
            "age_s": age,
        }
