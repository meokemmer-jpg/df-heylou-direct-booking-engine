#!/bin/bash
# DF-HeyLou-Direct-Booking-Engine Runner [CRUX-MK] K_0-CRITICAL
set -euo pipefail
LOCK_DIR="/tmp/df-heylou-direct-booking.lock"
LOCK_AGE_LIMIT_S=21600
if [ -d "$LOCK_DIR" ]; then
  LOCK_AGE_S=$(( $(date +%s) - $(stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0) ))
  if [ "$LOCK_AGE_S" -gt "$LOCK_AGE_LIMIT_S" ]; then
    rm -rf "$LOCK_DIR"
  else
    echo "K16-VETO: Lock active (age=$LOCK_AGE_S s)"
    exit 3
  fi
fi
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "K16-VETO: Lock-Race lost"
  exit 3
fi
echo "$$" > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT INT TERM
STOP_FLAG="/tmp/df-heylou-direct-booking.stop"
if [ -f "$STOP_FLAG" ]; then
  echo "STOP.flag detected"
  exit 0
fi
cd "$(dirname "$0")/.."
python3 -m src.booking_orchestrator "$@"
