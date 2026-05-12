# DF-HeyLou-Direct-Booking-Engine [CRUX-MK]

**Welle-40 Foundation-DF: Profit-Layer #2 (K_0-CRITICAL)**

Anti-OTA-Kommission via Direct-Booking-Pipeline (0% vs 12-20%).

## Status
- Version: 0.1.0-SKELETON
- Phase: PRE-PRODUCTION-CONDITIONAL
- **K_0-Touch: TRUE (Stripe-Echtgeld-Charge)**

## Architektur

```
src/
├── direct_booking_engine.py     # Search→Reserve→Confirm→Charge
├── stripe_integration.py         # Reuse _df_common.stripe_hmac_verifier
├── cancellation_policy_engine.py # Hotel-spezifische Cancellation
├── wallet_usp_tracker.py         # Wallet-USP per Martin-Direktive W34
├── booking_orchestrator.py       # LaunchAgent-Entry
└── audit_logger.py
```

## KRITISCH: Real-Stripe-Schutz

- `DF_HEYLOU_DIRECT_BOOKING_REAL_STRIPE_ENABLED=false` Default
- `PHRONESIS_TICKET=PT-...` Pflicht für Real-Charge
- Sandbox-Mode nutzt Stripe-Test-Keys + Mock-Charges
- HMAC-Verification via `_df_common.stripe_hmac_verifier`
- Replay-Defense: 300s Timestamp-Tolerance
- Constant-Time-Comparison

## rho-Gain

Year-1 (Hildesheim-Pilot 1 Hotel): +20-40k EUR/J vermiedene OTA-Kommission.
Year-3 5-Hotel-Skaling: +200-400k EUR/J.

## Phronesis-Pflicht Martin

- Stripe-API-Keys (Real-Mode)
- Cancellation-Policy-Approval pro Hotel
- DSGVO-Konformitaet Gast-Daten

[CRUX-MK]
