"""
Analyze best assets for lending/borrowing on Binance Earn
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
        # Get account balance
        account = await client.futures_account()
        print('=' * 60)
        print('ACCOUNT STATUS')
        print('=' * 60)
        print(f"  Total Wallet: ${float(account['totalWalletBalance']):.2f}")
        print(f"  Available: ${float(account['availableBalance']):.2f}")
        print(f"  Unrealized PnL: ${float(account['totalUnrealizedProfit']):.2f}")

        # Get funding rates
        print('\n' + '=' * 60)
        print('FUNDING RATE ANALYSIS')
        print('=' * 60)

        # Get premium index for funding rates
        premiums = await client.futures_mark_price()

        funding_data = []
        for p in premiums:
            if 'lastFundingRate' in p and p['lastFundingRate']:
                rate = float(p['lastFundingRate'])
                funding_data.append({
                    'symbol': p['symbol'],
                    'rate': rate,
                    'apr': rate * 3 * 365 * 100  # 3 funding per day * 365 days
                })

        # Sort by funding rate
        funding_data.sort(key=lambda x: x['rate'], reverse=True)

        print('\nHIGHEST FUNDING (Longs pay Shorts - SHORT these):')
        for f in funding_data[:10]:
            print(f"  {f['symbol']:18} Rate: {f['rate']*100:+.4f}%  APR: {f['apr']:+.1f}%")

        print('\nLOWEST FUNDING (Shorts pay Longs - LONG these):')
        for f in funding_data[-10:]:
            print(f"  {f['symbol']:18} Rate: {f['rate']*100:+.4f}%  APR: {f['apr']:+.1f}%")

        # Get top volume assets (more liquid = better for lending)
        tickers = await client.futures_ticker()
        volume_data = []
        for t in tickers:
            vol = float(t.get('quoteVolume', 0))
            if vol > 0:
                volume_data.append({
                    'symbol': t['symbol'],
                    'volume': vol,
                    'price_change': float(t.get('priceChangePercent', 0))
                })

        volume_data.sort(key=lambda x: x['volume'], reverse=True)

        print('\n' + '=' * 60)
        print('TOP VOLUME (Most Liquid - Good for Lending)')
        print('=' * 60)
        for v in volume_data[:15]:
            vol_m = v['volume'] / 1_000_000
            print(f"  {v['symbol']:18} Vol: ${vol_m:,.0f}M  24h: {v['price_change']:+.1f}%")

        # Analysis
        print('\n' + '=' * 60)
        print('LENDING STRATEGY RECOMMENDATION')
        print('=' * 60)

        print('''
WHAT TO LEND (Earn interest):
------------------------------
1. USDT/USDC - Stablecoins
   - Safest option, no price risk
   - Typical APY: 5-15%
   - Best for: Capital preservation

2. BTC/ETH - Blue chips
   - Lower volatility than alts
   - Good collateral value
   - Best for: Long-term holders

3. BNB - Exchange token
   - High utility on Binance
   - Often higher APY
   - Best for: Binance ecosystem users


WHAT TO BORROW AGAINST:
-----------------------
1. BTC - Best collateral
   - Highest LTV ratio (up to 65-70%)
   - Most stable value
   - Lowest liquidation risk

2. ETH - Second best
   - Good LTV (up to 65%)
   - High liquidity
   - Strong fundamentals

3. BNB - Platform benefits
   - Reduced fees on Binance
   - Decent LTV


STRATEGY FOR YOUR SITUATION:
----------------------------
Given your current positions are mostly LONG altcoins:

LEND: USDT
  - You have winning positions (+$7.96 unrealized)
  - Park profits in USDT lending when you take profits
  - Earn 5-15% APY while waiting for next entries

BORROW AGAINST: BTC or ETH
  - If you need more capital for trading
  - Borrow USDT against BTC/ETH
  - Use borrowed USDT for futures margin
  - This avoids selling your spot holdings

AVOID BORROWING:
  - Altcoins (high volatility = liquidation risk)
  - Memecoins (extreme volatility)
  - Low-volume assets (hard to liquidate)
''')

        print('=' * 60)
        print('CURRENT MARKET SENTIMENT')
        print('=' * 60)

        # Check if market is bullish/bearish based on funding
        avg_funding = sum(f['rate'] for f in funding_data) / len(funding_data) if funding_data else 0

        if avg_funding > 0.0005:
            sentiment = "VERY BULLISH (high funding = longs overleveraged)"
        elif avg_funding > 0.0001:
            sentiment = "BULLISH (positive funding)"
        elif avg_funding > -0.0001:
            sentiment = "NEUTRAL"
        elif avg_funding > -0.0005:
            sentiment = "BEARISH (negative funding)"
        else:
            sentiment = "VERY BEARISH (shorts overleveraged)"

        print(f"  Average Funding Rate: {avg_funding*100:.4f}%")
        print(f"  Market Sentiment: {sentiment}")

        # Final recommendation
        print('\n' + '=' * 60)
        print('FINAL RECOMMENDATION')
        print('=' * 60)
        print('''
  LEND:   USDT (stable, 5-15% APY, no price risk)

  BORROW AGAINST: BTC (best LTV, lowest risk)

  WHY: Your altcoin longs are performing well (+10%+).
       When you take profits, park USDT in Earn.
       If you need more margin, borrow against BTC
       rather than selling your spot holdings.
''')

    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
