"""Force close all positions that are past the stop loss threshold"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance import AsyncClient
from config import BINANCE_API_KEY, BINANCE_API_SECRET

SL_THRESHOLD = -3.0  # Close positions at -3% or worse


async def force_close_sl_positions():
    client = await AsyncClient.create(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    try:
        positions = await client.futures_position_information()
        open_pos = [p for p in positions if float(p['positionAmt']) != 0]

        print(f"Found {len(open_pos)} open positions")
        print(f"Checking for positions past {SL_THRESHOLD}% SL...")
        print("=" * 60)

        to_close = []
        for p in open_pos:
            sym = p['symbol']
            amt = float(p['positionAmt'])
            entry = float(p['entryPrice'])
            mark = float(p['markPrice'])

            if amt > 0:  # LONG
                pnl_pct = ((mark - entry) / entry) * 100
                side = "LONG"
                close_side = "SELL"
            else:  # SHORT
                pnl_pct = ((entry - mark) / entry) * 100
                side = "SHORT"
                close_side = "BUY"

            if pnl_pct <= SL_THRESHOLD:
                to_close.append({
                    'symbol': sym,
                    'side': side,
                    'close_side': close_side,
                    'quantity': abs(amt),
                    'pnl_pct': pnl_pct,
                    'entry': entry,
                    'mark': mark
                })
                print(f"🔴 {sym:15} {side:5} {pnl_pct:+.2f}% - WILL CLOSE")

        if not to_close:
            print("\n✅ No positions past SL threshold")
            return

        print(f"\n{'='*60}")
        print(f"CLOSING {len(to_close)} POSITIONS...")
        print(f"{'='*60}")

        # Confirm before closing
        confirm = input("\nType 'YES' to confirm closing these positions: ")
        if confirm != 'YES':
            print("Cancelled.")
            return

        total_loss = 0
        for pos in to_close:
            try:
                result = await client.futures_create_order(
                    symbol=pos['symbol'],
                    side=pos['close_side'],
                    type='MARKET',
                    quantity=pos['quantity'],
                    reduceOnly=True
                )
                print(f"✅ Closed {pos['symbol']} - Order ID: {result['orderId']}")

                # Estimate loss (rough)
                # loss = margin * leverage * pnl_pct (but we don't have margin here)
            except Exception as e:
                print(f"❌ Failed to close {pos['symbol']}: {e}")

        print(f"\n{'='*60}")
        print("DONE - Check your positions")

    finally:
        await client.close_connection()


if __name__ == "__main__":
    asyncio.run(force_close_sl_positions())
