"""Backfill all historical Global TP events to tracker"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance import AsyncClient
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime
from collections import defaultdict

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

    # Calculate balance at each point working backwards
    all_income = sorted(income, key=lambda x: int(x.get('time', 0)), reverse=True)

    print("=" * 80)
    print("ALL GLOBAL TP EVENTS FOUND")
    print("=" * 80)
    print()

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

        print(f"GLOBAL TP: {batch['timestamp']}")
        print(f"  Positions closed: {batch['count']}")
        print(f"  Balance BEFORE: ${balance_before:.2f}")
        print(f"  Balance AFTER:  ${balance_after:.2f}")
        print(f"  PROFIT:         ${batch['total_pnl']:+.2f}")
        print()

        # Show individual positions
        for t in batch['trades']:
            sym = t.get('symbol', 'N/A')
            pnl = float(t.get('income', 0))
            status = 'WIN' if pnl > 0 else 'LOSS'
            print(f"    {sym:15} ${pnl:+.4f} {status}")
        print()
        print("-" * 40)
        print()

    print(f"Total Global TP events found: {len(batch_closes)}")
    print(f"Current balance: ${current_balance:.2f}")

    await client.close_connection()

    return batch_closes, current_balance, income

if __name__ == "__main__":
    asyncio.run(main())
