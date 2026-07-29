"""Persistent direct-booking payment engine.

The module name is kept for repository compatibility.  The implementation is a
small sqlite-backed direct-booking engine with idempotent payment processing:
the same canonical payload returns the persisted payment result, while a
materially different or non-direct payload is evaluated independently.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DIRECT_CHANNELS = {"direct", "website", "wallet"}


@dataclass(frozen=True)
class PaymentResult:
    """Result persisted by ``DirectBookingPaymentEngine.process_payment``."""

    status: str
    idempotency_status: str
    booking_id: str | None
    charge_id: str | None
    hotel_id: str
    booking_channel: str
    amount_cents: int
    key_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "idempotency_status": self.idempotency_status,
            "booking_id": self.booking_id,
            "charge_id": self.charge_id,
            "hotel_id": self.hotel_id,
            "booking_channel": self.booking_channel,
            "amount_cents": self.amount_cents,
            "key_hash": self.key_hash,
        }


class DirectBookingPaymentEngine:
    """Processes direct-booking payments with a durable sqlite ledger."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def process_payment(self, payload: dict[str, Any]) -> PaymentResult:
        """Persist and return the payment decision for one booking payload."""

        normalized = self._normalize_payload(payload)
        key_hash = self._key_hash(normalized)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cached = conn.execute(
                "SELECT response_json FROM idempotency_ledger WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
            if cached is not None:
                cached_response = json.loads(cached["response_json"])
                return PaymentResult(
                    **cached_response,
                    idempotency_status="cached",
                    key_hash=key_hash,
                )

            result = self._fresh_result(conn, normalized, key_hash)
            response = result.as_dict()
            response.pop("idempotency_status")
            response.pop("key_hash")
            conn.execute(
                """
                INSERT INTO idempotency_ledger (key_hash, request_json, response_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    key_hash,
                    json.dumps(normalized, sort_keys=True, separators=(",", ":")),
                    json.dumps(response, sort_keys=True, separators=(",", ":")),
                    time.time(),
                ),
            )
            conn.commit()
            return result

    def ledger_counts(self) -> dict[str, int]:
        """Return durable row counts used by integration tests and diagnostics."""

        with self._connect() as conn:
            return {
                "idempotency_keys": conn.execute(
                    "SELECT COUNT(*) AS n FROM idempotency_ledger"
                ).fetchone()["n"],
                "bookings": conn.execute(
                    "SELECT COUNT(*) AS n FROM bookings"
                ).fetchone()["n"],
                "charges": conn.execute(
                    "SELECT COUNT(*) AS n FROM payment_charges"
                ).fetchone()["n"],
            }

    def _fresh_result(
        self,
        conn: sqlite3.Connection,
        normalized: dict[str, Any],
        key_hash: str,
    ) -> PaymentResult:
        hotel_id = normalized["hotel_id"]
        channel = normalized["booking_channel"]
        amount_cents = normalized["amount_cents"]

        if channel not in DIRECT_CHANNELS:
            return PaymentResult(
                status="rejected_non_direct_channel",
                idempotency_status="fresh",
                booking_id=None,
                charge_id=None,
                hotel_id=hotel_id,
                booking_channel=channel,
                amount_cents=amount_cents,
                key_hash=key_hash,
            )

        booking_id = self._public_id("bk", key_hash)
        charge_id = self._public_id("ch", key_hash)
        now = time.time()
        conn.execute(
            """
            INSERT INTO bookings (
                booking_id, hotel_id, room_type, guest_email_hash, check_in,
                check_out, booking_channel, amount_cents, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                booking_id,
                hotel_id,
                normalized["room_type"],
                self._email_hash(normalized["guest_email"]),
                normalized["check_in"],
                normalized["check_out"],
                channel,
                amount_cents,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO payment_charges (charge_id, booking_id, amount_cents, currency, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (charge_id, booking_id, amount_cents, normalized["currency"], now),
        )
        return PaymentResult(
            status="confirmed_direct_booking",
            idempotency_status="fresh",
            booking_id=booking_id,
            charge_id=charge_id,
            hotel_id=hotel_id,
            booking_channel=channel,
            amount_cents=amount_cents,
            key_hash=key_hash,
        )

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = {
            "hotel_id",
            "room_type",
            "guest_email",
            "check_in",
            "check_out",
            "amount_cents",
            "currency",
            "booking_channel",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ValueError(f"Missing payment fields: {', '.join(missing)}")

        amount_cents = int(payload["amount_cents"])
        if amount_cents <= 0:
            raise ValueError(f"Invalid amount_cents: {payload['amount_cents']}")

        normalized = {
            "hotel_id": str(payload["hotel_id"]).strip().lower(),
            "room_type": str(payload["room_type"]).strip().upper(),
            "guest_email": str(payload["guest_email"]).strip().lower(),
            "check_in": str(payload["check_in"]).strip(),
            "check_out": str(payload["check_out"]).strip(),
            "amount_cents": amount_cents,
            "currency": str(payload["currency"]).strip().lower(),
            "booking_channel": str(payload["booking_channel"]).strip().lower(),
        }
        if normalized["currency"] != "eur":
            raise ValueError(f"Unsupported currency: {normalized['currency']}")
        if normalized["check_in"] >= normalized["check_out"]:
            raise ValueError("check_in must be before check_out")
        return normalized

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS idempotency_ledger (
                    key_hash TEXT PRIMARY KEY,
                    request_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bookings (
                    booking_id TEXT PRIMARY KEY,
                    hotel_id TEXT NOT NULL,
                    room_type TEXT NOT NULL,
                    guest_email_hash TEXT NOT NULL,
                    check_in TEXT NOT NULL,
                    check_out TEXT NOT NULL,
                    booking_channel TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS payment_charges (
                    charge_id TEXT PRIMARY KEY,
                    booking_id TEXT NOT NULL REFERENCES bookings(booking_id),
                    amount_cents INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _key_hash(normalized_payload: dict[str, Any]) -> str:
        canonical = json.dumps(normalized_payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _public_id(prefix: str, key_hash: str) -> str:
        return f"{prefix}_{key_hash[:24]}"

    @staticmethod
    def _email_hash(email: str) -> str:
        return hashlib.sha256(email.encode("utf-8")).hexdigest()
