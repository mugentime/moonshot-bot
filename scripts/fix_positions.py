"""
EMERGENCY POSITION FIX SCRIPT
- Update all stop-losses to 2%
- Cancel all open orders
- Review positions
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env file
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)

from binance import AsyncClient
from binance.enums import *
from loguru import logger

# Configure logging
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# NEW SETTINGS
HARD_STOP_LOSS_PERCENT = 2.0  # 2% hard stop

async def main():
    logger.info("=" * 60)
    logger.info("EMERGENCY POSITION FIX - 2% HARD STOP LOSS")
    logger.info("=" * 60)

    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        logger.error("Missing API keys!")
        return

    client = await AsyncClient.create(BINANCE_API_KEY, BINANCE_API_SECRET)

    try:
        # 1. GET ALL OPEN POSITIONS
        logger.info("\n[1/3] FETCHING OPEN POSITIONS...")
        positions = await client.futures_position_information()

        open_positions = []
        for p in positions:
            amt = float(p['positionAmt'])
            if amt != 0:
                open_positions.append({
                    'symbol': p['symbol'],
                    'side': 'LONG' if amt > 0 else 'SHORT',
                    'quantity': abs(amt),
                    'entry_price': float(p['entryPrice']),
                    'unrealized_pnl': float(p['unRealizedProfit']),
                    'leverage': int(p['leverage']),
                    'mark_price': float(p['markPrice']),
                })

        logger.info(f"Found {len(open_positions)} open positions")

        # 2. CANCEL ALL OPEN ORDERS
        logger.info("\n[2/3] CANCELLING ALL OPEN ORDERS...")
        orders_cancelled = 0

        for pos in open_positions:
            symbol = pos['symbol']
            try:
                await client.futures_cancel_all_open_orders(symbol=symbol)
                orders_cancelled += 1
                logger.info(f"   Cancelled orders for {symbol}")
            except Exception as e:
                if "No order" not in str(e):
                    logger.warning(f"   Error cancelling {symbol}: {e}")

        # Also cancel orders for symbols we might have without positions
        try:
            open_orders = await client.futures_get_open_orders()
            symbols_with_orders = set(o['symbol'] for o in open_orders)
            for symbol in symbols_with_orders:
                await client.futures_cancel_all_open_orders(symbol=symbol)
                orders_cancelled += 1
                logger.info(f"   Cancelled orphan orders for {symbol}")
        except Exception as e:
            logger.warning(f"   Error getting open orders: {e}")

        logger.info(f"Total orders cancelled: {orders_cancelled}")

        # 3. SET NEW 2% STOP LOSSES
        logger.info("\n[3/3] SETTING 2% HARD STOP LOSSES...")

        for pos in open_positions:
            symbol = pos['symbol']
            entry = pos['entry_price']
            side = pos['side']
            qty = pos['quantity']
            pnl = pos['unrealized_pnl']
            mark = pos['mark_price']
            leverage = pos['leverage']

            # Calculate P&L %
            if entry > 0:
                if side == 'LONG':
                    pnl_pct = ((mark - entry) / entry) * 100
                else:
                    pnl_pct = ((entry - mark) / entry) * 100
            else:
                pnl_pct = 0

            logger.info(f"\n   {symbol} {side}")
            logger.info(f"      Entry: {entry:.6f} | Mark: {mark:.6f}")
            logger.info(f"      P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")

            # Calculate new 2% stop loss
            sl_ratio = HARD_STOP_LOSS_PERCENT / 100

            if side == 'LONG':
                new_sl = entry * (1 - sl_ratio)
                sl_side = SIDE_SELL
            else:
                new_sl = entry * (1 + sl_ratio)
                sl_side = SIDE_BUY

            # Get precision
            try:
                exchange_info = await client.futures_exchange_info()
                price_precision = 2
                for s in exchange_info['symbols']:
                    if s['symbol'] == symbol:
                        price_precision = s['pricePrecision']
                        break
                new_sl = round(new_sl, price_precision)
            except:
                pass

            logger.info(f"      New 2% SL: {new_sl:.6f}")

            # Set stop loss order
            try:
                order = await client.futures_create_order(
                    symbol=symbol,
                    side=sl_side,
                    type=FUTURE_ORDER_TYPE_STOP_MARKET,
                    stopPrice=new_sl,
                    closePosition=True
                )
                logger.info(f"      SL SET (Order: {order['orderId']})")
            except Exception as e:
                logger.error(f"      FAILED TO SET SL: {e}")

        # SUMMARY
        logger.info("\n" + "=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Positions: {len(open_positions)}")
        logger.info(f"Orders cancelled: {orders_cancelled}")
        logger.info(f"Stop loss: 2% HARD STOP")
        logger.info(f"Take profit: 10% target")
        logger.info(f"Trailing: 5% after 10% profit")
        logger.info("=" * 60)

        # Show positions
        if open_positions:
            logger.info("\nCURRENT POSITIONS:")
            total_pnl = 0
            for pos in open_positions:
                entry = pos['entry_price']
                mark = pos['mark_price']
                side = pos['side']
                if entry > 0:
                    if side == 'LONG':
                        pnl_pct = ((mark - entry) / entry) * 100
                    else:
                        pnl_pct = ((entry - mark) / entry) * 100
                else:
                    pnl_pct = 0
                pnl = pos['unrealized_pnl']
                total_pnl += pnl
                emoji = "" if pnl >= 0 else ""
                logger.info(f"   {emoji} {pos['symbol']} {pos['side']}: ${pnl:+.2f} ({pnl_pct:+.1f}%)")

            logger.info(f"\n   TOTAL P&L: ${total_pnl:+.2f}")

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(main())
