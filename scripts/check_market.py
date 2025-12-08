"""Quick market check script"""
import asyncio
from binance import AsyncClient
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BINANCE_API_KEY, BINANCE_API_SECRET

async def check_market():
    client = await AsyncClient.create(
        api_key=BINANCE_API_KEY,
        api_secret=BINANCE_API_SECRET
    )

    # Get top movers from the whitelist
    tickers = await client.futures_ticker()

    # Filter to whitelisted coins
    whitelist = [
        'ALPACAUSDT', 'USTCUSDT', 'BNXUSDT', 'MOODENGUSDT', 'LUNA2USDT',
        'ALPHAUSDT', 'SWARMSUSDT', 'DOODUSDT', 'BEATUSDT', 'PIUSDT',
        'NOTUSDT', 'SYNUSDT', 'OCEANUSDT', 'DGBUSDT', 'AGIXUSDT',
        'RONINUSDT', 'HEMIUSDT', 'POWERUSDT', 'MUBARAKUSDT', '1000LUNCUSDT',
        'BULLAUSDT', 'LINAUSDT', 'HMSTRUSDT', 'GOATUSDT', 'C98USDT',
        'FETUSDT', 'MEWUSDT', 'SUIUSDT', 'ZENUSDT', 'SHELLUSDT',
        'RIFUSDT', 'SXPUSDT', 'LPTUSDT', 'PORT3USDT', 'BSWUSDT',
        'NEIROETHUSDT', 'VIDTUSDT', 'TROYUSDT', 'BAKEUSDT', 'AMBUSDT',
        'KDAUSDT', 'FLMUSDT', 'MEMEFIUSDT', 'PIPPINUSDT', 'NULSUSDT',
        'PERPUSDT', 'HUSDT', 'SKATEUSDT', 'HIFIUSDT', 'OBOLUSDT',
        'MILKUSDT', 'LEVERUSDT', '1000XUSDT', 'MYROUSDT', 'PNUTUSDT',
        'PUFFERUSDT', 'ZEREBROUSDT', 'STABLEUSDT', 'ARIAUSDT', 'BIOUSDT', 'WLDUSDT'
    ]

    filtered = [t for t in tickers if t['symbol'] in whitelist]

    # Count up vs down
    up = 0
    down = 0
    total_change = 0

    for t in filtered:
        change = float(t['priceChangePercent'])
        total_change += change
        if change > 0:
            up += 1
        else:
            down += 1

    avg_change = total_change / len(filtered) if filtered else 0

    # Sort by change
    filtered.sort(key=lambda x: float(x['priceChangePercent']), reverse=True)

    print('=' * 60)
    print('MARKET OVERVIEW (61 Whitelisted Coins)')
    print('=' * 60)
    print(f'UP: {up} | DOWN: {down} | AVG Change: {avg_change:+.2f}%')
    print()

    # Determine direction based on macro strategy logic
    # Score >= +2 -> LONG, Score <= -2 -> SHORT
    majority_score = 1 if up > down else (-1 if down > up else 0)
    velocity_score = 1 if avg_change > 0.5 else (-1 if avg_change < -0.5 else 0)
    total_score = majority_score + velocity_score

    if total_score >= 2:
        direction = 'LONG (Bullish)'
        signal = '[LONG]'
    elif total_score <= -2:
        direction = 'SHORT (Bearish)'
        signal = '[SHORT]'
    else:
        direction = 'FLAT (Neutral)'
        signal = '[FLAT]'

    print(f'{signal} MACRO DIRECTION: {direction}')
    print(f'   Majority Score: {majority_score} | Velocity Score: {velocity_score} | Total: {total_score}')
    print()

    print('TOP 10 GAINERS:')
    for t in filtered[:10]:
        sym = t['symbol']
        chg = float(t['priceChangePercent'])
        price = float(t['lastPrice'])
        print(f"  {sym:15} {chg:+7.2f}%  ${price:.4f}")

    print()
    print('TOP 10 LOSERS:')
    for t in filtered[-10:]:
        sym = t['symbol']
        chg = float(t['priceChangePercent'])
        price = float(t['lastPrice'])
        print(f"  {sym:15} {chg:+7.2f}%  ${price:.4f}")

    # Also check BTC/ETH
    print()
    print('REFERENCE (BTC/ETH):')
    for t in tickers:
        if t['symbol'] in ['BTCUSDT', 'ETHUSDT']:
            sym = t['symbol']
            chg = float(t['priceChangePercent'])
            price = float(t['lastPrice'])
            print(f"  {sym:15} {chg:+7.2f}%  ${price:,.2f}")

    await client.close_connection()

if __name__ == "__main__":
    asyncio.run(check_market())
