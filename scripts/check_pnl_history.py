"""Check PnL history and analyze losses from Binance"""
import asyncio
from binance import AsyncClient
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime

async def check_history():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    start_time = int(datetime(2025, 12, 7).timestamp() * 1000)

    # Get all income by type
    print('=== INCOME BY TYPE (since Dec 7) ===')
    income = await client.futures_income_history(startTime=start_time, limit=1000)

    by_type = {}
    for i in income:
        t = i.get('incomeType', 'UNKNOWN')
        amt = float(i.get('income', 0))
        if t not in by_type:
            by_type[t] = 0
        by_type[t] += amt

    for t, total in sorted(by_type.items(), key=lambda x: x[1]):
        print(f'{t:20}: ${total:+.2f}')

    # Daily breakdown
    print('\n=== PnL BY DAY ===')
    income = await client.futures_income_history(startTime=start_time, limit=1000)

    by_day = {}
    for i in income:
        ts = int(i.get('time', 0))
        day = datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d')
        amt = float(i.get('income', 0))
        if day not in by_day:
            by_day[day] = 0
        by_day[day] += amt

    for day, total in sorted(by_day.items()):
        marker = ' <-- BIG LOSS' if total < -1 else ''
        print(f'{day}: ${total:+.2f}{marker}')

    print(f'\nGrand Total: ${sum(by_day.values()):.2f}')

    # Account info
    acc = await client.futures_account()
    print(f'\nCurrent Wallet Balance: ${float(acc["totalWalletBalance"]):.2f}')

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(check_history())
