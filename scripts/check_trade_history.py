"""
Check actual trade history from Binance for the last 7 hours
and compare against moonshots that happened
"""
import asyncio
import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from binance.client import Client
from binance import AsyncClient

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Try to load from .env first
from dotenv import load_dotenv
load_dotenv()

# Credentials - set via environment or railway run

# Moonshots that happened in last 7h (from our scan)
MOONSHOTS_UP = [
    "LSKUSDT", "SKLUSDT", "BEATUSDT"
]

MOONSHOTS_DOWN = [
    "ARCUSDT", "HEMIUSDT", "BNBUSDT", "FUNUSDT"
]

ALL_MOONSHOTS = MOONSHOTS_UP + MOONSHOTS_DOWN


async def get_trade_history():
    """Get all trades from the last 24 hours"""
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")

    if not api_key or not api_secret:
        print("ERROR: Missing API credentials")
        return

    client = await AsyncClient.create(api_key, api_secret)

    try:
        # Get current positions
        print("=" * 80)
        print("CURRENT OPEN POSITIONS")
        print("=" * 80)

        positions = await client.futures_position_information()
        open_positions = []
        for p in positions:
            amt = float(p['positionAmt'])
            if amt != 0:
                open_positions.append({
                    'symbol': p['symbol'],
                    'side': 'LONG' if amt > 0 else 'SHORT',
                    'size': abs(amt),
                    'entry_price': float(p['entryPrice']),
                    'unrealized_pnl': float(p['unRealizedProfit']),
                    'leverage': p['leverage']
                })

        if open_positions:
            for pos in open_positions:
                pnl_sign = "+" if pos['unrealized_pnl'] >= 0 else ""
                print(f"  {pos['symbol']}: {pos['side']} x{pos['leverage']} | Entry: ${pos['entry_price']:.6f} | PnL: {pnl_sign}${pos['unrealized_pnl']:.2f}")
        else:
            print("  No open positions")

        # Get account trade history for last 7h
        print("\n" + "=" * 80)
        print("TRADE HISTORY (LAST 7 HOURS)")
        print("=" * 80)

        # Calculate timestamp for 7h ago
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(hours=7)
        start_time = int(yesterday.timestamp() * 1000)

        # Get all trades - need to check each symbol unfortunately
        all_trades = []

        # First check the moonshot symbols
        print("\nChecking moonshot symbols for trades...")
        for symbol in ALL_MOONSHOTS:
            try:
                trades = await client.futures_account_trades(symbol=symbol, startTime=start_time, limit=100)
                if trades:
                    all_trades.extend(trades)
            except Exception as e:
                pass  # Symbol might not exist or be valid

        # Also get income history for realized PnL
        print("Fetching income history...")
        income = await client.futures_income_history(incomeType="REALIZED_PNL", startTime=start_time, limit=1000)

        if all_trades:
            print(f"\nTrades found: {len(all_trades)}")
            print("-" * 80)

            # Group by symbol
            trades_by_symbol = {}
            for trade in all_trades:
                symbol = trade['symbol']
                if symbol not in trades_by_symbol:
                    trades_by_symbol[symbol] = []
                trades_by_symbol[symbol].append(trade)

            for symbol, trades in trades_by_symbol.items():
                print(f"\n{symbol}:")
                for trade in sorted(trades, key=lambda x: x['time']):
                    trade_time = datetime.fromtimestamp(trade['time']/1000, tz=timezone.utc)
                    side = trade['side']
                    qty = float(trade['qty'])
                    price = float(trade['price'])
                    pnl = float(trade['realizedPnl'])
                    print(f"  {trade_time.strftime('%Y-%m-%d %H:%M')} | {side:<5} | Qty: {qty:.4f} | Price: ${price:.6f} | PnL: ${pnl:.2f}")
        else:
            print("\nNo trades on moonshot symbols in the last 24 hours")

        # Show income/realized PnL
        if income:
            print("\n" + "=" * 80)
            print("REALIZED PNL HISTORY (LAST 24 HOURS)")
            print("=" * 80)

            total_pnl = 0
            for inc in income:
                symbol = inc.get('symbol', 'N/A')
                amount = float(inc['income'])
                inc_time = datetime.fromtimestamp(inc['time']/1000, tz=timezone.utc)
                total_pnl += amount
                sign = "+" if amount >= 0 else ""
                print(f"  {inc_time.strftime('%Y-%m-%d %H:%M')} | {symbol:<15} | {sign}${amount:.2f}")

            print("-" * 80)
            sign = "+" if total_pnl >= 0 else ""
            print(f"TOTAL REALIZED PNL: {sign}${total_pnl:.2f}")
        else:
            print("\nNo realized PnL in the last 24 hours")

        # Summary: Which moonshots did we trade?
        print("\n" + "=" * 80)
        print("MOONSHOT CAPTURE ANALYSIS")
        print("=" * 80)

        traded_symbols = set(t['symbol'] for t in all_trades) if all_trades else set()
        income_symbols = set(i.get('symbol', '') for i in income) if income else set()
        all_traded = traded_symbols | income_symbols

        print(f"\nMoonshots that happened: {len(ALL_MOONSHOTS)}")
        print(f"Moonshots we traded: {len(all_traded & set(ALL_MOONSHOTS))}")

        # Captured moonshots
        captured = all_traded & set(ALL_MOONSHOTS)
        if captured:
            print(f"\nCAPTURED MOONSHOTS:")
            for s in captured:
                direction = "UP" if s in MOONSHOTS_UP else "DOWN"
                print(f"  [OK] {s} ({direction})")

        # Missed moonshots
        missed = set(ALL_MOONSHOTS) - all_traded
        if missed:
            print(f"\nMISSED MOONSHOTS ({len(missed)}):")
            for s in missed:
                direction = "UP" if s in MOONSHOTS_UP else "DOWN"
                print(f"  [X] {s} ({direction})")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close_connection()


if __name__ == "__main__":
    asyncio.run(get_trade_history())
