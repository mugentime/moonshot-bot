"""
Scan all Binance Futures pairs for moonshots in the last 10 hours.
Uses kline data to calculate actual 10h price change.
"""
import asyncio
import aiohttp
import sys
import io
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Thresholds
MOONSHOT_THRESHOLD = 10.0  # 10% move in either direction
HOURS = 7


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


async def get_klines(session: aiohttp.ClientSession, symbol: str, hours: int) -> Dict:
    """Get kline data for a symbol to calculate price change over specified hours"""
    # Use 1h klines, fetch enough for the time period
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit={hours + 1}"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                klines = await response.json()
                if len(klines) >= 2:
                    # First kline is oldest (10h ago), last is most recent
                    open_price = float(klines[0][1])  # Open of first candle
                    close_price = float(klines[-1][4])  # Close of last candle
                    high_price = max(float(k[2]) for k in klines)
                    low_price = min(float(k[3]) for k in klines)
                    volume = sum(float(k[7]) for k in klines)  # Quote volume

                    if open_price > 0:
                        change_pct = ((close_price - open_price) / open_price) * 100
                        volatility = ((high_price - low_price) / close_price) * 100 if close_price > 0 else 0

                        return {
                            'symbol': symbol,
                            'change_pct': change_pct,
                            'open_price': open_price,
                            'current_price': close_price,
                            'high': high_price,
                            'low': low_price,
                            'volume_usdt': volume,
                            'volatility': volatility
                        }
            return None
    except Exception as e:
        return None


async def process_batch(session: aiohttp.ClientSession, symbols: List[str], hours: int) -> List[Dict]:
    """Process a batch of symbols concurrently"""
    tasks = [get_klines(session, symbol, hours) for symbol in symbols]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


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
    print("=" * 90)
    print(f"BINANCE FUTURES {HOURS}H MOONSHOT SCANNER")
    print(f"Threshold: +/-{MOONSHOT_THRESHOLD}% price change")
    print(f"Scan Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 90)

    # Get all symbols
    print("\nFetching symbol list...")
    symbols = await get_all_symbols()
    print(f"Found {len(symbols)} USDT perpetual pairs")

    # Process in batches to avoid rate limits
    print(f"Analyzing {HOURS}h price movements...")
    all_results = []
    batch_size = 50

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            results = await process_batch(session, batch, HOURS)
            all_results.extend(results)
            # Small delay between batches
            if i + batch_size < len(symbols):
                await asyncio.sleep(0.5)

    print(f"Successfully analyzed {len(all_results)} pairs")

    # Separate into uptrends and downtrends
    uptrends = [r for r in all_results if r['change_pct'] >= MOONSHOT_THRESHOLD]
    downtrends = [r for r in all_results if r['change_pct'] <= -MOONSHOT_THRESHOLD]

    # Sort
    uptrends.sort(key=lambda x: x['change_pct'], reverse=True)
    downtrends.sort(key=lambda x: x['change_pct'])

    # Print uptrends
    print("\n" + "=" * 90)
    print(f"🚀 UPTREND MOONSHOTS (>= +{MOONSHOT_THRESHOLD}% in {HOURS}h): {len(uptrends)} found")
    print("=" * 90)

    if uptrends:
        print(f"{'#':<3} {'Symbol':<16} {'Change':<10} {'Open':<14} {'Current':<14} {'High':<14} {'Low':<14} {'Volume':<12}")
        print("-" * 107)
        for i, m in enumerate(uptrends, 1):
            print(f"{i:<3} {m['symbol']:<16} +{m['change_pct']:.2f}%    {m['open_price']:<14.6g} {m['current_price']:<14.6g} {m['high']:<14.6g} {m['low']:<14.6g} {format_volume(m['volume_usdt']):<12}")
    else:
        print("No uptrend moonshots found.")

    # Print downtrends
    print("\n" + "=" * 90)
    print(f"📉 DOWNTREND MOONSHOTS (<= -{MOONSHOT_THRESHOLD}% in {HOURS}h): {len(downtrends)} found")
    print("=" * 90)

    if downtrends:
        print(f"{'#':<3} {'Symbol':<16} {'Change':<10} {'Open':<14} {'Current':<14} {'High':<14} {'Low':<14} {'Volume':<12}")
        print("-" * 107)
        for i, m in enumerate(downtrends, 1):
            print(f"{i:<3} {m['symbol']:<16} {m['change_pct']:.2f}%    {m['open_price']:<14.6g} {m['current_price']:<14.6g} {m['high']:<14.6g} {m['low']:<14.6g} {format_volume(m['volume_usdt']):<12}")
    else:
        print("No downtrend moonshots found.")

    # Summary
    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)
    print(f"Time period: Last {HOURS} hours")
    print(f"Total pairs analyzed: {len(all_results)}")
    print(f"Uptrend moonshots (>= +{MOONSHOT_THRESHOLD}%): {len(uptrends)}")
    print(f"Downtrend moonshots (<= -{MOONSHOT_THRESHOLD}%): {len(downtrends)}")
    print(f"Total significant moves: {len(uptrends) + len(downtrends)}")

    if uptrends:
        print(f"\nTop 3 Gainers ({HOURS}h):")
        for m in uptrends[:3]:
            print(f"  🚀 {m['symbol']}: +{m['change_pct']:.2f}%")

    if downtrends:
        print(f"\nTop 3 Losers ({HOURS}h):")
        for m in downtrends[:3]:
            print(f"  📉 {m['symbol']}: {m['change_pct']:.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
