# df-heylou-direct-booking-engine — Output [CRUX-MK]
*Autonom aktiviert 2026-06-05T09:51:33.412982+00:00 | ollama-local/qwen2.5:14b-instruct*

# Dark-Factory 'df-heylou-direct-booking-engine' Dokumentation [CRUX-MK]

## Mission

Die **DF-HeyLou-Direct-Booking-Engine** zielt darauf ab, eine Direktbuchung
Direktbuchungs-Pipeline zu implementieren, um den 12%-20% OTA-Kommissionen 
entgegenzuwirken und somit die Gewinnspanne der Hotels zu erhöhen. Diese In
Initiative ist Teil des **Profit-Layers** in der Welle-40-Mosaikstrategie.

## Systemarchitektur

Die Booking-Pipeline ist modular aufgebaut:

```
src/
├── direct_booking_engine.py     # Durchsuche→Buchen→Bestätigen→Belasten
├── stripe_integration.py         # Verwendung von _df_common.stripe_hmac_v
_df_common.stripe_hmac_verifier für Sicherheit
├── cancellation_policy_engine.py # Anpassung von Stornierungsrichtlinien a
an Hotelbedingungen
├── wallet_usp_tracker.py         # Verfolgung der Wallet-USP gemäß Martin-
Martin-Direktive W34
├── booking_orchestrator.py       # Eintrittspunkt für LaunchAgent
└── audit_logger.py               # Protokollierung aller Transaktionen und
und Sicherheitsrelevante Ereignisse
```

## Kritische Schutzmaßnahmen

- **Real-Stripe-Schutz**: Standardmäßig deaktiviert (`DF_HEYLOU_DIRECT_BOOK
(`DF_HEYLOU_DIRECT_BOOKING_REAL_STRIPE_ENABLED=false`).
- **PHRONESIS-Ticket Erfordernis**: Bei Real-Chargen muss ein gültiges PHRO
PHRONESIS-Ticket (`PT-...`) vorliegen.
- **Sandbox-Modus**: Im Testmodus werden Stripe-Test-Schlüssel und Mock-Bet
Mock-Beträge verwendet, um keine echten Transaktionen auszuführen.
- **HMAC-Verifizierung**: Sicherheitsüberprüfungen durch `_df_common.stripe
`_df_common.stripe_hmac_verifier` zur Erkennung von Fälschungen.
- **Replay-Sicherheit**: Eine Toleranzzeit von 300 Sekunden um Replay-Angri
Replay-Angriffe zu verhindern. Konstantzeitenvergleiche werden verwendet, u
um vor laufender Zeitangriffen geschützt zu sein.

## rho-Gewinn

Mit einem Pilotprojekt in Hildesheim für ein einzelnes Hotel kann der erwar
erwartete Jahresgewinn durch die Entkommissionierung bei 20.000-40.000 EUR/
EUR/J liegen. Bei einer Skalierung auf fünf Hotels steigt dieser Wert auf 2
200.000-400.000 EUR/J im dritten Jahr.

## Phronesis-Pflichten

1. **Stripe-API-Schlüssel**: Bereitstellung der notwendigen Schlüssel für d
die Real-Datenmodi.
2. **Stornierungsrichtlinien**: Die Hotels müssen spezifische Stornierungsb
Stornierungsbedingungen genehmigen, um eine flexiblere Buchung zu gewährlei
gewährleisten.
3. **DSGVO-Konformität**: Gewährleistung der Datenschutz-Grundverordnung (D
(DSGVO) für die gesamte Prozesskette.

---

Diese Dokumentation stellt das wesentliche Grundgerüst des **df-heylou-dire
**df-heylou-direct-booking-engine** bereit und unterstützt eine zügige Umse
Umsetzung dieses kritischen Projekts.