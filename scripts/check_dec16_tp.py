"""Check the Dec 16 Global TP event specifically"""
import asyncio
from binance import AsyncClient
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    # Search from Dec 15 to now
    start = int(datetime(2025, 12, 15).timestamp() * 1000)
    income = await client.futures_income_history(startTime=start, limit=500)

    # Current balance
    acc = await client.futures_account()
    current = float(acc['totalWalletBalance'])

    print(f'Current Balance: ${current:.2f}')
    print()

    # Sort by time
    income = sorted(income, key=lambda x: int(x.get('time', 0)), reverse=True)

    # Group by minute to find batches
    by_minute = {}
    for i in income:
        ts = int(i.get('time', 0))
        minute_key = ts // 60000
        if minute_key not in by_minute:
            by_minute[minute_key] = []
        by_minute[minute_key].append(i)

    print('=== ALL BATCH CLOSES (Dec 15+) ===')
    print()

    running_balance = current

    for minute_key in sorted(by_minute.keys(), reverse=True):
        batch = by_minute[minute_key]
        if len(batch) >= 3:  # Show batches of 3+ trades
            ts = minute_key * 60000
            dt = datetime.fromtimestamp(ts/1000).strftime('%m-%d %H:%M')
            batch_pnl = sum(float(i.get('income', 0)) for i in batch)

            balance_before = running_balance - batch_pnl
            is_global_tp = len(batch) >= 10

            marker = ' <-- GLOBAL TP' if is_global_tp else ''

            print(f'{dt} | {len(batch):2} pos | PnL: ${batch_pnl:+.4f} | Before: ${balance_before:.2f}{marker}')

            running_balance = balance_before

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
