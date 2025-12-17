"""Quick check of recent income and positions"""
import asyncio
from binance import AsyncClient
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET
from datetime import datetime

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    income = await client.futures_income_history(limit=20)
    income = sorted(income, key=lambda x: int(x.get('time', 0)), reverse=True)

    print('=== RECENT INCOME HISTORY ===')
    for i in income[:15]:
        ts = datetime.fromtimestamp(int(i['time'])/1000)
        inc_type = i.get('incomeType', 'N/A')
        sym = i.get('symbol', 'N/A')
        amt = float(i.get('income', 0))
        print(f'{ts.strftime("%H:%M:%S")} | {inc_type:15} | {sym:15} | ${amt:+.4f}')

    positions = await client.futures_position_information()
    open_pos = [p for p in positions if float(p['positionAmt']) != 0]

    print(f'\n=== CURRENT POSITIONS ({len(open_pos)}) ===')
    for p in open_pos:
        sym = p['symbol']
        amt = float(p['positionAmt'])
        pnl = float(p['unRealizedProfit'])
        entry = float(p['entryPrice'])
        mark = float(p['markPrice'])
        side = 'LONG' if amt > 0 else 'SHORT'
        if side == 'LONG':
            roi = ((mark - entry) / entry) * 100
        else:
            roi = ((entry - mark) / entry) * 100
        print(f'  {sym:15} | {side:5} | ROI: {roi:+.2f}% | PnL: ${pnl:+.4f}')

    acc = await client.futures_account()
    print(f'\nWallet: ${float(acc["totalWalletBalance"]):.4f}')
    print(f'Equity: ${float(acc["totalMarginBalance"]):.4f}')

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
