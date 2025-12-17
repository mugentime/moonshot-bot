"""Backfill all historical Global TP events to the tracker"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance import AsyncClient
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime
from collections import defaultdict
from src.tp_tracker import GlobalTPTracker, GlobalTPEvent

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    # Get all realized PnL history
    income = await client.futures_income_history(incomeType='REALIZED_PNL', limit=1000)
    income = sorted(income, key=lambda x: int(x.get('time', 0)))

    # Group by minute to find batch closes
    by_minute = defaultdict(list)
    for i in income:
        minute = int(i.get('time', 0)) // 60000
        by_minute[minute].append(i)

    # Find batches with 3+ trades (Global TP pattern)
    batch_closes = []
    for minute, trades in by_minute.items():
        if len(trades) >= 3:
            total_pnl = sum(float(t.get('income', 0)) for t in trades)
            timestamp = datetime.fromtimestamp(minute * 60)
            batch_closes.append({
                'minute': minute,
                'timestamp': timestamp,
                'trades': trades,
                'count': len(trades),
                'total_pnl': total_pnl
            })

    batch_closes.sort(key=lambda x: x['minute'])

    # Get current balance to work backwards
    acc = await client.futures_account()
    current_balance = float(acc['totalWalletBalance'])

    # Create fresh tracker
    tracker = GlobalTPTracker()
    tracker.events = []  # Clear any existing events

    events_to_add = []

    # For each batch, calculate balance before/after
    for batch in batch_closes:
        batch_minute = batch['minute']

        # Sum all income AFTER this batch
        income_after = sum(
            float(i.get('income', 0))
            for i in income
            if int(i.get('time', 0)) // 60000 > batch_minute
        )

        balance_after = current_balance - income_after
        balance_before = balance_after - batch['total_pnl']

        # Build position details
        positions = []
        for t in batch['trades']:
            positions.append({
                'symbol': t.get('symbol', 'N/A'),
                'direction': 'LONG' if float(t.get('income', 0)) >= 0 else 'SHORT',  # Approximate
                'entry_price': 0,
                'exit_price': 0,
                'pnl_usd': float(t.get('income', 0)),
                'pnl_percent': 0,
                'margin': 0
            })

        # Create event
        event_id = f"TP_{batch['timestamp'].strftime('%Y%m%d_%H%M%S')}"

        # Estimate trigger percent (profit / margin ratio approximated from PnL)
        # For historical data we don't have exact trigger %, use profit as proxy
        trigger_pct = (batch['total_pnl'] / balance_before * 100) if balance_before > 0 else 0

        event = GlobalTPEvent(
            id=event_id,
            timestamp=batch['timestamp'].isoformat(),
            trigger_percent=abs(trigger_pct),  # Approximate
            threshold_percent=1.0,  # Default threshold
            balance_before=balance_before,
            balance_after=balance_after,
            profit_usd=batch['total_pnl'],
            positions_closed=len(batch['trades']),
            positions=positions,
            total_margin=0
        )

        events_to_add.append(event)

    # Add all events and save
    tracker.events = events_to_add
    tracker._save()

    print(f"Backfilled {len(events_to_add)} Global TP events to tracker")
    print()

    # Print summary
    total_profit = sum(e.profit_usd for e in events_to_add)
    winners = len([e for e in events_to_add if e.profit_usd > 0])
    losers = len([e for e in events_to_add if e.profit_usd <= 0])

    print("=" * 60)
    print("BACKFILL SUMMARY")
    print("=" * 60)
    print(f"Total Events:     {len(events_to_add)}")
    print(f"Total Profit:     ${total_profit:+.2f}")
    print(f"Winners:          {winners}")
    print(f"Losers:           {losers}")
    print(f"Win Rate:         {winners/len(events_to_add)*100:.1f}%")
    print()
    print("Events saved to: data/global_tp_tracker.json")

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
