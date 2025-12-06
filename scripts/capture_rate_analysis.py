"""
Analyze bot capture rate vs actual moonshots/moondrops
"""
import asyncio
from binance import AsyncClient
from datetime import datetime, timedelta
import os
import sys
from dotenv import load_dotenv

load_dotenv()

async def analyze_capture_rate():
    client = await AsyncClient.create(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

    try:
        # Get our trade history for last 24h
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(hours=24)).timestamp() * 1000)

        income = await client.futures_income_history(
            incomeType='REALIZED_PNL',
            startTime=start_time,
            endTime=end_time,
            limit=1000
        )

        # Get unique symbols we traded
        traded_symbols = set()

        for trade in income:
            sym = trade['symbol']
            traded_symbols.add(sym)

        # Known moonshots from our analysis (>=10% range, positive net)
        moonshots = [
            'XNYUSDT', 'SKYAIUSDT', '1000LUNCUSDT', 'SAPIENUSDT', 'PUMPBTCUSDT',
            'CVCUSDT', 'BEATUSDT', 'LUNA2USDT', 'USTCUSDT', 'TAIKOUSDT',
            'TAUSDT', 'CLOUSDT', 'ZECUSDT', 'TRADOORUSDT', 'EGLDUSDT',
            'AIOUSDT', 'BULLAUSDT', 'ALCHUSDT', 'KAITOUSDT', 'SYRUPUSDT',
            'YBUSDT', 'XVGUSDT', 'BTRUSDT', 'FLUXUSDT', 'TACUSDT',
            'STOUSDT', 'LSKUSDT', 'ALPINEUSDT', 'CUDISUSDT', 'TRUUSDT'
        ]

        # Known moondrops (>=10% range, negative net)
        moondrops = [
            'LIGHTUSDT', 'PTBUSDT', 'SKATEUSDT', 'RLSUSDT', 'RECALLUSDT',
            'SYNUSDT', 'LYNUSDT', 'WIFUSDT', 'BOBUSDT', 'AIAUSDT',
            'BDXNUSDT', 'PIPPINUSDT', 'ARIAUSDT', 'BATUSDT', 'HEMIUSDT',
            'PIEVERSEUSDT', 'JELLYJELLYUSDT', 'RIVERUSDT', 'VOXELUSDT', 'EVAAUSDT',
            'STABLEUSDT', 'MAVIAUSDT', '4USDT', 'FISUSDT', 'ALLOUSDT',
            'XPINUSDT', 'CLANKERUSDT', 'MONUSDT', 'IRYSUSDT', 'CHESSUSDT',
            'USELESSUSDT', 'FARTCOINUSDT', 'JCTUSDT', 'APRUSDT', 'HANAUSDT',
            'TAGUSDT', 'NAORISUSDT', 'HEIUSDT', '1000RATSUSDT', 'BARDUSDT',
            'SOONUSDT', 'CCUSDT', 'MYXUSDT', 'COMMONUSDT', 'MMTUSDT',
            'ESPORTSUSDT', 'HIPPOUSDT', 'RAYSOLUSDT', 'PARTIUSDT', 'AVAAIUSDT',
            'ZEREBROUSDT', 'RVVUSDT', 'TRUSTUSDT', 'BLUAIUSDT', 'ATUSDT',
            'GRIFFAINUSDT', 'BLESSUSDT', 'PUFFERUSDT', 'YALAUSDT', '2ZUSDT',
            'STBLUSDT', 'COWUSDT', 'AKEUSDT', 'FOLKSUSDT', 'REIUSDT',
            'COMPUSDT', 'RESOLVUSDT', 'SWARMSUSDT', 'MERLUSDT', 'METUSDT',
            'ZENUSDT', 'TURBOUSDT', 'DASHUSDT', 'ZKCUSDT', 'EDENUSDT',
            'KGENUSDT', 'SENTUSDT', 'XPLUSDT', 'ARCUSDT', 'AEROUSDT',
            'B3USDT', 'MAGICUSDT', 'TRUTHUSDT', 'DEEPUSDT', 'ZRCUSDT',
            'CYBERUSDT', 'BRETTUSDT', 'REDUSDT', 'SOMIUSDT', 'HFTUSDT', 'HYPEUSDT'
        ]

        # Calculate capture rates
        caught_moonshots = traded_symbols.intersection(set(moonshots))
        caught_moondrops = traded_symbols.intersection(set(moondrops))

        print('='*80)
        print('BOT PERFORMANCE vs MARKET MOVES - LAST 24 HOURS')
        print('='*80)

        total_pnl = sum(float(t['income']) for t in income)
        print(f'\nTOTAL TRADES: {len(income)} transactions on {len(traded_symbols)} unique symbols')
        print(f'TOTAL REALIZED PNL: ${total_pnl:.2f}')

        print(f'\n' + '='*80)
        print('MOONSHOT CAPTURE RATE (Pumps >=10%)')
        print('='*80)
        print(f'Total Moonshots Available: {len(moonshots)}')
        print(f'Moonshots We Traded: {len(caught_moonshots)} ({len(caught_moonshots)/len(moonshots)*100:.1f}%)')
        print(f'\nCaught: {sorted(caught_moonshots)}')
        print(f'\nMissed: {sorted(set(moonshots) - caught_moonshots)}')

        print(f'\n' + '='*80)
        print('MOONDROP CAPTURE RATE (Dumps >=10%)')
        print('='*80)
        print(f'Total Moondrops Available: {len(moondrops)}')
        print(f'Moondrops We Traded: {len(caught_moondrops)} ({len(caught_moondrops)/len(moondrops)*100:.1f}%)')
        print(f'\nCaught: {sorted(caught_moondrops)}')

        # PnL by category
        print(f'\n' + '='*80)
        print('PNL BREAKDOWN BY SYMBOL')
        print('='*80)

        # Aggregate PnL by symbol
        symbol_pnl = {}
        for t in income:
            sym = t['symbol']
            pnl = float(t['income'])
            symbol_pnl[sym] = symbol_pnl.get(sym, 0) + pnl

        moonshot_pnl = sum(symbol_pnl.get(s, 0) for s in caught_moonshots)
        moondrop_pnl = sum(symbol_pnl.get(s, 0) for s in caught_moondrops)
        other_pnl = sum(pnl for sym, pnl in symbol_pnl.items() if sym not in moonshots and sym not in moondrops)

        print(f'\nMoonshot trades PnL: ${moonshot_pnl:.2f}')
        print(f'Moondrop trades PnL: ${moondrop_pnl:.2f}')
        print(f'Other trades PnL: ${other_pnl:.2f}')

        print(f'\n' + '='*80)
        print('TOP WINNERS')
        print('='*80)
        sorted_pnl = sorted(symbol_pnl.items(), key=lambda x: x[1], reverse=True)
        for sym, pnl in sorted_pnl[:10]:
            tag = '[MOONSHOT]' if sym in moonshots else '[MOONDROP]' if sym in moondrops else ''
            print(f'  {sym:<20} ${pnl:>+8.2f} {tag}')

        print(f'\n' + '='*80)
        print('TOP LOSERS')
        print('='*80)
        for sym, pnl in sorted_pnl[-10:]:
            tag = '[MOONSHOT]' if sym in moonshots else '[MOONDROP]' if sym in moondrops else ''
            print(f'  {sym:<20} ${pnl:>+8.2f} {tag}')

        # Summary
        print(f'\n' + '='*80)
        print('SUMMARY')
        print('='*80)
        total_movers = len(moonshots) + len(moondrops)
        total_caught = len(caught_moonshots) + len(caught_moondrops)
        print(f'\nTotal Big Movers (>=10%): {total_movers}')
        print(f'Total We Traded: {total_caught} ({total_caught/total_movers*100:.1f}%)')
        print(f'\nMoonshot Catch Rate: {len(caught_moonshots)}/{len(moonshots)} = {len(caught_moonshots)/len(moonshots)*100:.1f}%')
        print(f'Moondrop Catch Rate: {len(caught_moondrops)}/{len(moondrops)} = {len(caught_moondrops)/len(moondrops)*100:.1f}%')

    finally:
        await client.close_connection()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(analyze_capture_rate())
