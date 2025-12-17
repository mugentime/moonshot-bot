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
        total_margin = 0
        for p in open_positions:
            sym = p['symbol']
            amt = float(p['positionAmt'])
            pnl = float(p['unRealizedProfit'])
            entry = float(p['entryPrice'])
            leverage = int(p['leverage'])
            notional = abs(amt * entry)
            margin = notional / leverage
            side = 'LONG' if amt > 0 else 'SHORT'
            total_pnl += pnl
            total_margin += margin
            print(f'  {sym:15} {side:5} | Entry: {entry:.6f} | Qty: {abs(amt):.4f} | Margin: ${margin:.2f} | PnL: ${pnl:+.2f}')
        print()
        print(f'Total Margin: ${total_margin:.2f}')
        print(f'Total Unrealized PnL: ${total_pnl:+.2f}')
    else:
        print('NO OPEN POSITIONS!')

    # Check balance - use futures_account() for accurate figures
    account = await client.futures_account()
    wallet_balance = float(account['totalWalletBalance'])
    margin_balance = float(account['totalMarginBalance'])
    available_balance = float(account['availableBalance'])
    unrealized_pnl = float(account['totalUnrealizedProfit'])

    print()
    print(f'Wallet Balance: ${wallet_balance:.2f}')
    print(f'Margin Balance: ${margin_balance:.2f}')
    print(f'Unrealized PnL: ${unrealized_pnl:+.2f}')
    print(f'Available Balance: ${available_balance:.2f}')

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(check_positions())
