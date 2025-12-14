"""Detailed position analysis with trailing stop conditions"""
import asyncio
from binance import AsyncClient
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
    positions = await client.futures_position_information()
    open_pos = [p for p in positions if float(p['positionAmt']) != 0]

    # Get current prices
    tickers = await client.futures_ticker()
    price_map = {t['symbol']: float(t['lastPrice']) for t in tickers}

    print('=' * 100)
    print('DETAILED POSITION ANALYSIS - TRAILING STOP & TAKE PROFIT CONDITIONS')
    print('=' * 100)
    print()
    print('CONFIGURATION:')
    print('  - Stop Loss: 3% (software monitoring)')
    print('  - Trailing Activation: +15% profit (price move, not leveraged)')
    print('  - Trailing Distance: 10% from peak')
    print('  - Leverage: 20x')
    print()

    winners = []
    losers = []

    for p in open_pos:
        sym = p['symbol']
        amt = float(p['positionAmt'])
        entry = float(p['entryPrice'])
        pnl_usd = float(p['unRealizedProfit'])
        leverage = int(p['leverage'])
        current = price_map.get(sym, entry)

        # Calculate profit % (price move, not leveraged)
        if amt > 0:  # LONG
            pnl_pct = ((current - entry) / entry) * 100
        else:  # SHORT
            pnl_pct = ((entry - current) / entry) * 100

        leveraged_pnl_pct = pnl_pct * leverage

        data = {
            'symbol': sym,
            'side': 'LONG' if amt > 0 else 'SHORT',
            'entry': entry,
            'current': current,
            'pnl_pct': pnl_pct,
            'leveraged_pnl_pct': leveraged_pnl_pct,
            'pnl_usd': pnl_usd,
            'leverage': leverage
        }

        if pnl_usd > 0:
            winners.append(data)
        else:
            losers.append(data)

    # Sort winners by profit
    winners.sort(key=lambda x: x['pnl_usd'], reverse=True)

    print('=' * 100)
    print(f'WINNING POSITIONS ({len(winners)} total)')
    print('=' * 100)

    for i, w in enumerate(winners, 1):
        trailing_active = w['pnl_pct'] >= 15.0
        if trailing_active:
            trail_exit = w['pnl_pct'] - 10.0  # Current profit - 10%
            status = f'ACTIVE @ peak {w["pnl_pct"]:.2f}% -> exit if drops to {trail_exit:.2f}%'
        else:
            needed = 15.0 - w['pnl_pct']
            status = f'INACTIVE (needs +{needed:.2f}% more price move to activate)'

        # Calculate actual SL price
        if w['side'] == 'LONG':
            sl_price = w['entry'] * (1 - 0.03)  # 3% below entry
        else:
            sl_price = w['entry'] * (1 + 0.03)  # 3% above entry

        print()
        print(f'{i}. {w["symbol"]}')
        print(f'   Side: {w["side"]} | Leverage: {w["leverage"]}x')
        print(f'   Entry: {w["entry"]:.8f} | Current: {w["current"]:.8f}')
        print(f'   Profit: {w["pnl_pct"]:+.4f}% ({w["leveraged_pnl_pct"]:+.2f}% on margin) | PnL: ${w["pnl_usd"]:+.2f}')
        print(f'   TRAILING STOP: {status}')
        print(f'   STOP LOSS: Entry*0.97 = {sl_price:.8f} | Currently {abs((w["current"]-sl_price)/w["current"]*100):.2f}% away')

    if losers:
        losers.sort(key=lambda x: x['pnl_usd'])  # Sort by most loss first
        print()
        print('=' * 100)
        print(f'LOSING POSITIONS ({len(losers)} total) - NO TRAILING STOP')
        print('=' * 100)
        for l in losers:
            sl_trigger = -3.0
            remaining_to_sl = abs(sl_trigger - l['pnl_pct'])

            if l['side'] == 'LONG':
                sl_price = l['entry'] * (1 - 0.03)
            else:
                sl_price = l['entry'] * (1 + 0.03)

            print()
            print(f'- {l["symbol"]}')
            print(f'   Side: {l["side"]} | Entry: {l["entry"]:.8f} | Current: {l["current"]:.8f}')
            print(f'   Current loss: {l["pnl_pct"]:+.4f}% (${l["pnl_usd"]:+.2f})')
            print(f'   SL triggers at: -3% ({remaining_to_sl:.2f}% away from SL)')
            print(f'   SL Price: {sl_price:.8f}')

    print()
    print('=' * 100)
    print('SUMMARY')
    print('=' * 100)
    total_pnl = sum(w['pnl_usd'] for w in winners) + sum(l['pnl_usd'] for l in losers)
    print(f'Total Positions: {len(winners) + len(losers)}')
    print(f'Winners: {len(winners)} | Losers: {len(losers)}')
    print(f'Total Unrealized PnL: ${total_pnl:+.2f}')

    trailing_active_count = sum(1 for w in winners if w['pnl_pct'] >= 15.0)
    print(f'Trailing Stops Active: {trailing_active_count}')

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
