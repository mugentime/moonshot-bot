"""Calculate balance timeline and find balance before Global TP"""
import asyncio
from binance import AsyncClient
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    # Get all income since Dec 1
    start = int(datetime(2025, 12, 1).timestamp() * 1000)
    income = await client.futures_income_history(startTime=start, limit=1000)

    # Also check for transfers
    transfers = await client.futures_income_history(incomeType='TRANSFER', startTime=start, limit=100)

    # Current balance
    acc = await client.futures_account()
    current = float(acc['totalWalletBalance'])

    print('=== BALANCE TIMELINE ===')
    print()

    # Sort all income by time
    all_income = sorted(income, key=lambda x: int(x.get('time', 0)), reverse=True)

    # Calculate running balance backwards
    running_balance = current

    # Group by significant events
    print(f'NOW:                      ${current:.2f}')
    print()

    # Find major events (batches of 5+ trades in 1 minute = likely Global TP)
    by_minute = {}
    for i in all_income:
        ts = int(i.get('time', 0))
        minute_key = ts // 60000
        if minute_key not in by_minute:
            by_minute[minute_key] = []
        by_minute[minute_key].append(i)

    # Show significant batches
    print('=== SIGNIFICANT EVENTS (5+ trades/min) ===')
    print()

    for minute_key in sorted(by_minute.keys(), reverse=True):
        batch = by_minute[minute_key]
        if len(batch) >= 5:
            ts = minute_key * 60000
            dt = datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M')
            batch_pnl = sum(float(i.get('income', 0)) for i in batch)

            # Calculate balance before this batch
            # Sum all income AFTER this batch
            income_after = sum(
                float(i.get('income', 0))
                for i in all_income
                if int(i.get('time', 0)) > (minute_key + 1) * 60000
            )
            balance_before = current - income_after - batch_pnl

            print(f'{dt}:')
            print(f'  Positions: {len(batch)}')
            print(f'  PnL:       ${batch_pnl:+.2f}')
            print(f'  Balance BEFORE: ${balance_before:.2f}')
            print(f'  Balance AFTER:  ${balance_before + batch_pnl:.2f}')
            print()

    # Show transfers if any
    if transfers:
        print('=== TRANSFERS ===')
        for t in transfers:
            ts = int(t.get('time', 0))
            dt = datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M')
            amt = float(t.get('income', 0))
            print(f'{dt}: ${amt:+.2f}')

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
