"""Get all moonshots and moondrops from Binance Futures"""
import asyncio
from binance import AsyncClient
import os
import sys
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

async def get_movers():
    client = await AsyncClient.create(
        os.getenv('BINANCE_API_KEY'),
        os.getenv('BINANCE_API_SECRET')
    )

    try:
        # Get all futures tickers
        tickers = await client.futures_ticker()

        # Sort by 24h price change
        sorted_tickers = sorted(tickers, key=lambda x: float(x['priceChangePercent']), reverse=True)

        print('='*80)
        print('MOONSHOTS (Top gainers in last 24h) - Binance Futures')
        print('='*80)
        print(f"{'Symbol':<18} {'24h Change':<12} {'Price':<15} {'Volume (USD)':<18}")
        print('-'*80)

        moonshots = []
        for t in sorted_tickers[:50]:
            change = float(t['priceChangePercent'])
            if change >= 10:
                vol = float(t['quoteVolume'])
                price = float(t['lastPrice'])
                print(f"{t['symbol']:<18} {change:>+10.2f}% ${price:>12.6f} ${vol:>16,.0f}")
                moonshots.append((t['symbol'], change))

        print()
        print('='*80)
        print('MOONDROPS (Top losers in last 24h) - Binance Futures')
        print('='*80)
        print(f"{'Symbol':<18} {'24h Change':<12} {'Price':<15} {'Volume (USD)':<18}")
        print('-'*80)

        moondrops = []
        sorted_losers = sorted(tickers, key=lambda x: float(x['priceChangePercent']))
        for t in sorted_losers[:50]:
            change = float(t['priceChangePercent'])
            if change <= -10:
                vol = float(t['quoteVolume'])
                price = float(t['lastPrice'])
                print(f"{t['symbol']:<18} {change:>+10.2f}% ${price:>12.6f} ${vol:>16,.0f}")
                moondrops.append((t['symbol'], change))

        print()
        print('='*80)
        print('SUMMARY')
        print('='*80)
        print(f'Total moonshots (>+10%): {len(moonshots)}')
        print(f'Total moondrops (<-10%): {len(moondrops)}')

        if moonshots:
            top = moonshots[0]
            print(f'Biggest moonshot: {top[0]} at {top[1]:+.2f}%')

        if moondrops:
            bottom = moondrops[0]
            print(f'Biggest moondrop: {bottom[0]} at {bottom[1]:+.2f}%')

    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(get_movers())
