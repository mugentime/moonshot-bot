"""
Analyze top moonshots and moondrops to find optimal trailing stop
"""
import asyncio
import aiohttp
from datetime import datetime, timedelta
import sys
import json

async def analyze_top_movers():
    base_url = 'https://fapi.binance.com'

    async with aiohttp.ClientSession() as session:
        async with session.get(f'{base_url}/fapi/v1/exchangeInfo') as resp:
            data = await resp.json()

        symbols = [s['symbol'] for s in data['symbols']
                   if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']

        print(f'Analyzing {len(symbols)} pairs for last 48 hours...')

        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(hours=48)).timestamp() * 1000)

        all_moves = []
        count = 0

        for symbol in symbols:
            try:
                params = {'symbol': symbol, 'interval': '5m', 'startTime': start_time, 'endTime': end_time, 'limit': 576}
                async with session.get(f'{base_url}/fapi/v1/klines', params=params) as resp:
                    klines = await resp.json()

                count += 1
                if count % 100 == 0:
                    print(f'Processed {count}/{len(symbols)}...')

                if not klines or len(klines) < 50:
                    continue

                # Find biggest pump and dump for this symbol using sliding window
                for i in range(24, len(klines)):
                    window = klines[i-24:i+1]  # 2-hour window (24 x 5min)

                    window_high = max(float(k[2]) for k in window)
                    window_low = min(float(k[3]) for k in window)
                    window_open = float(window[0][1])
                    window_close = float(window[-1][4])

                    if window_low <= 0:
                        continue

                    net_change = ((window_close - window_open) / window_open) * 100

                    if abs(net_change) >= 8:
                        ts = window[-1][0]
                        prices = [float(k[4]) for k in window]
                        highs = [float(k[2]) for k in window]
                        lows = [float(k[3]) for k in window]

                        peak_price = max(highs)
                        trough_price = min(lows)
                        peak_idx = highs.index(peak_price)
                        trough_idx = lows.index(trough_price)

                        if net_change > 0:  # PUMP
                            entry_price = trough_price
                            optimal_gain = ((peak_price - entry_price) / entry_price) * 100

                            # Drawdown after peak
                            post_peak_lows = lows[peak_idx:] if peak_idx < len(lows) else [trough_price]
                            lowest_after = min(post_peak_lows) if post_peak_lows else trough_price
                            drawdown_from_peak = ((peak_price - lowest_after) / peak_price) * 100
                            move_type = 'MOONSHOT'
                        else:  # DUMP
                            entry_price = peak_price
                            optimal_gain = ((entry_price - trough_price) / entry_price) * 100

                            # Bounce after trough
                            post_trough_highs = highs[trough_idx:] if trough_idx < len(highs) else [peak_price]
                            highest_after = max(post_trough_highs) if post_trough_highs else peak_price
                            drawdown_from_peak = ((highest_after - trough_price) / trough_price) * 100
                            move_type = 'MOONDROP'

                        all_moves.append({
                            'symbol': symbol,
                            'type': move_type,
                            'net_change': net_change,
                            'optimal_gain': optimal_gain,
                            'drawdown_after': drawdown_from_peak,
                            'timestamp': ts,
                            'entry': entry_price,
                            'peak': peak_price if move_type == 'MOONSHOT' else trough_price
                        })

                await asyncio.sleep(0.02)
            except Exception as e:
                continue

        # Deduplicate - keep only the biggest move per symbol per type
        best_moves = {}
        for m in all_moves:
            key = f"{m['symbol']}_{m['type']}"
            if key not in best_moves or abs(m['net_change']) > abs(best_moves[key]['net_change']):
                best_moves[key] = m

        moves = list(best_moves.values())

        moonshots = sorted([m for m in moves if m['type'] == 'MOONSHOT'], key=lambda x: x['net_change'], reverse=True)[:15]
        moondrops = sorted([m for m in moves if m['type'] == 'MOONDROP'], key=lambda x: x['net_change'])[:15]

        print(f'\n' + '='*100)
        print('TOP 15 MOONSHOTS (PUMPS) - Last 48h')
        print('='*100)
        print(f"{'Symbol':<16} {'Net Change':<12} {'Optimal Gain':<14} {'Drawdown After':<16} {'Time'}")
        print('-'*100)

        for m in moonshots:
            ts = datetime.fromtimestamp(m['timestamp']/1000).strftime('%Y-%m-%d %H:%M')
            print(f"{m['symbol']:<16} {m['net_change']:>+10.2f}% {m['optimal_gain']:>12.2f}% {m['drawdown_after']:>14.2f}% {ts}")

        print(f'\n' + '='*100)
        print('TOP 15 MOONDROPS (DUMPS) - Last 48h')
        print('='*100)
        print(f"{'Symbol':<16} {'Net Change':<12} {'Optimal Gain':<14} {'Bounce After':<16} {'Time'}")
        print('-'*100)

        for m in moondrops:
            ts = datetime.fromtimestamp(m['timestamp']/1000).strftime('%Y-%m-%d %H:%M')
            print(f"{m['symbol']:<16} {m['net_change']:>+10.2f}% {m['optimal_gain']:>12.2f}% {m['drawdown_after']:>14.2f}% {ts}")

        # Trailing stop analysis
        print(f'\n' + '='*100)
        print('TRAILING STOP OPTIMIZATION ANALYSIS')
        print('='*100)

        all_top = moonshots + moondrops

        # Simulate different trailing stop percentages
        print(f'\nSimulating trailing stop capture for top 30 moves:')
        print('-'*80)

        trailing_results = {}
        for trail_pct in [2, 3, 4, 5, 6, 7, 8, 10, 12, 15]:
            total_captured = 0
            for m in all_top:
                # If trailing stop is X%, we capture (optimal_gain - X%) assuming we entered at perfect time
                # But we also need to consider if the drawdown after peak exceeds our trailing
                if m['drawdown_after'] >= trail_pct:
                    # Trailing stop would trigger, we capture optimal - trail
                    captured = max(0, m['optimal_gain'] - trail_pct)
                else:
                    # Price never pulled back enough to trigger trailing, we'd still be in
                    # Assume we exit at close which is net_change from entry
                    captured = abs(m['net_change'])
                total_captured += captured

            avg_captured = total_captured / len(all_top)
            trailing_results[trail_pct] = avg_captured
            print(f"  {trail_pct}% trailing stop: Avg captured = {avg_captured:.2f}%")

        best_trail = max(trailing_results, key=trailing_results.get)
        print(f'\nOPTIMAL TRAILING STOP: {best_trail}% (captures avg {trailing_results[best_trail]:.2f}%)')

        # More detailed analysis
        print(f'\n' + '='*100)
        print('DETAILED STATISTICS')
        print('='*100)

        ms_gains = [m['optimal_gain'] for m in moonshots]
        md_gains = [m['optimal_gain'] for m in moondrops]
        ms_dd = [m['drawdown_after'] for m in moonshots]
        md_dd = [m['drawdown_after'] for m in moondrops]

        print(f'\nMOONSHOTS (Pumps):')
        print(f'  Optimal gains: min={min(ms_gains):.1f}% avg={sum(ms_gains)/len(ms_gains):.1f}% max={max(ms_gains):.1f}%')
        print(f'  Drawdown after: min={min(ms_dd):.1f}% avg={sum(ms_dd)/len(ms_dd):.1f}% max={max(ms_dd):.1f}%')

        print(f'\nMOONDROPS (Dumps):')
        print(f'  Optimal gains: min={min(md_gains):.1f}% avg={sum(md_gains)/len(md_gains):.1f}% max={max(md_gains):.1f}%')
        print(f'  Bounce after: min={min(md_dd):.1f}% avg={sum(md_dd)/len(md_dd):.1f}% max={max(md_dd):.1f}%')

        # Recommendation
        print(f'\n' + '='*100)
        print('RECOMMENDATIONS')
        print('='*100)
        print(f'''
Based on analysis of top 30 moves (15 moonshots + 15 moondrops):

1. TRAILING STOP: {best_trail}%
   - Captures maximum profit on average
   - Tight enough to lock gains, loose enough to ride moves

2. ENTRY: Detect velocity spike early
   - Moonshots avg {sum(ms_gains)/len(ms_gains):.1f}% potential gain
   - Moondrops avg {sum(md_gains)/len(md_gains):.1f}% potential gain

3. STOP-LOSS: Based on avg drawdown
   - Moonshots pull back avg {sum(ms_dd)/len(ms_dd):.1f}% from peak
   - Moondrops bounce avg {sum(md_dd)/len(md_dd):.1f}% from bottom
''')

        # Save data
        with open('top_moves_analysis.json', 'w') as f:
            json.dump({'moonshots': moonshots, 'moondrops': moondrops, 'trailing_results': trailing_results}, f, indent=2)
        print('Data saved to top_moves_analysis.json')

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(analyze_top_movers())
