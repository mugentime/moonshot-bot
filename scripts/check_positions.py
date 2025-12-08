"""Check open positions"""
import asyncio
from binance import AsyncClient
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET

async def check_positions():
    client = await AsyncClient.create(
        api_key=BINANCE_API_KEY,
        api_secret=BINANCE_API_SECRET
    )

    # Get positions
    positions = await client.futures_position_information()
    open_positions = [p for p in positions if float(p['positionAmt']) != 0]

    print(f'Open Positions: {len(open_positions)}')
    print()

    if open_positions:
        total_pnl = 0
        for p in open_positions:
            sym = p['symbol']
            amt = float(p['positionAmt'])
            pnl = float(p['unRealizedProfit'])
            entry = float(p['entryPrice'])
            side = 'LONG' if amt > 0 else 'SHORT'
            total_pnl += pnl
            print(f'  {sym:15} {side:5} | Entry: {entry:.6f} | PnL: ${pnl:+.2f}')
        print()
        print(f'Total Unrealized PnL: ${total_pnl:+.2f}')
    else:
        print('NO OPEN POSITIONS!')

    # Check balance
    account = await client.futures_account_balance()
    for a in account:
        if a['asset'] == 'USDT':
            print(f'USDT Balance: ${float(a["balance"]):.2f}')
            break

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(check_positions())
