"""
Trailing Stop Optimization Analysis
Analyzes historical price data to find optimal trailing stop configuration
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
from binance import AsyncClient
from datetime import datetime


async def analyze_trailing_stop(symbol: str, entry_price: float, direction: str = 'SHORT', hours_back: int = 48):
    """
    Analyze price history to find optimal trailing stop configuration.

    Args:
        symbol: Trading pair (e.g., 'BEATUSDT')
        entry_price: Entry price of the position
        direction: 'LONG' or 'SHORT'
        hours_back: How many hours of history to analyze
    """
    client = await AsyncClient.create(
        os.getenv('BINANCE_API_KEY'),
        os.getenv('BINANCE_API_SECRET')
    )

    # Get klines
    klines = await client.futures_klines(
        symbol=symbol,
        interval='1m',
        limit=min(hours_back * 60, 1500)
    )

    print('=' * 90)
    print(f'{symbol} TRAILING STOP OPTIMIZATION ANALYSIS')
    print('=' * 90)
    print(f'Direction: {direction}')
    print(f'Entry Price: {entry_price}')
    print(f'Data Period: {hours_back} hours ({len(klines)} candles)')
    print()

    # Process prices
    prices = []
    for k in klines:
        ts = datetime.fromtimestamp(k[0] / 1000)
        prices.append({
            'time': ts,
            'open': float(k[1]),
            'high': float(k[2]),
            'low': float(k[3]),
            'close': float(k[4])
        })

    # Calculate profit at each point
    def calc_profit(price):
        if direction == 'SHORT':
            return ((entry_price - price) / entry_price) * 100
        else:
            return ((price - entry_price) / entry_price) * 100

    # Find peak profit
    peak_profit = 0
    peak_time = None
    peak_price = entry_price

    profit_timeline = []
    for p in prices:
        if direction == 'SHORT':
            best_price = p['low']
        else:
            best_price = p['high']

        profit = calc_profit(best_price)
        profit_timeline.append({
            'time': p['time'],
            'price': p['close'],
            'profit': calc_profit(p['close']),
            'best_profit': profit
        })

        if profit > peak_profit:
            peak_profit = profit
            peak_time = p['time']
            peak_price = best_price

    # Print key milestones
    print('KEY PROFIT MILESTONES:')
    print('-' * 90)
    last_milestone = -5
    for pt in profit_timeline:
        milestone = int(pt['best_profit'] / 5) * 5
        if milestone > last_milestone and pt['best_profit'] > 0:
            print(f"  {pt['time'].strftime('%m-%d %H:%M')} | Price: {pt['price']:.4f} | Profit: +{pt['best_profit']:.2f}%")
            last_milestone = milestone

    print()
    print('=' * 90)
    print('PEAK PERFORMANCE')
    print('=' * 90)
    print(f'Maximum Profit Reached: +{peak_profit:.2f}%')
    print(f'At Price: {peak_price:.4f}')
    print(f'At Time: {peak_time}')
    print()

    # Simulate different configurations
    configs = []
    for activation in [5, 10, 15, 20, 25, 30]:
        for trail in [3, 5, 7, 10, 12, 15]:
            configs.append((activation, trail))

    results = []
    for activation, trail in configs:
        peak = 0
        trailing_active = False
        exit_profit = None
        exit_time = None

        for pt in profit_timeline:
            profit = pt['profit']

            if profit > peak:
                peak = profit

            if not trailing_active and peak >= activation:
                trailing_active = True

            if trailing_active:
                trail_level = peak - trail
                if profit <= trail_level:
                    exit_profit = profit
                    exit_time = pt['time']
                    break

        if exit_profit is None:
            # Still holding
            exit_profit = profit_timeline[-1]['profit']
            status = 'HOLDING'
        else:
            status = 'EXITED'

        efficiency = (exit_profit / peak_profit * 100) if peak_profit > 0 else 0
        results.append({
            'activation': activation,
            'trail': trail,
            'exit_profit': exit_profit,
            'peak_reached': peak,
            'efficiency': efficiency,
            'status': status,
            'exit_time': exit_time
        })

    # Sort by exit profit
    results.sort(key=lambda x: x['exit_profit'], reverse=True)

    print('=' * 90)
    print('TRAILING STOP SIMULATION RESULTS')
    print('=' * 90)
    print()
    print(f"{'Config':<20} {'Exit Profit':<15} {'Peak':<12} {'Efficiency':<12} {'Status':<10}")
    print('-' * 90)

    # Top 10 configs
    print('TOP 10 CONFIGURATIONS:')
    for r in results[:10]:
        config = f"{r['activation']}% act / {r['trail']}% trail"
        print(f"  {config:<18} +{r['exit_profit']:>6.2f}%       +{r['peak_reached']:>5.2f}%      {r['efficiency']:>5.1f}%       {r['status']}")

    print()
    print('WORST 5 CONFIGURATIONS:')
    for r in results[-5:]:
        config = f"{r['activation']}% act / {r['trail']}% trail"
        print(f"  {config:<18} +{r['exit_profit']:>6.2f}%       +{r['peak_reached']:>5.2f}%      {r['efficiency']:>5.1f}%       {r['status']}")

    # Find optimal by efficiency (profit captured vs peak)
    best_by_efficiency = sorted(results, key=lambda x: x['efficiency'], reverse=True)

    print()
    print('=' * 90)
    print('RECOMMENDATIONS')
    print('=' * 90)

    best = results[0]
    print()
    print(f'HIGHEST PROFIT CONFIG:')
    print(f'  Activation: {best["activation"]}%')
    print(f'  Trail Distance: {best["trail"]}%')
    print(f'  Exit Profit: +{best["exit_profit"]:.2f}%')
    print(f'  Capture Efficiency: {best["efficiency"]:.1f}%')

    best_eff = best_by_efficiency[0]
    if best_eff != best:
        print()
        print(f'HIGHEST EFFICIENCY CONFIG:')
        print(f'  Activation: {best_eff["activation"]}%')
        print(f'  Trail Distance: {best_eff["trail"]}%')
        print(f'  Exit Profit: +{best_eff["exit_profit"]:.2f}%')
        print(f'  Capture Efficiency: {best_eff["efficiency"]:.1f}%')

    # Current config comparison
    current_activation = 15
    current_trail = 10
    current_result = next((r for r in results if r['activation'] == current_activation and r['trail'] == current_trail), None)

    if current_result:
        print()
        print(f'CURRENT CONFIG ({current_activation}% / {current_trail}%):')
        print(f'  Exit Profit: +{current_result["exit_profit"]:.2f}%')
        print(f'  Capture Efficiency: {current_result["efficiency"]:.1f}%')
        print()
        improvement = best["exit_profit"] - current_result["exit_profit"]
        print(f'POTENTIAL IMPROVEMENT: +{improvement:.2f}% more profit with optimal config')

    await client.close_connection()
    return results


async def main():
    # BEATUSDT analysis - entry was SHORT at 2.0613
    await analyze_trailing_stop(
        symbol='BEATUSDT',
        entry_price=2.0613,
        direction='SHORT',
        hours_back=24
    )


if __name__ == "__main__":
    asyncio.run(main())
