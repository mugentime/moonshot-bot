"""
FORCE CANCEL ALL STOP_MARKET ORDERS ON BINANCE

This script immediately cancels ALL stop loss orders on your Binance Futures account.
Run this to ensure NO stop loss orders are active.

Usage:
    python scripts/force_cancel_all_stops.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from binance import AsyncClient
from loguru import logger

load_dotenv()

async def cancel_all_stop_orders():
    """Cancel ALL STOP_MARKET orders on Binance Futures"""

    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    testnet = os.getenv("BINANCE_TESTNET", "false").lower() == "true"

    if not api_key or not api_secret:
        logger.error("Missing BINANCE_API_KEY or BINANCE_API_SECRET in .env")
        return

    logger.info("="*60)
    logger.info("FORCE CANCELLING ALL STOP_MARKET ORDERS")
    logger.info("="*60)

    try:
        # Create client
        if testnet:
            client = await AsyncClient.create(
                api_key=api_key,
                api_secret=api_secret,
                testnet=True
            )
            logger.info("Connected to TESTNET")
        else:
            client = await AsyncClient.create(
                api_key=api_key,
                api_secret=api_secret
            )
            logger.info("Connected to MAINNET")

        # Get all open orders
        logger.info("Fetching all open orders...")
        open_orders = await client.futures_get_open_orders()
        logger.info(f"Found {len(open_orders)} total open orders")

        # Filter for STOP_MARKET orders
        stop_orders = [o for o in open_orders if o['type'] == 'STOP_MARKET']

        if not stop_orders:
            logger.info("✅ NO STOP_MARKET ORDERS FOUND")
            logger.info("Your account has NO active stop loss orders")
            await client.close_connection()
            return

        logger.warning(f"Found {len(stop_orders)} STOP_MARKET orders:")
        for order in stop_orders:
            logger.warning(f"  - {order['symbol']}: {order['side']} @ {order.get('stopPrice', 'N/A')}")

        # Cancel all stop orders
        logger.info(f"\nCancelling {len(stop_orders)} STOP_MARKET orders...")
        cancelled = 0
        failed = 0

        for order in stop_orders:
            try:
                await client.futures_cancel_order(
                    symbol=order['symbol'],
                    orderId=order['orderId']
                )
                cancelled += 1
                logger.info(f"✅ Cancelled: {order['symbol']}")
            except Exception as e:
                failed += 1
                logger.error(f"❌ Failed to cancel {order['symbol']}: {e}")

        logger.info("="*60)
        logger.info(f"RESULTS:")
        logger.info(f"  Cancelled: {cancelled}")
        logger.info(f"  Failed: {failed}")
        logger.info("="*60)

        if cancelled == len(stop_orders):
            logger.info("✅ ALL STOP_MARKET ORDERS CANCELLED")
            logger.info("✅ NO STOP LOSS IS ACTIVE")
        else:
            logger.warning(f"⚠️  {failed} orders could not be cancelled")

        await client.close_connection()

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(cancel_all_stop_orders())
