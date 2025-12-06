"""
Show best performing position
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)

from binance import AsyncClient

async def main():
    client = await AsyncClient.create(
        os.getenv('BINANCE_API_KEY'),
        os.getenv('BINANCE_API_SECRET')
    )

    try:
        positions = await client.futures_position_information()

        results = []
        for p in positions:
            amt = float(p['positionAmt'])
            if amt != 0:
                entry = float(p['entryPrice'])
                mark = float(p['markPrice'])
                side = 'LONG' if amt > 0 else 'SHORT'
                pnl = float(p['unRealizedProfit'])

                if entry > 0:
                    if side == 'LONG':
                        pnl_pct = ((mark - entry) / entry) * 100
                    else:
                        pnl_pct = ((entry - mark) / entry) * 100
                else:
                    pnl_pct = 0

                results.append({
                    'symbol': p['symbol'],
                    'side': side,
                    'entry': entry,
                    'mark': mark,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'leverage': int(p['leverage'])
                })

        # Sort by P&L %
        results.sort(key=lambda x: x['pnl_pct'], reverse=True)

        print('=' * 60)
        print('POSITIONS RANKED BY PERFORMANCE')
        print('=' * 60)

        total_pnl = 0
        for i, r in enumerate(results, 1):
            emoji = '1' if i == 1 else '2' if i == 2 else '3' if i == 3 else '  '
            sign = '+' if r['pnl_pct'] >= 0 else ''
            print(f"{emoji} {i:2}. {r['symbol']:15} {r['side']:5} | {sign}{r['pnl_pct']:.2f}% | ${r['pnl']:+.2f}")
            total_pnl += r['pnl']

        print('=' * 60)
        print(f"TOTAL P&L: ${total_pnl:+.2f}")
        print('=' * 60)

        if results:
            best = results[0]
            print(f"\n** BEST PERFORMER: {best['symbol']} **")
            print(f"   Side: {best['side']}")
            print(f"   Entry: {best['entry']}")
            print(f"   Current: {best['mark']}")
            print(f"   P&L: +{best['pnl_pct']:.2f}% (${best['pnl']:+.2f})")
            print(f"   Leverage: {best['leverage']}x")

    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
