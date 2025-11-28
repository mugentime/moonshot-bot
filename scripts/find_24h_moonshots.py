"""
Scan all Binance Futures pairs for moonshots (significant price movements) in the last 24 hours.
A moonshot is defined as:
- UPTREND: Price increased by 10% or more in 24h
- DOWNTREND: Price decreased by 10% or more in 24h
"""
import asyncio
import aiohttp
import sys
import io
from datetime import datetime, timezone
from typing import List, Dict, Tuple

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Thresholds
MOONSHOT_THRESHOLD = 10.0  # 10% move in either direction


async def get_all_symbols() -> List[str]:
    """Get all USDT perpetual futures symbols from Binance"""
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            symbols = [
                s['symbol'] for s in data['symbols']
                if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING'
            ]
            return symbols


async def get_24h_ticker(session: aiohttp.ClientSession, symbol: str) -> Dict:
    """Get 24h ticker data for a symbol"""
    url = f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            return None
    except Exception as e:
        return None


async def get_all_24h_tickers() -> List[Dict]:
    """Get 24h ticker data for all symbols in one call"""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            return []


def identify_moonshots(tickers: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """
    Identify moonshots from ticker data.
    Returns tuple of (uptrend_moonshots, downtrend_moonshots)
    """
    uptrends = []
    downtrends = []

    for ticker in tickers:
        symbol = ticker.get('symbol', '')

        # Skip non-USDT pairs
        if not symbol.endswith('USDT'):
            continue

        try:
            price_change_pct = float(ticker.get('priceChangePercent', 0))
            current_price = float(ticker.get('lastPrice', 0))
            high_24h = float(ticker.get('highPrice', 0))
            low_24h = float(ticker.get('lowPrice', 0))
            volume = float(ticker.get('quoteVolume', 0))  # Volume in USDT

            # Calculate volatility (high-low range as % of current price)
            if current_price > 0:
                volatility = ((high_24h - low_24h) / current_price) * 100
            else:
                volatility = 0

            if price_change_pct >= MOONSHOT_THRESHOLD:
                uptrends.append({
                    'symbol': symbol,
                    'change_pct': price_change_pct,
                    'current_price': current_price,
                    'high_24h': high_24h,
                    'low_24h': low_24h,
                    'volume_usdt': volume,
                    'volatility': volatility
                })
            elif price_change_pct <= -MOONSHOT_THRESHOLD:
                downtrends.append({
                    'symbol': symbol,
                    'change_pct': price_change_pct,
                    'current_price': current_price,
                    'high_24h': high_24h,
                    'low_24h': low_24h,
                    'volume_usdt': volume,
                    'volatility': volatility
                })
        except (ValueError, TypeError):
            continue

    # Sort by absolute change percentage
    uptrends.sort(key=lambda x: x['change_pct'], reverse=True)
    downtrends.sort(key=lambda x: x['change_pct'])

    return uptrends, downtrends


def format_volume(vol: float) -> str:
    """Format volume in millions/billions"""
    if vol >= 1_000_000_000:
        return f"${vol/1_000_000_000:.2f}B"
    elif vol >= 1_000_000:
        return f"${vol/1_000_000:.2f}M"
    elif vol >= 1_000:
        return f"${vol/1_000:.2f}K"
    else:
        return f"${vol:.2f}"


async def main():
    print("=" * 80)
    print(f"BINANCE FUTURES 24H MOONSHOT SCANNER")
    print(f"Threshold: ±{MOONSHOT_THRESHOLD}% price change")
    print(f"Scan Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 80)

    # Get all tickers in one API call
    print("\nFetching 24h ticker data for all pairs...")
    tickers = await get_all_24h_tickers()

    if not tickers:
        print("ERROR: Failed to fetch ticker data")
        return

    print(f"Analyzing {len(tickers)} trading pairs...")

    # Identify moonshots
    uptrends, downtrends = identify_moonshots(tickers)

    # Print results
    print("\n" + "=" * 80)
    print(f"🚀 UPTREND MOONSHOTS (≥+{MOONSHOT_THRESHOLD}% in 24h): {len(uptrends)} found")
    print("=" * 80)

    if uptrends:
        print(f"{'#':<3} {'Symbol':<15} {'Change':<10} {'Price':<15} {'24h High':<15} {'24h Low':<15} {'Volume':<12} {'Volatility':<10}")
        print("-" * 105)
        for i, moon in enumerate(uptrends, 1):
            print(f"{i:<3} {moon['symbol']:<15} +{moon['change_pct']:.2f}%     {moon['current_price']:<15.8g} {moon['high_24h']:<15.8g} {moon['low_24h']:<15.8g} {format_volume(moon['volume_usdt']):<12} {moon['volatility']:.1f}%")
    else:
        print("No uptrend moonshots found.")

    print("\n" + "=" * 80)
    print(f"📉 DOWNTREND MOONSHOTS (≤-{MOONSHOT_THRESHOLD}% in 24h): {len(downtrends)} found")
    print("=" * 80)

    if downtrends:
        print(f"{'#':<3} {'Symbol':<15} {'Change':<10} {'Price':<15} {'24h High':<15} {'24h Low':<15} {'Volume':<12} {'Volatility':<10}")
        print("-" * 105)
        for i, moon in enumerate(downtrends, 1):
            print(f"{i:<3} {moon['symbol']:<15} {moon['change_pct']:.2f}%     {moon['current_price']:<15.8g} {moon['high_24h']:<15.8g} {moon['low_24h']:<15.8g} {format_volume(moon['volume_usdt']):<12} {moon['volatility']:.1f}%")
    else:
        print("No downtrend moonshots found.")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total pairs analyzed: {len([t for t in tickers if t.get('symbol', '').endswith('USDT')])}")
    print(f"Uptrend moonshots: {len(uptrends)}")
    print(f"Downtrend moonshots: {len(downtrends)}")
    print(f"Total moonshots: {len(uptrends) + len(downtrends)}")

    if uptrends:
        print(f"\nTop 3 Gainers:")
        for moon in uptrends[:3]:
            print(f"  🚀 {moon['symbol']}: +{moon['change_pct']:.2f}%")

    if downtrends:
        print(f"\nTop 3 Losers:")
        for moon in downtrends[:3]:
            print(f"  📉 {moon['symbol']}: {moon['change_pct']:.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
