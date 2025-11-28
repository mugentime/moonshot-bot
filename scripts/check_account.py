"""Check account positions and trade history"""
import asyncio
from binance import AsyncClient
import os
from dotenv import load_dotenv
from datetime import datetime
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

async def check_positions_and_history():
    client = await AsyncClient.create(
        os.getenv('BINANCE_API_KEY'),
        os.getenv('BINANCE_API_SECRET')
    )

    try:
        # Get current positions
        positions = await client.futures_position_information()
        open_positions = [p for p in positions if float(p['positionAmt']) != 0]

        print('='*80)
        print('CURRENT OPEN POSITIONS')
        print('='*80)
        if open_positions:
            for p in open_positions:
                amt = float(p['positionAmt'])
                entry = float(p['entryPrice'])
                mark = float(p['markPrice'])
                pnl = float(p['unRealizedProfit'])
                side = 'LONG' if amt > 0 else 'SHORT'
                pnl_pct = ((mark - entry) / entry * 100) if entry > 0 else 0
                if amt < 0:
                    pnl_pct = -pnl_pct
                print(f'{p["symbol"]:<18} {side:<6} Entry: ${entry:<12.6f} PnL: ${pnl:>+10.2f} ({pnl_pct:>+6.2f}%)')
        else:
            print('No open positions')

        # Get recent trades (last 24h)
        print()
        print('='*80)
        print('REALIZED PnL (Last 24 hours)')
        print('='*80)

        end_time = int(time.time() * 1000)
        start_time = end_time - (24 * 60 * 60 * 1000)

        # Get income history (realized PnL)
        income = await client.futures_income_history(
            incomeType='REALIZED_PNL',
            startTime=start_time,
            endTime=end_time,
            limit=100
        )

        if income:
            total_pnl = 0
            print(f'{"Symbol":<18} {"PnL":<14} {"Time":<20}')
            print('-'*60)
            for i in income:
                pnl = float(i['income'])
                total_pnl += pnl
                ts = int(i['time']) / 1000
                time_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
                print(f'{i["symbol"]:<18} ${pnl:>+12.4f} {time_str}')
            print('-'*60)
            print(f'TOTAL REALIZED PnL (24h): ${total_pnl:>+.2f}')
        else:
            print('No realized PnL in last 24 hours')

        # Get account balance
        print()
        print('='*80)
        print('ACCOUNT BALANCE')
        print('='*80)
        balance = await client.futures_account_balance()
        for b in balance:
            if float(b['balance']) > 0:
                print(f'{b["asset"]}: ${float(b["balance"]):,.4f}')

    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(check_positions_and_history())
