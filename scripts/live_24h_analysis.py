"""
Live 24h Moonshots and Moondrops Analysis from Binance Futures
"""
import asyncio
import aiohttp
from datetime import datetime, timedelta
import sys

async def fetch_24h_movers():
    base_url = 'https://fapi.binance.com'

    async with aiohttp.ClientSession() as session:
        # Get all perpetual futures symbols
        async with session.get(f'{base_url}/fapi/v1/exchangeInfo') as resp:
            data = await resp.json()

        symbols = [s['symbol'] for s in data['symbols']
                   if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']

        print(f'Scanning {len(symbols)} USDT perpetual pairs...')
        print('='*110)

        moonshots = []  # Big upward moves
        moondrops = []  # Big downward moves
        count = 0

        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(hours=24)).timestamp() * 1000)

        for symbol in symbols:
            try:
                params = {'symbol': symbol, 'interval': '1h', 'startTime': start_time, 'endTime': end_time, 'limit': 25}
                async with session.get(f'{base_url}/fapi/v1/klines', params=params) as resp:
                    klines = await resp.json()

                count += 1
                if count % 50 == 0:
                    print(f'Scanned {count}/{len(symbols)}...')

                if not klines or len(klines) < 12:
                    continue

                # Calculate 24h metrics
                high_24h = max(float(k[2]) for k in klines)
                low_24h = min(float(k[3]) for k in klines)
                open_24h = float(klines[0][1])
                close_24h = float(klines[-1][4])
                total_vol = sum(float(k[5]) * float(k[4]) for k in klines)  # Volume in USDT

                if low_24h <= 0 or open_24h <= 0:
                    continue

                # Range and net change
                range_pct = ((high_24h - low_24h) / low_24h) * 100
                net_change = ((close_24h - open_24h) / open_24h) * 100

                # From low to high (pump potential)
                pump_from_low = ((high_24h - low_24h) / low_24h) * 100
                # From high to low (drop magnitude)
                drop_from_high = ((high_24h - low_24h) / high_24h) * 100

                # Find the biggest single hour candle move
                max_hour_pump = 0
                max_hour_drop = 0
                for k in klines:
                    o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
                    if o > 0:
                        hour_change = ((c - o) / o) * 100
                        if hour_change > max_hour_pump:
                            max_hour_pump = hour_change
                        if hour_change < max_hour_drop:
                            max_hour_drop = hour_change

                move_data = {
                    'symbol': symbol,
                    'range_pct': range_pct,
                    'net_change': net_change,
                    'open': open_24h,
                    'high': high_24h,
                    'low': low_24h,
                    'close': close_24h,
                    'volume_usdt': total_vol,
                    'max_hour_pump': max_hour_pump,
                    'max_hour_drop': max_hour_drop,
                    'pump_from_low': pump_from_low,
                    'drop_from_high': drop_from_high
                }

                # Classify: if net positive with big range = moonshot, if net negative with big range = moondrop
                if range_pct >= 5:  # At least 5% range
                    if net_change > 0:
                        moonshots.append(move_data)
                    else:
                        moondrops.append(move_data)

                await asyncio.sleep(0.015)

            except Exception as e:
                continue

        # Sort by absolute net change
        moonshots.sort(key=lambda x: x['net_change'], reverse=True)
        moondrops.sort(key=lambda x: x['net_change'])  # Most negative first

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        print(f'\n' + '='*110)
        print(f'                    BINANCE FUTURES - LAST 24 HOURS ANALYSIS')
        print(f'                         Generated: {now}')
        print('='*110)

        # MOONSHOTS Section
        print(f'\n' + '='*110)
        print('                         MOONSHOTS (Pumps - Net Positive)')
        print('='*110)
        print(f'Total moonshots (>=5% range, net positive): {len(moonshots)}')
        print('-'*110)
        hdr = f"{'Symbol':<16} {'Net Change':<12} {'24h Range':<12} {'Low':<14} {'High':<14} {'Max 1h Pump':<12} {'Volume (USDT)':<18}"
        print(hdr)
        print('-'*110)

        for m in moonshots[:30]:  # Top 30
            line = f"{m['symbol']:<16} {m['net_change']:>+10.2f}% {m['range_pct']:>10.2f}% ${m['low']:<12.6g} ${m['high']:<12.6g} {m['max_hour_pump']:>+10.2f}% ${m['volume_usdt']:>14,.0f}"
            print(line)

        # MOONDROPS Section
        print(f'\n' + '='*110)
        print('                         MOONDROPS (Dumps - Net Negative)')
        print('='*110)
        print(f'Total moondrops (>=5% range, net negative): {len(moondrops)}')
        print('-'*110)
        hdr2 = f"{'Symbol':<16} {'Net Change':<12} {'24h Range':<12} {'High':<14} {'Low':<14} {'Max 1h Drop':<12} {'Volume (USDT)':<18}"
        print(hdr2)
        print('-'*110)

        for m in moondrops[:30]:  # Top 30
            line = f"{m['symbol']:<16} {m['net_change']:>+10.2f}% {m['range_pct']:>10.2f}% ${m['high']:<12.6g} ${m['low']:<12.6g} {m['max_hour_drop']:>+10.2f}% ${m['volume_usdt']:>14,.0f}"
            print(line)

        # Summary by tier
        print(f'\n' + '='*110)
        print('                              SUMMARY BY TIER')
        print('='*110)

        tiers = [
            (50, float('inf'), 'MEGA (50%+)'),
            (30, 50, 'MAJOR (30-50%)'),
            (20, 30, 'STRONG (20-30%)'),
            (10, 20, 'MODERATE (10-20%)'),
            (5, 10, 'NOTABLE (5-10%)')
        ]

        tier_hdr = f"{'Tier':<20} {'Moonshots':<15} {'Moondrops':<15} {'Total':<10}"
        print(tier_hdr)
        print('-'*60)

        for low, high, name in tiers:
            shots = len([m for m in moonshots if low <= m['net_change'] < high])
            drops = len([m for m in moondrops if low <= abs(m['net_change']) < high])
            print(f'{name:<20} {shots:<15} {drops:<15} {shots+drops:<10}')

        # Biggest movers overall
        print(f'\n' + '='*110)
        print('                         TOP 10 BIGGEST ABSOLUTE MOVES')
        print('='*110)
        all_moves = moonshots + moondrops
        all_moves.sort(key=lambda x: abs(x['net_change']), reverse=True)

        top_hdr = f"{'Symbol':<16} {'Net Change':<12} {'Direction':<12} {'24h Range':<12} {'Volume (USDT)':<18}"
        print(top_hdr)
        print('-'*80)

        for m in all_moves[:10]:
            direction = 'PUMP' if m['net_change'] > 0 else 'DUMP'
            print(f"{m['symbol']:<16} {m['net_change']:>+10.2f}% {direction:<12} {m['range_pct']:>10.2f}% ${m['volume_usdt']:>14,.0f}")

        print(f'\n' + '='*110)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(fetch_24h_movers())
