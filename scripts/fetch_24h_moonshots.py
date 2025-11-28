"""
Fetch all moonshots from Binance Futures in the last 24 hours
"""
import asyncio
from binance import AsyncClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')

async def analyze_24h_moonshots():
    """Find all pairs with significant moves (>=10%) in the last 24 hours"""

    client = await AsyncClient.create(BINANCE_API_KEY, BINANCE_API_SECRET)

    try:
        # Get all futures symbols
        exchange_info = await client.futures_exchange_info()
        symbols = []
        for s in exchange_info['symbols']:
            if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] in ['USDT', 'USDC'] and s['status'] == 'TRADING':
                symbols.append(s['symbol'])

        print(f'Analyzing {len(symbols)} perpetual futures pairs for last 24 hours...')
        print(f'Looking for moves >= 10% (intraday high-low range)\n')

        moonshots = []

        for i, symbol in enumerate(symbols):
            try:
                # Get hourly klines for the last 24 hours
                klines = await client.futures_klines(
                    symbol=symbol,
                    interval='1h',
                    limit=25
                )

                if len(klines) < 24:
                    continue

                # Get the last 24 candles
                last_24h = klines[-24:]

                # Find high and low of last 24 hours
                high_24h = max(float(k[2]) for k in last_24h)
                low_24h = min(float(k[3]) for k in last_24h)
                open_24h = float(last_24h[0][1])
                close_24h = float(last_24h[-1][4])
                total_volume = sum(float(k[5]) for k in last_24h)

                # Calculate range percent
                if low_24h > 0:
                    range_percent = ((high_24h - low_24h) / low_24h) * 100
                else:
                    range_percent = 0

                # Calculate direction (uptrend or downtrend)
                if open_24h > 0:
                    net_change = ((close_24h - open_24h) / open_24h) * 100
                else:
                    net_change = 0

                # Look for 10%+ range
                if range_percent >= 10:
                    direction = 'UPTREND' if net_change > 0 else 'DOWNTREND'

                    moonshots.append({
                        'symbol': symbol,
                        'range_percent': range_percent,
                        'net_change': net_change,
                        'direction': direction,
                        'low_24h': low_24h,
                        'high_24h': high_24h,
                        'open_24h': open_24h,
                        'close_24h': close_24h,
                        'volume_usdt': total_volume * close_24h
                    })

                if (i + 1) % 100 == 0:
                    print(f'Processed {i + 1}/{len(symbols)} pairs...')

            except Exception as e:
                continue

        # Sort by range (biggest moves first)
        moonshots.sort(key=lambda x: x['range_percent'], reverse=True)

        print(f'\n{"="*100}')
        print(f'MOONSHOT REPORT - LAST 24 HOURS (as of {datetime.now().strftime("%Y-%m-%d %H:%M:%S")})')
        print(f'{"="*100}')
        print(f'\nTotal moonshots found (>=10% range): {len(moonshots)}\n')

        # Separate uptrends and downtrends
        uptrends = [m for m in moonshots if m['direction'] == 'UPTREND']
        downtrends = [m for m in moonshots if m['direction'] == 'DOWNTREND']

        print(f'UPTRENDS: {len(uptrends)} | DOWNTRENDS: {len(downtrends)}\n')

        print(f'{"="*100}')
        print('>>> UPTREND MOONSHOTS (Pumps) <<<')
        print(f'{"="*100}')
        print(f'{"Symbol":<18} {"Range%":<12} {"Net Change%":<14} {"Low":<14} {"High":<14} {"Volume (USDT)":<18}')
        print('-' * 100)

        for m in uptrends:
            print(f'{m["symbol"]:<18} {m["range_percent"]:>+10.2f}% {m["net_change"]:>+12.2f}% ${m["low_24h"]:<12.6f} ${m["high_24h"]:<12.6f} ${m["volume_usdt"]:>14,.0f}')

        print(f'\n{"="*100}')
        print('>>> DOWNTREND MOONSHOTS (Dumps) <<<')
        print(f'{"="*100}')
        print(f'{"Symbol":<18} {"Range%":<12} {"Net Change%":<14} {"Low":<14} {"High":<14} {"Volume (USDT)":<18}')
        print('-' * 100)

        for m in downtrends:
            print(f'{m["symbol"]:<18} {m["range_percent"]:>+10.2f}% {m["net_change"]:>+12.2f}% ${m["low_24h"]:<12.6f} ${m["high_24h"]:<12.6f} ${m["volume_usdt"]:>14,.0f}')

        # Summary by tier
        print(f'\n{"="*100}')
        print('SUMMARY BY GAIN TIER')
        print(f'{"="*100}')

        tiers = [
            (50, float('inf'), '50%+ (MEGA MOONSHOT)'),
            (30, 50, '30-50% (MAJOR MOONSHOT)'),
            (20, 30, '20-30% (MOONSHOT)'),
            (15, 20, '15-20% (SIGNIFICANT)'),
            (10, 15, '10-15% (NOTABLE)')
        ]

        for low, high, name in tiers:
            tier_moves = [m for m in moonshots if low <= m['range_percent'] < high]
            up = len([m for m in tier_moves if m['direction'] == 'UPTREND'])
            down = len([m for m in tier_moves if m['direction'] == 'DOWNTREND'])
            if up + down > 0:
                print(f'  {name}: {up + down} total ({up} up, {down} down)')

        return moonshots

    finally:
        await client.close_connection()

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(analyze_24h_moonshots())
