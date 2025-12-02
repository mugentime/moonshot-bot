import asyncio
import aiohttp
from datetime import datetime, timedelta
import json

async def analyze_all_moondrops():
    base_url = 'https://fapi.binance.com'

    async with aiohttp.ClientSession() as session:
        async with session.get(f'{base_url}/fapi/v1/exchangeInfo') as resp:
            data = await resp.json()

        symbols = [s['symbol'] for s in data['symbols']
                   if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT']

        print(f'Scanning {len(symbols)} pairs for comprehensive analysis...')

        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(hours=48)).timestamp() * 1000)

        all_moondrops = []
        count = 0

        for symbol in symbols:
            try:
                params = {'symbol': symbol, 'interval': '5m', 'startTime': start_time, 'endTime': end_time, 'limit': 576}
                async with session.get(f'{base_url}/fapi/v1/klines', params=params) as resp:
                    klines = await resp.json()

                count += 1
                if count % 100 == 0:
                    print(f'Scanned {count}/{len(symbols)}...')

                if not klines or len(klines) < 15:
                    continue

                for i in range(12, len(klines)):
                    kline = klines[i]
                    o, h, l, c = float(kline[1]), float(kline[2]), float(kline[3]), float(kline[4])
                    vol = float(kline[5])
                    ts = kline[0]

                    if h <= 0 or o <= 0:
                        continue

                    wick_drop = ((h - l) / h) * 100
                    body_drop = ((o - c) / o) * 100 if c < o else 0

                    # Only significant drops (moondrops)
                    if wick_drop < 2 and body_drop < 1.5:
                        continue

                    # Calculate pre-drop indicators
                    prev_candles = klines[i-12:i]
                    prev_volumes = [float(k[5]) * float(k[4]) for k in prev_candles]
                    avg_vol = sum(prev_volumes) / len(prev_volumes) if prev_volumes else 1
                    curr_vol = vol * c
                    vol_spike = curr_vol / avg_vol if avg_vol > 0 else 1

                    prev_lows = [float(k[3]) for k in prev_candles]
                    min_low = min(prev_lows) if prev_lows else l
                    pre_pump = ((h - min_low) / min_low) * 100 if min_low > 0 else 0

                    # RSI approximation
                    gains = []
                    losses = []
                    for j in range(1, len(prev_candles)):
                        change = float(prev_candles[j][4]) - float(prev_candles[j-1][4])
                        if change > 0:
                            gains.append(change)
                        else:
                            losses.append(abs(change))
                    avg_gain = sum(gains) / len(gains) if gains else 0.0001
                    avg_loss = sum(losses) / len(losses) if losses else 0.0001
                    rs = avg_gain / avg_loss if avg_loss > 0 else 1
                    rsi_approx = 100 - (100 / (1 + rs))

                    # Upper wick analysis
                    upper_wick = h - max(o, c)
                    upper_wick_pct = (upper_wick / h) * 100 if h > 0 else 0

                    # Range expansion
                    prev_ranges = [(float(k[2]) - float(k[3])) / float(k[2]) * 100 for k in prev_candles if float(k[2]) > 0]
                    avg_range = sum(prev_ranges) / len(prev_ranges) if prev_ranges else 1
                    range_expansion = wick_drop / avg_range if avg_range > 0 else 1

                    # Velocity calculations
                    velocity_1m = 0
                    if i >= 1:
                        prev_c = float(klines[i-1][4])
                        if prev_c > 0:
                            velocity_1m = ((c - prev_c) / prev_c) * 100

                    velocity_5m = ((c - o) / o) * 100 if o > 0 else 0

                    all_moondrops.append({
                        'sym': symbol,
                        'ts': ts,
                        'wick_drop': wick_drop,
                        'body_drop': body_drop,
                        'vol_spike': vol_spike,
                        'pre_pump': pre_pump,
                        'rsi': rsi_approx,
                        'upper_wick_pct': upper_wick_pct,
                        'range_expansion': range_expansion,
                        'vol_usd': curr_vol,
                        'velocity_1m': velocity_1m,
                        'velocity_5m': velocity_5m
                    })

                await asyncio.sleep(0.025)
            except Exception as e:
                continue

        all_moondrops.sort(key=lambda x: x['wick_drop'], reverse=True)

        with open('moondrop_analysis.json', 'w') as f:
            json.dump(all_moondrops, f)

        print(f'\nTotal moondrops collected: {len(all_moondrops)}')
        print('Data saved to moondrop_analysis.json')

        if all_moondrops:
            drops = [m['wick_drop'] for m in all_moondrops]
            vol_spikes = [m['vol_spike'] for m in all_moondrops]
            pre_pumps = [m['pre_pump'] for m in all_moondrops]
            rsis = [m['rsi'] for m in all_moondrops]
            upper_wicks = [m['upper_wick_pct'] for m in all_moondrops]
            range_exps = [m['range_expansion'] for m in all_moondrops]
            vel_1m = [abs(m['velocity_1m']) for m in all_moondrops]
            vel_5m = [abs(m['velocity_5m']) for m in all_moondrops]
            body_drops = [m['body_drop'] for m in all_moondrops]

            def pct(data, p):
                s = sorted(data)
                return s[min(int(len(s) * p / 100), len(s)-1)]

            print('\n' + '='*80)
            print('STATISTICAL ANALYSIS OF ALL MOONDROPS (for 80% capture rate)')
            print('='*80)

            print(f'\nDROP SIZE (wick high-to-low):')
            print(f'  min={min(drops):.2f}% p10={pct(drops,10):.2f}% p20={pct(drops,20):.2f}% p25={pct(drops,25):.2f}%')
            print(f'  p50={pct(drops,50):.2f}% p75={pct(drops,75):.2f}% p90={pct(drops,90):.2f}% max={max(drops):.2f}%')

            print(f'\nBODY DROP (open-to-close bearish):')
            print(f'  min={min(body_drops):.2f}% p10={pct(body_drops,10):.2f}% p20={pct(body_drops,20):.2f}% p25={pct(body_drops,25):.2f}%')
            print(f'  p50={pct(body_drops,50):.2f}% p75={pct(body_drops,75):.2f}% p90={pct(body_drops,90):.2f}% max={max(body_drops):.2f}%')

            print(f'\nVOLUME SPIKE (vs 1h avg):')
            print(f'  min={min(vol_spikes):.2f}x p10={pct(vol_spikes,10):.2f}x p20={pct(vol_spikes,20):.2f}x p25={pct(vol_spikes,25):.2f}x')
            print(f'  p50={pct(vol_spikes,50):.2f}x p75={pct(vol_spikes,75):.2f}x p90={pct(vol_spikes,90):.2f}x max={max(vol_spikes):.2f}x')

            print(f'\nPRE-DROP PUMP (run-up before drop):')
            print(f'  min={min(pre_pumps):.2f}% p10={pct(pre_pumps,10):.2f}% p20={pct(pre_pumps,20):.2f}% p25={pct(pre_pumps,25):.2f}%')
            print(f'  p50={pct(pre_pumps,50):.2f}% p75={pct(pre_pumps,75):.2f}% p90={pct(pre_pumps,90):.2f}% max={max(pre_pumps):.2f}%')

            print(f'\nRSI BEFORE DROP:')
            print(f'  min={min(rsis):.1f} p10={pct(rsis,10):.1f} p20={pct(rsis,20):.1f} p25={pct(rsis,25):.1f}')
            print(f'  p50={pct(rsis,50):.1f} p75={pct(rsis,75):.1f} p90={pct(rsis,90):.1f} max={max(rsis):.1f}')

            print(f'\nUPPER WICK % (rejection signal):')
            print(f'  min={min(upper_wicks):.2f}% p10={pct(upper_wicks,10):.2f}% p20={pct(upper_wicks,20):.2f}% p25={pct(upper_wicks,25):.2f}%')
            print(f'  p50={pct(upper_wicks,50):.2f}% p75={pct(upper_wicks,75):.2f}% p90={pct(upper_wicks,90):.2f}% max={max(upper_wicks):.2f}%')

            print(f'\nRANGE EXPANSION (vs avg range):')
            print(f'  min={min(range_exps):.2f}x p10={pct(range_exps,10):.2f}x p20={pct(range_exps,20):.2f}x p25={pct(range_exps,25):.2f}x')
            print(f'  p50={pct(range_exps,50):.2f}x p75={pct(range_exps,75):.2f}x p90={pct(range_exps,90):.2f}x max={max(range_exps):.2f}x')

            print(f'\nVELOCITY 5m (absolute):')
            print(f'  min={min(vel_5m):.2f}% p10={pct(vel_5m,10):.2f}% p20={pct(vel_5m,20):.2f}% p25={pct(vel_5m,25):.2f}%')
            print(f'  p50={pct(vel_5m,50):.2f}% p75={pct(vel_5m,75):.2f}% p90={pct(vel_5m,90):.2f}% max={max(vel_5m):.2f}%')

            # Calculate thresholds to catch 80% of moondrops
            print('\n' + '='*80)
            print('THRESHOLDS TO CATCH 80% OF MOONDROPS')
            print('='*80)

            # To catch 80%, we need to set thresholds at the 20th percentile
            print(f'\nTo catch 80% of moondrops, use these MINIMUM thresholds:')
            print(f'  - Wick Drop >= {pct(drops, 20):.2f}%')
            print(f'  - Body Drop >= {pct(body_drops, 20):.2f}%')
            print(f'  - Volume Spike >= {pct(vol_spikes, 20):.2f}x')
            print(f'  - Pre-Pump >= {pct(pre_pumps, 20):.2f}%')
            print(f'  - Range Expansion >= {pct(range_exps, 20):.2f}x')
            print(f'  - Velocity 5m >= {pct(vel_5m, 20):.2f}%')

            # Test different condition combinations
            print('\n' + '='*80)
            print('CONDITION COMBINATION TESTING')
            print('='*80)

            # Test various entry condition combinations
            test_conditions = [
                ('wick_drop >= 2.0', lambda m: m['wick_drop'] >= 2.0),
                ('wick_drop >= 2.5', lambda m: m['wick_drop'] >= 2.5),
                ('wick_drop >= 3.0', lambda m: m['wick_drop'] >= 3.0),
                ('body_drop >= 1.0', lambda m: m['body_drop'] >= 1.0),
                ('body_drop >= 1.5', lambda m: m['body_drop'] >= 1.5),
                ('vol_spike >= 1.5', lambda m: m['vol_spike'] >= 1.5),
                ('vol_spike >= 2.0', lambda m: m['vol_spike'] >= 2.0),
                ('velocity_5m <= -1.0', lambda m: m['velocity_5m'] <= -1.0),
                ('velocity_5m <= -1.5', lambda m: m['velocity_5m'] <= -1.5),
                ('range_exp >= 1.5', lambda m: m['range_expansion'] >= 1.5),
                ('range_exp >= 2.0', lambda m: m['range_expansion'] >= 2.0),
                ('upper_wick >= 0.5', lambda m: m['upper_wick_pct'] >= 0.5),
            ]

            print('\nSingle Condition Capture Rates:')
            for name, cond in test_conditions:
                caught = sum(1 for m in all_moondrops if cond(m))
                rate = (caught / len(all_moondrops)) * 100
                print(f'  {name}: {caught}/{len(all_moondrops)} = {rate:.1f}%')

            # Combined conditions for 80% capture
            print('\nCombined Conditions (OR logic) for 80%+ capture:')

            def test_combo(conditions, all_data):
                caught = sum(1 for m in all_data if any(c(m) for c in conditions))
                return caught, (caught / len(all_data)) * 100

            # Combo 1: Low thresholds
            combo1 = [
                lambda m: m['wick_drop'] >= 2.5,
                lambda m: m['body_drop'] >= 1.0 and m['vol_spike'] >= 1.3,
                lambda m: m['velocity_5m'] <= -1.0,
            ]
            c1, r1 = test_combo(combo1, all_moondrops)
            print(f'  Combo1 (wick>=2.5 OR (body>=1.0 AND vol>=1.3) OR vel<=-1.0): {r1:.1f}%')

            # Combo 2
            combo2 = [
                lambda m: m['wick_drop'] >= 2.0,
                lambda m: m['body_drop'] >= 0.8 and m['range_expansion'] >= 1.3,
            ]
            c2, r2 = test_combo(combo2, all_moondrops)
            print(f'  Combo2 (wick>=2.0 OR (body>=0.8 AND range>=1.3)): {r2:.1f}%')

            # Combo 3 - aggressive
            combo3 = [
                lambda m: m['wick_drop'] >= 2.0,
                lambda m: m['velocity_5m'] <= -0.8,
                lambda m: m['body_drop'] >= 0.5 and m['vol_spike'] >= 1.2,
            ]
            c3, r3 = test_combo(combo3, all_moondrops)
            print(f'  Combo3 (wick>=2.0 OR vel<=-0.8 OR (body>=0.5 AND vol>=1.2)): {r3:.1f}%')

if __name__ == '__main__':
    asyncio.run(analyze_all_moondrops())
