"""Check why position sync is missing positions"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance import AsyncClient
from config import BINANCE_API_KEY, BINANCE_API_SECRET

async def main():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    # Get all positions from Binance
    positions = await client.futures_position_information()
    open_positions = [p for p in positions if float(p['positionAmt']) != 0]

    print(f"Open positions on Binance: {len(open_positions)}")
    print()

    symbols = []
    for p in open_positions:
        symbol = p['symbol']
        amt = float(p['positionAmt'])
        entry = float(p['entryPrice'])
        pnl = float(p['unRealizedProfit'])
        side = 'LONG' if amt > 0 else 'SHORT'

        symbols.append(symbol)
        print(f"  {symbol:15} {side:5} entry={entry:.6f} pnl=${pnl:+.4f}")

    print()

    # Check for duplicates
    unique = set(symbols)
    if len(unique) < len(symbols):
        print("WARNING: DUPLICATE SYMBOLS FOUND!")
        print(f"  Total positions: {len(symbols)}")
        print(f"  Unique symbols: {len(unique)}")
        print()
        from collections import Counter
        counts = Counter(symbols)
        for sym, count in counts.items():
            if count > 1:
                print(f"  {sym}: {count} positions (only 1 tracked!)")
    else:
        print("All symbols are unique - no duplicates")

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
