"""Find the REAL Global TP events (positive PnL batches)"""
import asyncio
from binance import AsyncClient
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    # Get more history
    start = int(datetime(2025, 12, 1).timestamp() * 1000)
    income = await client.futures_income_history(startTime=start, limit=1000)

    # Current balance
    acc = await client.futures_account()
    current = float(acc['totalWalletBalance'])

    # Sort by time
    income = sorted(income, key=lambda x: int(x.get('time', 0)))

    # Group by minute
    by_minute = {}
    for i in income:
        ts = int(i.get('time', 0))
        minute_key = ts // 60000
        if minute_key not in by_minute:
            by_minute[minute_key] = []
        by_minute[minute_key].append(i)

    print('=== REAL GLOBAL TP EVENTS (5+ positions, POSITIVE PnL) ===')
    print()

    # Find batches with 5+ positions AND positive PnL
    tp_events = []
    for minute_key in sorted(by_minute.keys()):
        batch = by_minute[minute_key]
        if len(batch) >= 5:
            batch_pnl = sum(float(i.get('income', 0)) for i in batch)
            if batch_pnl > 0.01:  # Positive PnL (more than $0.01)
                ts = minute_key * 60000
                dt = datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M')
                tp_events.append({
                    'time': dt,
                    'ts': minute_key,
                    'positions': len(batch),
                    'pnl': batch_pnl,
                    'trades': batch
                })

    if not tp_events:
        print('No Global TP events with positive PnL found in history.')
        print()
        print('This means either:')
        print('1. Global TP never triggered profitably')
        print('2. The events are older than the history limit')
    else:
        # Calculate balance before/after for each TP event
        all_sorted = sorted(income, key=lambda x: int(x.get('time', 0)))

        for tp in tp_events:
            # Sum all income AFTER this TP
            income_after = sum(
                float(i.get('income', 0))
                for i in all_sorted
                if int(i.get('time', 0)) > (tp['ts'] + 1) * 60000
            )

            balance_after_tp = current - income_after
            balance_before_tp = balance_after_tp - tp['pnl']

            print(f"Time: {tp['time']}")
            print(f"Positions closed: {tp['positions']}")
            print(f"PnL: ${tp['pnl']:+.4f}")
            print(f"Balance BEFORE: ${balance_before_tp:.2f}")
            print(f"Balance AFTER:  ${balance_after_tp:.2f}")
            print(f"Profit: ${tp['pnl']:.2f}")
            print('-' * 40)
            print()

    print(f'Current Balance: ${current:.2f}')

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
