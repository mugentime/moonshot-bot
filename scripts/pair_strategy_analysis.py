"""
Analyze best asset pairs for:
1. Interest rate differential (carry trade)
2. Volatility harvesting through rebalancing
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)

from binance import AsyncClient
import math
import sys
import io

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

async def main():
    client = await AsyncClient.create(
        os.getenv('BINANCE_API_KEY'),
        os.getenv('BINANCE_API_SECRET')
    )

    try:
        print('=' * 70)
        print('50/50 REBALANCING STRATEGY ANALYSIS')
        print('Interest Differential + Volatility Harvesting')
        print('=' * 70)

        # Get funding rates
        premiums = await client.futures_mark_price()
        funding_map = {}
        for p in premiums:
            if 'lastFundingRate' in p and p['lastFundingRate']:
                funding_map[p['symbol']] = float(p['lastFundingRate'])

        # Get 24h volatility and volume
        tickers = await client.futures_ticker()
        asset_data = {}

        for t in tickers:
            symbol = t['symbol']
            if not symbol.endswith('USDT'):
                continue

            volume = float(t.get('quoteVolume', 0))
            if volume < 10_000_000:  # Min $10M volume
                continue

            high = float(t.get('highPrice', 0))
            low = float(t.get('lowPrice', 0))
            price = float(t.get('lastPrice', 0))

            if low > 0 and price > 0:
                # Daily range as % of price (volatility proxy)
                daily_range = ((high - low) / price) * 100
                price_change = float(t.get('priceChangePercent', 0))

                asset_data[symbol] = {
                    'symbol': symbol,
                    'volume': volume,
                    'volatility': daily_range,
                    'price_change': price_change,
                    'funding': funding_map.get(symbol, 0),
                    'funding_apr': funding_map.get(symbol, 0) * 3 * 365 * 100,
                    'price': price
                }

        # Find best pairs for the strategy
        print('\n' + '=' * 70)
        print('STRATEGY 1: INTEREST RATE DIFFERENTIAL (Carry Trade)')
        print('=' * 70)
        print('Long asset with NEGATIVE funding, Short asset with POSITIVE funding')
        print('You earn the spread between the two funding rates\n')

        # Find pairs with biggest funding differential
        symbols = list(asset_data.keys())
        pairs = []

        for i, sym1 in enumerate(symbols):
            for sym2 in symbols[i+1:]:
                d1 = asset_data[sym1]
                d2 = asset_data[sym2]

                # Calculate funding differential
                funding_diff = abs(d1['funding'] - d2['funding'])
                funding_diff_apr = funding_diff * 3 * 365 * 100

                # Average volatility (for rebalancing profit)
                avg_vol = (d1['volatility'] + d2['volatility']) / 2

                # Correlation proxy (if both move same direction, lower rebal profit)
                # Different direction = higher rebalancing profit potential
                direction_diff = abs(d1['price_change'] - d2['price_change'])

                # Combined score
                min_volume = min(d1['volume'], d2['volume'])

                pairs.append({
                    'asset_a': sym1,
                    'asset_b': sym2,
                    'funding_a': d1['funding'],
                    'funding_b': d2['funding'],
                    'funding_diff_apr': funding_diff_apr,
                    'vol_a': d1['volatility'],
                    'vol_b': d2['volatility'],
                    'avg_volatility': avg_vol,
                    'direction_diff': direction_diff,
                    'min_volume': min_volume,
                    'rebal_score': avg_vol * (1 + direction_diff/10)  # Higher = better for rebalancing
                })

        # Sort by funding differential
        pairs.sort(key=lambda x: x['funding_diff_apr'], reverse=True)

        print('TOP 10 BY FUNDING DIFFERENTIAL:')
        print('-' * 70)
        for p in pairs[:10]:
            long_asset = p['asset_a'] if asset_data[p['asset_a']]['funding'] < asset_data[p['asset_b']]['funding'] else p['asset_b']
            short_asset = p['asset_b'] if long_asset == p['asset_a'] else p['asset_a']

            print(f"LONG {long_asset:12} / SHORT {short_asset:12}")
            print(f"   Funding Diff APR: {p['funding_diff_apr']:+.1f}%")
            print(f"   Avg Volatility: {p['avg_volatility']:.1f}%")
            print()

        print('\n' + '=' * 70)
        print('STRATEGY 2: VOLATILITY HARVESTING (Rebalancing Profit)')
        print('=' * 70)
        print('High volatility + low correlation = more rebalancing profits')
        print('Each rebalance captures the mean reversion\n')

        # Sort by rebalancing score
        pairs.sort(key=lambda x: x['rebal_score'], reverse=True)

        print('TOP 10 BY REBALANCING POTENTIAL:')
        print('-' * 70)
        for p in pairs[:10]:
            # Estimate annual rebalancing profit
            # Rough formula: volatility^2 / 4 (for daily rebalancing)
            # With 50/50 split and mean reversion
            daily_rebal_profit = (p['avg_volatility'] ** 2) / 400  # Simplified model
            annual_rebal_profit = daily_rebal_profit * 365

            print(f"{p['asset_a']:15} / {p['asset_b']:15}")
            print(f"   Avg Daily Range: {p['avg_volatility']:.1f}%")
            print(f"   Direction Divergence: {p['direction_diff']:.1f}%")
            print(f"   Est. Rebal Profit/Year: ~{annual_rebal_profit:.1f}%")
            print()

        print('\n' + '=' * 70)
        print('BEST COMBINED STRATEGY (Funding + Volatility)')
        print('=' * 70)

        # Combined score: funding + rebalancing potential
        for p in pairs:
            daily_rebal = (p['avg_volatility'] ** 2) / 400
            annual_rebal = daily_rebal * 365
            p['combined_apr'] = p['funding_diff_apr'] + annual_rebal
            p['annual_rebal'] = annual_rebal

        pairs.sort(key=lambda x: x['combined_apr'], reverse=True)

        print('\nTOP 5 COMBINED STRATEGIES:')
        print('-' * 70)

        for i, p in enumerate(pairs[:5], 1):
            long_asset = p['asset_a'] if asset_data[p['asset_a']]['funding'] < asset_data[p['asset_b']]['funding'] else p['asset_b']
            short_asset = p['asset_b'] if long_asset == p['asset_a'] else p['asset_a']

            print(f"\n{'#'*3} STRATEGY {i} {'#'*50}")
            print(f"   LONG:  {long_asset} (50%)")
            print(f"   SHORT: {short_asset} (50%)")
            print(f"   " + "-" * 40)
            print(f"   Funding Carry APR:    {p['funding_diff_apr']:+6.1f}%")
            print(f"   Rebalancing APR:      {p['annual_rebal']:+6.1f}%")
            print(f"   " + "-" * 40)
            print(f"   TOTAL EXPECTED APR:   {p['combined_apr']:+6.1f}%")

        # Final recommendation
        best = pairs[0]
        long_asset = best['asset_a'] if asset_data[best['asset_a']]['funding'] < asset_data[best['asset_b']]['funding'] else best['asset_b']
        short_asset = best['asset_b'] if long_asset == best['asset_a'] else best['asset_a']

        print('\n' + '=' * 70)
        print('RECOMMENDED STRATEGY')
        print('=' * 70)
        print(f'''
   ┌─────────────────────────────────────────────────────────┐
   │                                                         │
   │   ASSET A (50%): LONG  {long_asset:12}               │
   │   ASSET B (50%): SHORT {short_asset:12}               │
   │                                                         │
   │   Expected Returns:                                     │
   │   ├── Funding Carry:  {best['funding_diff_apr']:+6.1f}% APR                    │
   │   ├── Rebalancing:    {best['annual_rebal']:+6.1f}% APR                    │
   │   └── TOTAL:          {best['combined_apr']:+6.1f}% APR                    │
   │                                                         │
   │   Rebalance when: Allocation drifts >5% from 50/50     │
   │                                                         │
   └─────────────────────────────────────────────────────────┘
''')

        print('=' * 70)
        print('ALTERNATIVE: SPOT STRATEGY (No Funding, Pure Volatility)')
        print('=' * 70)

        # For spot, we want high volatility + negative correlation
        spot_pairs = [
            {'a': 'BTC', 'b': 'ETH', 'vol': 8, 'corr': 0.85, 'note': 'Classic, low rebal profit due to high correlation'},
            {'a': 'BTC', 'b': 'SOL', 'vol': 12, 'corr': 0.75, 'note': 'Higher vol, decent decorrelation'},
            {'a': 'ETH', 'b': 'BNB', 'vol': 10, 'corr': 0.70, 'note': 'Good volatility spread'},
            {'a': 'BTC', 'b': 'DOGE', 'vol': 15, 'corr': 0.60, 'note': 'High vol, lower correlation'},
            {'a': 'ETH', 'b': 'SOL', 'vol': 14, 'corr': 0.72, 'note': 'Alt L1 pair, good vol'},
        ]

        print('\nSPOT PAIRS FOR REBALANCING:')
        for sp in spot_pairs:
            rebal_apr = ((sp['vol'] ** 2) / 400) * 365 * (1 - sp['corr'])
            print(f"   {sp['a']}/{sp['b']}: ~{rebal_apr:.1f}% APR from rebalancing")
            print(f"      {sp['note']}")
            print()

    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
