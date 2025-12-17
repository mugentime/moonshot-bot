"""Check last Global TP event details"""
import asyncio
from binance import AsyncClient
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    income = await client.futures_income_history(incomeType='REALIZED_PNL', limit=50)

    print('=== LAST GLOBAL TP EVENT BREAKDOWN ===')
    print()

    # Group trades by minute
    by_minute = {}
    for i in income:
        ts = int(i.get('time', 0))
        minute_key = ts // 60000  # Group by minute
        if minute_key not in by_minute:
            by_minute[minute_key] = []
        by_minute[minute_key].append(i)

    # Find the batch with most trades (likely Global TP)
    largest_batch = max(by_minute.values(), key=len)

    ts = int(largest_batch[0].get('time', 0))
    dt = datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M')
    print(f'Time: {dt}')
    print(f'Positions closed: {len(largest_batch)}')
    print()

    winners = 0
    losers = 0
    total_win = 0
    total_loss = 0

    for i in sorted(largest_batch, key=lambda x: float(x.get('income', 0))):
        sym = i.get('symbol', 'N/A')
        pnl = float(i.get('income', 0))

        if pnl > 0:
            winners += 1
            total_win += pnl
            status = 'WIN '
        else:
            losers += 1
            total_loss += pnl
            status = 'LOSS'

        print(f'{sym:15} | ${pnl:+.4f} | {status}')

    print()
    print(f'Winners: {winners} (${total_win:+.4f})')
    print(f'Losers:  {losers} (${total_loss:.4f})')
    print('-' * 30)
    print(f'NET PnL: ${total_win + total_loss:+.4f}')

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
