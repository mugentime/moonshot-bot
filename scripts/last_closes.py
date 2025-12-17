"""Get last batch closes from Binance"""
import asyncio
from binance import AsyncClient
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    # Get last 100 trades
    income = await client.futures_income_history(incomeType='REALIZED_PNL', limit=100)

    # Sort by time descending
    income = sorted(income, key=lambda x: int(x.get('time', 0)), reverse=True)

    # Group by minute
    by_minute = {}
    for i in income:
        ts = int(i.get('time', 0))
        minute_key = ts // 60000
        if minute_key not in by_minute:
            by_minute[minute_key] = []
        by_minute[minute_key].append(i)

    print('LAST 10 BATCH CLOSES:')
    print()

    count = 0
    for minute_key in sorted(by_minute.keys(), reverse=True):
        if count >= 10:
            break
        batch = by_minute[minute_key]
        ts = minute_key * 60000
        dt = datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M')
        pnl = sum(float(i.get('income', 0)) for i in batch)
        status = 'PROFIT' if pnl > 0 else 'LOSS'
        print(f'{dt} | {len(batch):2} positions | ${pnl:+.4f} | {status}')
        count += 1

    # Get current balance
    acc = await client.futures_account()
    print()
    print(f"Current balance: ${float(acc['totalWalletBalance']):.2f}")

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
