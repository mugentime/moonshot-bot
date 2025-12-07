"""
MACRO INDEX BOT
Trade all 61 whitelisted coins in same direction based on macro indicator.

Strategy:
- Calculate macro score from majority vote + leader-follower + aggregate velocity
- Score >= +2 → LONG all 61 coins
- Score <= -2 → SHORT all 61 coins
- Fixed exits: 5% SL, 10% TP per position
"""
import asyncio
import sys
import os
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from loguru import logger
import uvicorn

from config import PORT, LOG_LEVEL, PairFilterConfig
from src import DataFeed, PairFilter, PositionTracker, OrderExecutor
from src.macro_strategy import MacroIndicator, MacroConfig, MacroExitManager, MacroDirection
from src.profit_tracker import profit_tracker

# Configure logging
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
    level=LOG_LEVEL
)

# Also log to file
logger.add(
    "logs/macro_bot_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG"
)


class MacroIndexBot:
    """
    Macro Index Trading Bot
    - Calculates composite macro indicator across all 61 coins
    - Opens positions on ALL coins in same direction
    - Fixed 5% SL, 10% TP per position
    """

    def __init__(self):
        self.config = MacroConfig()
        self.data_feed = DataFeed()
        self.pair_filter = PairFilter(self.data_feed)
        self.position_tracker = PositionTracker(self.data_feed)
        self.order_executor = OrderExecutor(self.data_feed)
        self.macro_indicator = None  # Initialize after data_feed
        self.exit_manager = MacroExitManager(self.config)

        self._running = False
        self._macro_task = None
        self._monitor_task = None

        # Trading state
        self.current_direction: MacroDirection = MacroDirection.FLAT
        self.whitelisted_symbols: list = []

    async def close_all_positions(self):
        """Close all open positions before starting fresh"""
        logger.info("=" * 60)
        logger.info("CLOSING ALL EXISTING POSITIONS FOR FRESH START")
        logger.info("=" * 60)

        try:
            positions = await self.data_feed.client.futures_position_information()
            open_positions = [p for p in positions if float(p['positionAmt']) != 0]

            if not open_positions:
                logger.info("No existing positions to close")
                return

            logger.info(f"Found {len(open_positions)} positions to close")

            for pos in open_positions:
                symbol = pos['symbol']
                amt = float(pos['positionAmt'])
                side = 'LONG' if amt > 0 else 'SHORT'
                pnl = float(pos['unRealizedProfit'])

                try:
                    if amt > 0:
                        result = await self.order_executor.close_long(symbol)
                    else:
                        result = await self.order_executor.close_short(symbol)

                    status = "+" if pnl > 0 else ""
                    if result.success:
                        logger.info(f"  Closed {side} {symbol} | PnL: ${status}{pnl:.2f}")
                    else:
                        logger.error(f"  FAILED {symbol}: {result.error}")
                except Exception as e:
                    logger.error(f"  ERROR {symbol}: {e}")

                await asyncio.sleep(0.1)

            logger.info("All positions closed!")

        except Exception as e:
            logger.error(f"Error closing positions: {e}")

    async def initialize(self):
        """Initialize the bot"""
        logger.info("=" * 60)
        logger.info("INITIALIZING MACRO INDEX BOT")
        logger.info("=" * 60)

        # Initialize data feed
        await self.data_feed.initialize()
        logger.info("Connected to Binance")

        # CLOSE ALL EXISTING POSITIONS FOR FRESH START
        await self.close_all_positions()

        # Initialize macro indicator
        self.macro_indicator = MacroIndicator(self.data_feed, self.config)

        # Get whitelisted symbols from config
        if hasattr(PairFilterConfig, 'ALLOWED_COINS') and PairFilterConfig.ALLOWED_COINS:
            self.whitelisted_symbols = list(PairFilterConfig.ALLOWED_COINS)
            logger.info(f"Using {len(self.whitelisted_symbols)} whitelisted coins")
        else:
            # Fallback to pair filter
            await self.pair_filter.initialize()
            self.whitelisted_symbols = list(self.pair_filter.pairs.keys())
            logger.info(f"Loaded {len(self.whitelisted_symbols)} trading pairs")

        # Initialize position tracker
        await self.position_tracker.initialize()
        logger.info("Position tracker ready")

        # Get starting balance
        balance = await self.data_feed.get_account_balance()
        profit_tracker.set_start_balance(balance)
        logger.info(f"Starting balance: ${balance:.2f}")

        logger.info("=" * 60)
        logger.info("MACRO STRATEGY CONFIG:")
        logger.info(f"  Coins: {len(self.whitelisted_symbols)}")
        logger.info(f"  Leverage: {self.config.LEVERAGE}x")
        logger.info(f"  Stop Loss: {self.config.STOP_LOSS_PERCENT}%")
        logger.info(f"  Take Profit: {self.config.TAKE_PROFIT_PERCENT}%")
        logger.info(f"  Long Trigger: Score >= {self.config.LONG_TRIGGER_SCORE}")
        logger.info(f"  Short Trigger: Score <= {self.config.SHORT_TRIGGER_SCORE}")
        logger.info("=" * 60)

    async def start(self):
        """Start the bot"""
        self._running = True
        logger.info("MACRO INDEX BOT STARTED")

        # Start macro calculation and monitor loops
        self._macro_task = asyncio.create_task(self._macro_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """Stop the bot"""
        self._running = False
        logger.info("Stopping bot...")

        if self._macro_task:
            self._macro_task.cancel()
        if self._monitor_task:
            self._monitor_task.cancel()

        # Print final report
        profit_tracker.print_report()

    async def _macro_loop(self):
        """Main loop - calculate macro indicator and trade"""
        logger.info("Macro calculation loop started")

        while self._running:
            try:
                # Calculate macro score across all whitelisted coins
                score = await self.macro_indicator.calculate(self.whitelisted_symbols)

                # Log current state periodically
                logger.debug(f"Macro: {score.direction.value} | Score: {score.total_score} | "
                            f"Up: {score.coins_up} Down: {score.coins_down} | "
                            f"Avg Vel: {score.avg_velocity:.2f}%")

                # Check for direction change
                if score.direction != self.current_direction:
                    await self._handle_direction_change(score)

                await asyncio.sleep(self.config.SCAN_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Macro loop error: {e}")
                await asyncio.sleep(5)

    async def _handle_direction_change(self, score):
        """Handle when macro direction changes"""
        old_direction = self.current_direction
        new_direction = score.direction

        logger.info(f"{'='*60}")
        logger.info(f"MACRO DIRECTION CHANGE: {old_direction.value} -> {new_direction.value}")
        logger.info(f"{'='*60}")

        # Close existing positions if we had any
        if old_direction != MacroDirection.FLAT:
            await self._close_all_positions_for_direction(old_direction.value)

        # Open new positions if not flat
        if new_direction != MacroDirection.FLAT:
            await self._open_all_positions(new_direction.value)

        self.current_direction = new_direction

    async def _close_all_positions_for_direction(self, direction: str):
        """Close all positions for a given direction"""
        logger.info(f"Closing all {direction} positions...")

        positions = self.position_tracker.get_all_positions()
        closed = 0

        for symbol, position in positions.items():
            if position.direction == direction:
                try:
                    if direction == "LONG":
                        result = await self.order_executor.close_long(symbol)
                    else:
                        result = await self.order_executor.close_short(symbol)

                    if result.success:
                        closed += 1
                        # Calculate PnL
                        current_price = self.data_feed.get_current_price(symbol) or position.entry_price
                        if direction == "LONG":
                            pnl_pct = ((current_price - position.entry_price) / position.entry_price) * 100
                        else:
                            pnl_pct = ((position.entry_price - current_price) / position.entry_price) * 100

                        pnl_usd = position.margin * (pnl_pct / 100) * self.config.LEVERAGE
                        profit_tracker.record_exit(
                            symbol=symbol,
                            exit_price=current_price,
                            exit_reason="macro_flip",
                            pnl_percent=pnl_pct * self.config.LEVERAGE,
                            pnl_usd=pnl_usd,
                            peak_profit=0
                        )

                except Exception as e:
                    logger.error(f"Error closing {symbol}: {e}")

                await asyncio.sleep(0.05)  # Small delay between closes

        logger.info(f"Closed {closed} {direction} positions")

    async def _open_all_positions(self, direction: str):
        """Open positions on all whitelisted coins"""
        logger.info(f"Opening {direction} positions on {len(self.whitelisted_symbols)} coins...")

        # Get available balance
        balance = await self.data_feed.get_account_balance()

        # Calculate margin per position (equal weight)
        margin_per_position = balance / len(self.whitelisted_symbols)
        margin_per_position = max(margin_per_position, 1.0)  # Minimum $1

        opened = 0
        failed = 0

        for symbol in self.whitelisted_symbols:
            try:
                # Get current price for SL/TP calculation
                ticker = await self.data_feed.get_ticker(symbol)
                if not ticker:
                    failed += 1
                    continue

                entry_price = ticker.price

                # Calculate SL price
                if direction == "LONG":
                    sl_price = entry_price * (1 - self.config.STOP_LOSS_PERCENT / 100)
                    result = await self.order_executor.open_long(
                        symbol=symbol,
                        margin=margin_per_position,
                        leverage=self.config.LEVERAGE,
                        stop_loss=sl_price
                    )
                else:  # SHORT
                    sl_price = entry_price * (1 + self.config.STOP_LOSS_PERCENT / 100)
                    result = await self.order_executor.open_short(
                        symbol=symbol,
                        margin=margin_per_position,
                        leverage=self.config.LEVERAGE,
                        stop_loss=sl_price
                    )

                if result.success:
                    opened += 1
                    profit_tracker.record_entry(
                        symbol=symbol,
                        direction=direction,
                        entry_price=result.entry_price,
                        leverage=self.config.LEVERAGE,
                        margin=margin_per_position,
                        velocity=0
                    )
                else:
                    failed += 1
                    logger.debug(f"Failed to open {symbol}: {result.error}")

            except Exception as e:
                failed += 1
                logger.debug(f"Error opening {symbol}: {e}")

            await asyncio.sleep(0.05)  # Small delay between orders

        logger.info(f"Opened {opened}/{len(self.whitelisted_symbols)} {direction} positions (failed: {failed})")

    async def _monitor_loop(self):
        """Monitor open positions for SL/TP exits"""
        logger.info("Position monitor loop started")

        while self._running:
            try:
                positions = self.position_tracker.get_all_positions()

                for symbol, position in list(positions.items()):
                    try:
                        # Get current price
                        current_price = self.data_feed.get_current_price(symbol)
                        if not current_price:
                            await self.data_feed.get_klines(symbol, '1m', 5)
                            current_price = self.data_feed.get_current_price(symbol)

                        if not current_price:
                            continue

                        # Check for SL/TP exit
                        exit_action = self.exit_manager.check_exit(
                            direction=position.direction,
                            entry_price=position.entry_price,
                            current_price=current_price
                        )

                        if exit_action:
                            await self._execute_exit(symbol, position, exit_action, current_price)

                    except Exception as e:
                        logger.debug(f"Error monitoring {symbol}: {e}")

                await asyncio.sleep(2)  # Check every 2 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(5)

    async def _execute_exit(self, symbol: str, position, exit_action: dict, current_price: float):
        """Execute an exit trade"""
        try:
            direction = position.direction
            entry_price = position.entry_price

            # Calculate PnL
            if direction == "LONG":
                pnl_pct = ((current_price - entry_price) / entry_price) * 100 * self.config.LEVERAGE
            else:
                pnl_pct = ((entry_price - current_price) / entry_price) * 100 * self.config.LEVERAGE

            pnl_usd = position.margin * (pnl_pct / 100)

            # Close position
            if direction == "LONG":
                result = await self.order_executor.close_long(symbol)
            else:
                result = await self.order_executor.close_short(symbol)

            if result.success:
                # Record in profit tracker
                profit_tracker.record_exit(
                    symbol=symbol,
                    exit_price=current_price,
                    exit_reason=exit_action['reason'],
                    pnl_percent=pnl_pct,
                    pnl_usd=pnl_usd,
                    peak_profit=0
                )

                status = "+" if pnl_usd > 0 else ""
                reason = exit_action['reason'].upper()
                logger.info(f"{reason}: {symbol} | PnL: ${status}{pnl_usd:.2f} ({pnl_pct:+.2f}%)")
            else:
                logger.error(f"Exit failed: {symbol} - {result.error}")

        except Exception as e:
            logger.error(f"Error executing exit: {e}")

    def get_status(self):
        """Get bot status"""
        positions = self.position_tracker.get_all_positions()
        metrics = profit_tracker.get_metrics()

        return {
            "running": self._running,
            "strategy": "macro_index",
            "direction": self.current_direction.value,
            "positions": len(positions),
            "coins": len(self.whitelisted_symbols),
            "total_trades": metrics.total_trades,
            "win_rate": f"{metrics.win_rate:.1f}%",
            "total_pnl": f"${metrics.total_pnl_usd:+.2f}",
            "start_balance": f"${profit_tracker.start_balance:.2f}"
        }


# FastAPI app
bot = None
_init_task = None


async def _initialize_bot():
    """Initialize bot in background so server can start accepting requests"""
    global bot
    try:
        await bot.initialize()
        await bot.start()
        logger.info("Bot initialization complete!")
    except Exception as e:
        logger.error(f"Bot initialization failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, _init_task
    bot = MacroIndexBot()
    # Start initialization in background - don't block server startup
    _init_task = asyncio.create_task(_initialize_bot())
    yield
    # Wait for init to complete before stopping
    if _init_task and not _init_task.done():
        _init_task.cancel()
    await bot.stop()


app = FastAPI(lifespan=lifespan, title="Macro Index Bot")


@app.get("/")
async def root():
    return {"status": "running", "strategy": "macro_index"}


@app.get("/health")
async def health():
    if bot:
        return {"status": "healthy", **bot.get_status()}
    return {"status": "initializing"}


@app.get("/metrics")
async def metrics():
    return profit_tracker.get_metrics().__dict__


@app.get("/report")
async def report():
    return {"report": profit_tracker.print_report()}


@app.get("/positions")
async def positions():
    if bot:
        return {"positions": [str(p) for p in bot.position_tracker.get_all_positions().values()]}
    return {"positions": []}


@app.get("/macro")
async def macro():
    """Get current macro indicator state"""
    if bot and bot.macro_indicator and bot.macro_indicator.last_score:
        score = bot.macro_indicator.last_score
        return {
            "direction": score.direction.value,
            "total_score": score.total_score,
            "majority_score": score.majority_score,
            "leader_score": score.leader_score,
            "velocity_score": score.velocity_score,
            "coins_up": score.coins_up,
            "coins_down": score.coins_down,
            "avg_velocity": f"{score.avg_velocity:.2f}%",
            "leader_velocity": f"{score.leader_velocity:.2f}%"
        }
    return {"status": "calculating..."}


if __name__ == "__main__":
    # Create logs directory
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    logger.info("=" * 60)
    logger.info("STARTING MACRO INDEX BOT")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=PORT)
