"""Equity timeline every 30 minutes since Global TP enabled"""
import asyncio
from binance import AsyncClient
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime, timedelta

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    income = await client.futures_income_history(limit=500)
    income = sorted(income, key=lambda x: int(x.get('time', 0)))

    # Current balance
    acc = await client.futures_account()
    current_wallet = float(acc['totalWalletBalance'])

    # Calculate starting balance at 21:50 by working backwards
    cutoff = datetime(2025, 12, 16, 21, 50).timestamp() * 1000
    income_since = [i for i in income if int(i.get('time', 0)) > cutoff]
    total_since = sum(float(i.get('income', 0)) for i in income_since)

    balance_at_2150 = current_wallet - total_since

    # Build equity timeline every 30 min
    print('=== EQUITY TIMELINE (Every 30 min since Global TP) ===')
    print('')
    print('Time   |  Equity   |  Change')
    print('-' * 35)

    start = datetime(2025, 12, 16, 21, 50)
    now = datetime.now()

    running_balance = balance_at_2150
    current_time = start
    prev_balance = balance_at_2150

    while current_time <= now:
        # Sum income in this 30 min window
        window_start = current_time.timestamp() * 1000
        window_end = (current_time + timedelta(minutes=30)).timestamp() * 1000

        window_income = sum(
            float(i.get('income', 0))
            for i in income
            if window_start <= int(i.get('time', 0)) < window_end
        )

        running_balance += window_income

        change_str = f'+{window_income:.4f}' if window_income >= 0 else f'{window_income:.4f}'
        print(f'{current_time.strftime("%H:%M")}  |  ${running_balance:.4f}  |  {change_str}')

        current_time += timedelta(minutes=30)

    print('-' * 35)
    print(f'NOW    |  ${current_wallet:.4f}')
    print('')
    print(f'Start (21:50):  ${balance_at_2150:.4f}')
    print(f'Current:        ${current_wallet:.4f}')
    print(f'Net Change:     ${current_wallet - balance_at_2150:+.4f}')

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
