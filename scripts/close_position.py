"""
Close a specific position immediately
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)

from binance import AsyncClient
from binance.enums import *
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

async def close_position(symbol: str):
    client = await AsyncClient.create(BINANCE_API_KEY, BINANCE_API_SECRET)

    try:
        # Get position
        positions = await client.futures_position_information(symbol=symbol)

        for p in positions:
            amt = float(p['positionAmt'])
            if amt != 0:
                side = SIDE_SELL if amt > 0 else SIDE_BUY
                qty = abs(amt)

                logger.info(f"Closing {symbol}: {qty} (Side: {side})")

                # Cancel existing orders
                try:
                    await client.futures_cancel_all_open_orders(symbol=symbol)
                except:
                    pass

                # Close position
                order = await client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type=ORDER_TYPE_MARKET,
                    quantity=qty,
                    reduceOnly=True
                )

                logger.info(f"Position {symbol} CLOSED. Order ID: {order['orderId']}")
                return

        logger.warning(f"No position found for {symbol}")

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await client.close_connection()

if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "ZKCUSDT"
    asyncio.run(close_position(symbol))
