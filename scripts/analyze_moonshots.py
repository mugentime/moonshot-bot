"""
Analyze Binance Futures for moonshot moves in the last N days
"""
import asyncio
from binance import AsyncClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')

async def analyze_moonshots(days=5, min_gain_percent=20):
    """Find all pairs that had gains >= min_gain_percent in the last N days"""

    client = await AsyncClient.create(BINANCE_API_KEY, BINANCE_API_SECRET)

    try:
        # Get all futures symbols
        exchange_info = await client.futures_exchange_info()
        symbols = []
        for s in exchange_info['symbols']:
            if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] in ['USDT', 'USDC'] and s['status'] == 'TRADING':
                symbols.append(s['symbol'])

        print(f"Analyzing {len(symbols)} perpetual futures pairs over last {days} days...")
        print(f"Looking for moves >= {min_gain_percent}%\n")

        moonshots = []

        for i, symbol in enumerate(symbols):
            try:
                # Get daily klines for the last N days
                klines = await client.futures_klines(
                    symbol=symbol,
                    interval='1d',
                    limit=days + 1
                )

                if len(klines) < 2:
                    continue

                # Analyze each day for significant moves
                for j in range(1, len(klines)):
                    open_price = float(klines[j][1])
                    high_price = float(klines[j][2])
                    low_price = float(klines[j][3])
                    close_price = float(klines[j][4])
                    volume = float(klines[j][5])
                    timestamp = klines[j][0]

                    # Calculate intraday gain (low to high)
                    if low_price > 0:
                        intraday_gain = ((high_price - low_price) / low_price) * 100
                    else:
                        intraday_gain = 0

                    # Calculate open to close gain
                    if open_price > 0:
                        daily_gain = ((close_price - open_price) / open_price) * 100
                    else:
                        daily_gain = 0

                    # Check for moonshot (either intraday or daily)
                    max_gain = max(intraday_gain, daily_gain)

                    if max_gain >= min_gain_percent:
                        date = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d')
                        moonshots.append({
                            'symbol': symbol,
                            'date': date,
                            'intraday_gain': intraday_gain,
                            'daily_gain': daily_gain,
                            'low': low_price,
                            'high': high_price,
                            'open': open_price,
                            'close': close_price,
                            'volume_usdt': volume * close_price
                        })

                if (i + 1) % 50 == 0:
                    print(f"Processed {i + 1}/{len(symbols)} pairs...")

            except Exception as e:
                continue

        # Sort by gain
        moonshots.sort(key=lambda x: x['intraday_gain'], reverse=True)

        print(f"\n{'='*80}")
        print(f"MOONSHOT REPORT - Last {days} Days")
        print(f"{'='*80}")
        print(f"\nTotal moonshots found (>={min_gain_percent}%): {len(moonshots)}\n")

        if moonshots:
            print(f"{'Symbol':<15} {'Date':<12} {'Intraday%':<12} {'Daily%':<10} {'Low':<12} {'High':<12}")
            print("-" * 80)

            for m in moonshots:
                print(f"{m['symbol']:<15} {m['date']:<12} {m['intraday_gain']:>+10.1f}% {m['daily_gain']:>+8.1f}% ${m['low']:<10.4f} ${m['high']:<10.4f}")

        # Summary by tier
        print(f"\n{'='*80}")
        print("SUMMARY BY GAIN TIER")
        print(f"{'='*80}")

        tiers = [
            (100, float('inf'), "100%+ (Mega Moonshot)"),
            (50, 100, "50-100% (Major Moonshot)"),
            (30, 50, "30-50% (Moonshot)"),
            (20, 30, "20-30% (Mini Moonshot)")
        ]

        for low, high, name in tiers:
            count = len([m for m in moonshots if low <= m['intraday_gain'] < high])
            if count > 0:
                print(f"  {name}: {count}")

        return moonshots

    finally:
        await client.close_connection()


if __name__ == "__main__":
    asyncio.run(analyze_moonshots(days=5, min_gain_percent=20))
