"""Get details of last Global TP at 21:53"""
import asyncio
from binance import AsyncClient
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    # Get recent trades
    income = await client.futures_income_history(incomeType='REALIZED_PNL', limit=100)
    income = sorted(income, key=lambda x: int(x.get('time', 0)))

    # Find the 21:53 batch
    target_minute = int(datetime(2025, 12, 16, 21, 53).timestamp() * 1000) // 60000

    tp_trades = [i for i in income if int(i.get('time', 0)) // 60000 == target_minute]

    print('=== LAST GLOBAL TP: 2025-12-16 21:53 ===')
    print()

    tp_pnl = 0
    for t in tp_trades:
        sym = t.get('symbol', 'N/A')
        pnl = float(t.get('income', 0))
        tp_pnl += pnl
        status = 'WIN' if pnl > 0 else 'LOSS'
        print(f'  {sym:15} ${pnl:+.4f} {status}')

    print()
    print(f'Total TP PnL: ${tp_pnl:+.4f}')

    # Calculate balance before/after
    # Sum all income AFTER the TP
    income_after = sum(
        float(i.get('income', 0))
        for i in income
        if int(i.get('time', 0)) // 60000 > target_minute
    )

    # Current balance
    acc = await client.futures_account()
    current = float(acc['totalWalletBalance'])

    balance_after_tp = current - income_after
    balance_before_tp = balance_after_tp - tp_pnl

    print()
    print(f'Balance BEFORE TP: ${balance_before_tp:.2f}')
    print(f'Balance AFTER TP:  ${balance_after_tp:.2f}')
    print(f'PROFIT:            ${tp_pnl:.2f}')
    print()
    print(f'Current Balance:   ${current:.2f}')

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
