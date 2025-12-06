"""
Close all open positions - run once on startup
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_feed import DataFeed
from src.order_executor import OrderExecutor
from loguru import logger

async def close_all_positions():
    """Close all open positions"""
    logger.info("=" * 60)
    logger.info("CLOSING ALL OPEN POSITIONS")
    logger.info("=" * 60)

    df = DataFeed()
    await df.initialize()

    try:
        # Get all positions
        positions = await df.client.futures_position_information()
        open_positions = [p for p in positions if float(p['positionAmt']) != 0]

        logger.info(f"Found {len(open_positions)} open positions to close")

        if not open_positions:
            logger.info("No positions to close")
            balance = await df.get_account_balance()
            logger.info(f"Current balance: ${balance:.2f}")
            return balance

        executor = OrderExecutor(df)
        closed = 0
        failed = 0

        for pos in open_positions:
            symbol = pos['symbol']
            amt = float(pos['positionAmt'])
            side = 'LONG' if amt > 0 else 'SHORT'
            entry_price = float(pos['entryPrice'])
            unrealized_pnl = float(pos['unRealizedProfit'])

            try:
                if amt > 0:
                    result = await executor.close_long(symbol)
                else:
                    result = await executor.close_short(symbol)

                if result.success:
                    status = "+" if unrealized_pnl > 0 else ""
                    logger.info(f"  Closed {side} {symbol} | Entry: {entry_price:.6f} | PnL: ${status}{unrealized_pnl:.2f}")
                    closed += 1
                else:
                    logger.error(f"  FAILED {symbol}: {result.error}")
                    failed += 1

            except Exception as e:
                logger.error(f"  ERROR {symbol}: {e}")
                failed += 1

            await asyncio.sleep(0.1)  # Small delay between closes

        # Get final balance
        balance = await df.get_account_balance()

        logger.info("=" * 60)
        logger.info(f"CLOSED: {closed} positions")
        logger.info(f"FAILED: {failed} positions")
        logger.info(f"FINAL BALANCE: ${balance:.2f}")
        logger.info("=" * 60)

        return balance

    finally:
        await df.close()

if __name__ == "__main__":
    asyncio.run(close_all_positions())
