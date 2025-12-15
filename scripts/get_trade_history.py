"""
Get closed trade history from Binance Futures API - DETAILED ANALYSIS
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from binance import AsyncClient

async def get_detailed_losses():
    """Fetch and analyze losing trades from Binance Futures"""
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")

    client = await AsyncClient.create(api_key, api_secret)

    try:
        # Get all trades from the last 7 days
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)

        print("=" * 100)
        print("DETAILED ANALYSIS: LAST 20 CLOSED LOSING POSITIONS")
        print("=" * 100)

        # Get income history (includes realized PnL)
        income = await client.futures_income_history(
            incomeType="REALIZED_PNL",
            startTime=start_time,
            endTime=end_time,
            limit=200
        )

        # Filter for losses and get unique symbols
        losses = [i for i in income if float(i['income']) < 0]
        losses.sort(key=lambda x: x['time'], reverse=True)

        # Group by symbol to find entry/exit pairs
        analyzed = []

        for loss in losses[:20]:
            symbol = loss['symbol']
            loss_time = datetime.fromtimestamp(loss['time'] / 1000)
            pnl = float(loss['income'])

            # Get trades for this symbol to find entry
            try:
                trades = await client.futures_account_trades(
                    symbol=symbol,
                    startTime=start_time,
                    limit=50
                )

                # Find the trade that caused this loss
                loss_trade = None
                entry_trade = None

                for t in trades:
                    if t['time'] == loss['time'] or abs(t['time'] - loss['time']) < 1000:
                        loss_trade = t
                        break

                if loss_trade:
                    # Find corresponding entry (opposite side before this trade)
                    exit_side = loss_trade['side']
                    entry_side = 'SELL' if exit_side == 'BUY' else 'BUY'

                    for t in reversed(trades):
                        if t['time'] < loss_trade['time'] and t['side'] == entry_side:
                            entry_trade = t
                            break

                    entry_price = float(entry_trade['price']) if entry_trade else 0
                    exit_price = float(loss_trade['price'])
                    qty = float(loss_trade['qty'])
                    direction = "LONG" if entry_side == "BUY" else "SHORT"

                    if entry_price > 0:
                        if direction == "LONG":
                            price_change_pct = ((exit_price - entry_price) / entry_price) * 100
                        else:
                            price_change_pct = ((entry_price - exit_price) / entry_price) * 100
                    else:
                        price_change_pct = 0

                    # Calculate hold time
                    if entry_trade:
                        entry_time = datetime.fromtimestamp(entry_trade['time'] / 1000)
                        hold_time = loss_time - entry_time
                        hold_str = str(hold_time).split('.')[0]
                    else:
                        entry_time = None
                        hold_str = "Unknown"

                    analyzed.append({
                        'symbol': symbol,
                        'direction': direction,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'entry_time': entry_time,
                        'exit_time': loss_time,
                        'hold_time': hold_str,
                        'price_change_pct': price_change_pct,
                        'pnl_usd': pnl,
                        'qty': qty
                    })
                else:
                    analyzed.append({
                        'symbol': symbol,
                        'direction': 'Unknown',
                        'entry_price': 0,
                        'exit_price': 0,
                        'entry_time': None,
                        'exit_time': loss_time,
                        'hold_time': 'Unknown',
                        'price_change_pct': 0,
                        'pnl_usd': pnl,
                        'qty': 0
                    })

            except Exception as e:
                analyzed.append({
                    'symbol': symbol,
                    'direction': 'Error',
                    'entry_price': 0,
                    'exit_price': 0,
                    'entry_time': None,
                    'exit_time': loss_time,
                    'hold_time': 'Error',
                    'price_change_pct': 0,
                    'pnl_usd': pnl,
                    'qty': 0,
                    'error': str(e)
                })

            await asyncio.sleep(0.1)  # Rate limit

        # Print detailed analysis
        print("\n")
        for i, trade in enumerate(analyzed, 1):
            print(f"{'-' * 100}")
            print(f"LOSS #{i}: {trade['symbol']}")
            print(f"{'-' * 100}")
            print(f"  Direction:      {trade['direction']}")
            print(f"  Entry Price:    ${trade['entry_price']:.6f}")
            print(f"  Exit Price:     ${trade['exit_price']:.6f}")
            print(f"  Price Change:   {trade['price_change_pct']:+.2f}%")
            print(f"  Entry Time:     {trade['entry_time'].strftime('%Y-%m-%d %H:%M:%S') if trade['entry_time'] else 'Unknown'}")
            print(f"  Exit Time:      {trade['exit_time'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Hold Duration:  {trade['hold_time']}")
            print(f"  Realized PnL:   ${trade['pnl_usd']:.4f}")
            print()

            # Determine likely exit reason
            if abs(trade['price_change_pct']) >= 2.5:
                reason = "STOP LOSS (price moved ~3% against position)"
            elif trade['hold_time'] and 'second' in str(trade['hold_time']).lower():
                reason = "IMMEDIATE CLOSE (likely SL order failure - BUG)"
            else:
                reason = "Manual/Other"
            print(f"  LIKELY REASON:  {reason}")
            print()

        # Summary
        print("=" * 100)
        print("SUMMARY")
        print("=" * 100)
        total_loss = sum(t['pnl_usd'] for t in analyzed)
        avg_loss = total_loss / len(analyzed) if analyzed else 0
        avg_hold = [t for t in analyzed if t['hold_time'] != 'Unknown']

        print(f"Total Positions Analyzed: {len(analyzed)}")
        print(f"Total Loss: ${total_loss:.4f}")
        print(f"Average Loss per Trade: ${avg_loss:.4f}")

        # Count by reason
        immediate_closes = sum(1 for t in analyzed if 'second' in str(t.get('hold_time', '')).lower() or t.get('hold_time') == '0:00:00')
        if immediate_closes > 0:
            print(f"\n⚠️  IMMEDIATE CLOSES (BUG): {immediate_closes} trades")
            print("   These were likely closed due to the STOP_MARKET order failure bug")
            print("   that we just fixed. Positions were opened then immediately closed.")

    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(get_detailed_losses())
