"""
Cancel ALL open futures orders across all symbols
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)

from binance import AsyncClient
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

async def cancel_all_orders():
    client = await AsyncClient.create(BINANCE_API_KEY, BINANCE_API_SECRET)

    try:
        # Get all open orders
        open_orders = await client.futures_get_open_orders()

        if not open_orders:
            logger.info("No open orders found")
            return

        logger.info(f"Found {len(open_orders)} open orders")

        # Group by symbol
        symbols_with_orders = set()
        for order in open_orders:
            symbols_with_orders.add(order['symbol'])
            logger.info(f"  {order['symbol']}: {order['side']} {order['type']} @ {order['price']} qty={order['origQty']}")

        # Cancel all orders for each symbol
        cancelled = 0
        for symbol in symbols_with_orders:
            try:
                result = await client.futures_cancel_all_open_orders(symbol=symbol)
                logger.info(f"Cancelled orders for {symbol}: {result}")
                cancelled += 1
            except Exception as e:
                logger.error(f"Error cancelling orders for {symbol}: {e}")

        logger.info(f"Done! Cancelled orders for {cancelled} symbols")

        # Verify
        remaining = await client.futures_get_open_orders()
        if remaining:
            logger.warning(f"Still have {len(remaining)} orders remaining!")
        else:
            logger.info("All orders cancelled successfully")

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await client.close_connection()

if __name__ == "__main__":
    asyncio.run(cancel_all_orders())
