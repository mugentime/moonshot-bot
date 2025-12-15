"""Show only positions with ACTIVE trailing stops"""
import asyncio
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
from binance import AsyncClient

TRAILING_ACTIVATION = 15.0  # +15% to activate
TRAILING_DISTANCE = 10.0    # 10% trail from peak

async def main():
    client = await AsyncClient.create(
        os.getenv('BINANCE_API_KEY'),
        os.getenv('BINANCE_API_SECRET')
    )

    positions = await client.futures_position_information()
    open_pos = [p for p in positions if float(p['positionAmt']) != 0]

    tickers = await client.futures_ticker()
    price_map = {t['symbol']: float(t['lastPrice']) for t in tickers}

    print('=' * 80)
    print('ACTIVE TRAILING STOPS (Profit >= 15%)')
    print('=' * 80)
    print()
    print(f'Config: Activation at +{TRAILING_ACTIVATION}% | Trail distance: {TRAILING_DISTANCE}% from peak')
    print()

    active_trailing = []
    all_positions = []

    for p in open_pos:
        sym = p['symbol']
        amt = float(p['positionAmt'])
        entry = float(p['entryPrice'])
        current = price_map.get(sym, entry)
        leverage = int(p['leverage'])
        pnl_usd = float(p['unRealizedProfit'])

        if amt > 0:  # LONG
            pnl_pct = ((current - entry) / entry) * 100
        else:  # SHORT
            pnl_pct = ((entry - current) / entry) * 100

        data = {
            'symbol': sym,
            'side': 'LONG' if amt > 0 else 'SHORT',
            'entry': entry,
            'current': current,
            'pnl_pct': pnl_pct,
            'pnl_usd': pnl_usd,
            'leverage': leverage
        }

        all_positions.append(data)

        if pnl_pct >= TRAILING_ACTIVATION:
            active_trailing.append(data)

    if active_trailing:
        active_trailing.sort(key=lambda x: x['pnl_pct'], reverse=True)

        for i, pos in enumerate(active_trailing, 1):
            trail_exit = pos['pnl_pct'] - TRAILING_DISTANCE

            print(f"{i}. {pos['symbol']}")
            print(f"   Direction: {pos['side']} | Leverage: {pos['leverage']}x")
            print(f"   Entry: {pos['entry']:.8f}")
            print(f"   Current: {pos['current']:.8f}")
            print(f"   Profit: +{pos['pnl_pct']:.2f}% | PnL: ${pos['pnl_usd']:+.2f}")
            print(f"   TRAILING STOP ACTIVE!")
            print(f"   Peak: +{pos['pnl_pct']:.2f}%")
            print(f"   EXIT TRIGGERS IF DROPS TO: +{trail_exit:.2f}%")
            print()

        print('=' * 80)
        print(f"TOTAL: {len(active_trailing)} positions with ACTIVE trailing stop")
        print('=' * 80)
    else:
        print('NO POSITIONS WITH ACTIVE TRAILING STOP')
        print()
        print('=' * 80)
        print('TOP 5 CLOSEST TO ACTIVATION:')
        print('=' * 80)

        winners = [p for p in all_positions if p['pnl_pct'] > 0]
        winners.sort(key=lambda x: x['pnl_pct'], reverse=True)

        for pos in winners[:5]:
            needed = TRAILING_ACTIVATION - pos['pnl_pct']
            print(f"  {pos['symbol']}: +{pos['pnl_pct']:.2f}% (needs +{needed:.2f}% more)")
            print(f"      PnL: ${pos['pnl_usd']:+.2f} | {pos['side']} @ {pos['leverage']}x")
            print()

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
