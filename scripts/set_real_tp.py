"""Set only the REAL Global TP event (Dec 16 22:07)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tp_tracker import GlobalTPTracker, GlobalTPEvent

# Create fresh tracker with only the real Global TP
tracker = GlobalTPTracker()
tracker.events = []

# The ONLY real Global TP - Dec 16 22:07 (04:07 UTC on Dec 17)
event = GlobalTPEvent(
    id="TP_20251216_220710",
    timestamp="2025-12-16T22:07:10",
    trigger_percent=16.78,  # From logs: +16.78% triggered
    threshold_percent=1.0,   # 1% threshold was configured
    balance_before=3.72,
    balance_after=4.03,
    profit_usd=0.32,
    positions_closed=3,
    positions=[
        {"symbol": "BULLAUSDT", "direction": "LONG", "pnl_usd": 0.0632, "pnl_percent": 0, "margin": 0, "entry_price": 0, "exit_price": 0},
        {"symbol": "PNUTUSDT", "direction": "LONG", "pnl_usd": 0.1302, "pnl_percent": 0, "margin": 0, "entry_price": 0, "exit_price": 0},
        {"symbol": "PNUTUSDT", "direction": "LONG", "pnl_usd": 0.1233, "pnl_percent": 0, "margin": 0, "entry_price": 0, "exit_price": 0},
    ],
    total_margin=0
)

tracker.events = [event]
tracker._save()

print("Tracker reset with ONLY the real Global TP event:")
print()
print(f"  Timestamp:      {event.timestamp}")
print(f"  Trigger:        {event.trigger_percent}% (threshold: {event.threshold_percent}%)")
print(f"  Balance BEFORE: ${event.balance_before:.2f}")
print(f"  Balance AFTER:  ${event.balance_after:.2f}")
print(f"  PROFIT:         ${event.profit_usd:+.2f}")
print(f"  Positions:      {event.positions_closed}")
print()
print("Saved to: data/global_tp_tracker.json")
