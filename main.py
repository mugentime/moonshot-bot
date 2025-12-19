"""
MACRO INDEX BOT - 24H TIMEFRAME
Trade all whitelisted coins in same direction based on 24H macro indicator.

Strategy:
- Uses 24-HOUR price changes (NOT 5-minute noise) for stable trend detection
- Calculate macro score from majority vote + leader-follower + aggregate velocity
- Score >= +1 → LONG all coins
- Score <= -1 → SHORT all coins
- 1 HOUR COOLDOWN between direction changes to prevent whipsaws
- NO AUTOMATED EXITS: Positions held indefinitely until manual close or direction change
"""
import asyncio
import sys
import os
import time

# Fix Windows console encoding for emoji support
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from loguru import logger
import uvicorn

from config import PORT, LOG_LEVEL, PairFilterConfig
from src import DataFeed, PairFilter, PositionTracker, OrderExecutor
from src.macro_strategy import MacroIndicator, MacroConfig, MacroDirection
from src.profit_tracker import profit_tracker
from src.tp_tracker import tp_tracker
from src.exit_tracker import exit_tracker
from src.fee_tracker import fee_tracker

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
    - Calculates composite macro indicator across all whitelisted coins
    - Opens positions on ALL coins in same direction
    - NO AUTOMATED EXITS: Positions held indefinitely until manual close
    - NO Take Profit or Stop Loss logic
    """

    def __init__(self):
        self.config = MacroConfig()
        self.data_feed = DataFeed()
        self.pair_filter = PairFilter(self.data_feed)
        self.position_tracker = PositionTracker(self.data_feed)
        self.order_executor = OrderExecutor(self.data_feed)
        self.macro_indicator = None  # Initialize after data_feed

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

    async def _cancel_all_stop_orders(self):
        """
        Cancel all STOP_MARKET orders to ensure software SL has exclusive control.
        This prevents leftover exchange-side stop orders from earlier code versions
        from triggering at different thresholds than the current software SL.
        """
        try:
            # Get all open orders across all symbols
            open_orders = await self.data_feed.client.futures_get_open_orders()

            # Filter for stop orders
            stop_orders = [o for o in open_orders if o['type'] == 'STOP_MARKET']

            if stop_orders:
                logger.info(f"🧹 Found {len(stop_orders)} STOP_MARKET orders to cancel...")
                cancelled = 0
                for order in stop_orders:
                    try:
                        await self.data_feed.client.futures_cancel_order(
                            symbol=order['symbol'],
                            orderId=order['orderId']
                        )
                        cancelled += 1
                        logger.debug(f"  Cancelled stop order for {order['symbol']}")
                    except Exception as e:
                        logger.warning(f"  Failed to cancel stop order for {order['symbol']}: {e}")

                logger.info(f"✅ Cancelled {cancelled}/{len(stop_orders)} stop orders - software SL now in control")
            else:
                logger.info("No leftover STOP_MARKET orders found")

        except Exception as e:
            logger.error(f"Error cancelling stop orders: {e}")

    async def initialize(self):
        """Initialize the bot"""
        logger.info("=" * 60)
        logger.info("INITIALIZING MACRO INDEX BOT")
        logger.info("=" * 60)

        try:
            # Initialize data feed
            await self.data_feed.initialize()
            logger.info("Connected to Binance")
        except Exception as e:
            logger.error(f"Failed to initialize data feed: {e}")
            raise  # Can't continue without data feed

        # NOTE: Positions persist across restarts - no longer closing on startup

        # Initialize macro indicator
        self.macro_indicator = MacroIndicator(self.data_feed, self.config)

        # Get whitelisted symbols from config
        if hasattr(PairFilterConfig, 'ALLOWED_COINS') and PairFilterConfig.ALLOWED_COINS:
            self.whitelisted_symbols = list(PairFilterConfig.ALLOWED_COINS)
            logger.info(f"Using {len(self.whitelisted_symbols)} whitelisted coins")
        else:
            # Fallback to pair filter
            try:
                await self.pair_filter.initialize()
                self.whitelisted_symbols = list(self.pair_filter.pairs.keys())
                logger.info(f"Loaded {len(self.whitelisted_symbols)} trading pairs")
            except Exception as e:
                logger.error(f"Failed to initialize pair filter: {e}")
                raise

        # Initialize position tracker
        try:
            await self.position_tracker.initialize()
            logger.info("Position tracker ready")
        except Exception as e:
            logger.error(f"Failed to initialize position tracker: {e}")
            # Continue without position tracker - will use Binance directly

        # Initialize TP tracker with Redis
        try:
            await tp_tracker.initialize()
            logger.info("TP tracker ready")
        except Exception as e:
            logger.warning(f"Failed to initialize TP tracker: {e}")
            # Non-critical - can continue

        # Initialize exit tracker with Redis
        try:
            await exit_tracker.initialize()
            logger.info("Exit tracker ready")
        except Exception as e:
            logger.warning(f"Failed to initialize exit tracker: {e}")
            # Non-critical - can continue

        # Initialize fee tracker with data feed for API access
        try:
            fee_tracker.data_feed = self.data_feed
            await fee_tracker.start_background_updates()
            logger.info("Fee tracker ready")
        except Exception as e:
            logger.warning(f"Failed to initialize fee tracker: {e}")
            # Non-critical - can continue

        # Cancel any leftover STOP_MARKET orders from previous code versions
        # This ensures software SL has exclusive control
        try:
            await self._cancel_all_stop_orders()
        except Exception as e:
            logger.warning(f"Failed to cancel stop orders: {e}")
            # Non-critical - can continue

        # Get starting balance
        try:
            balance = await self.data_feed.get_account_balance()
            profit_tracker.set_start_balance(balance)
            logger.info(f"Starting balance: ${balance:.2f}")
        except Exception as e:
            logger.warning(f"Failed to get starting balance: {e}")
            # Non-critical - set default
            profit_tracker.set_start_balance(0)

        logger.info("=" * 60)
        logger.info("MACRO STRATEGY CONFIG (24H TIMEFRAME):")
        logger.info(f"  Coins: {len(self.whitelisted_symbols)}")
        logger.info(f"  Leverage: {self.config.LEVERAGE}x")
        logger.info(f"  Timeframe: 24H (stable trend detection)")
        logger.info(f"  Direction Cooldown: {self.config.DIRECTION_CHANGE_COOLDOWN_SECONDS}s (1 hour)")
        logger.info(f"  EXIT STRATEGY: NO AUTOMATED TP/SL - Positions held indefinitely")
        logger.info(f"  Long Trigger: Score >= {self.config.LONG_TRIGGER_SCORE}")
        logger.info(f"  Short Trigger: Score <= {self.config.SHORT_TRIGGER_SCORE}")
        logger.info("=" * 60)

    def _task_exception_handler(self, task: asyncio.Task):
        """Handle exceptions from background tasks to prevent silent failures"""
        try:
            task.result()  # This will raise if task failed
        except asyncio.CancelledError:
            pass  # Expected during shutdown
        except Exception as e:
            logger.exception(f"CRITICAL: Background task '{task.get_name()}' failed with exception: {e}")
            # Log the full traceback for debugging
            import traceback
            logger.error(f"Task traceback:\n{traceback.format_exc()}")
            # Optionally: trigger graceful shutdown or restart the task
            logger.error("Bot may be in unstable state - manual restart recommended")

    async def start(self):
        """Start the bot"""
        self._running = True
        logger.info("MACRO INDEX BOT STARTED")

        # Start WebSocket ticker stream for real-time prices
        try:
            await self.data_feed.start_ticker_stream()
            logger.info("Ticker stream started - Global TP monitoring active")
        except Exception as e:
            logger.error(f"Failed to start ticker stream: {e}")
            logger.warning("Bot will continue without real-time price stream")

        # Start macro calculation and monitor loops with exception handlers
        self._macro_task = asyncio.create_task(self._macro_loop(), name="macro_loop")
        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="monitor_loop")

        # Add exception callbacks to catch and log failures
        self._macro_task.add_done_callback(self._task_exception_handler)
        self._monitor_task.add_done_callback(self._task_exception_handler)

    async def stop(self):
        """Stop the bot"""
        self._running = False
        logger.info("Stopping bot...")

        # Cancel background tasks
        if self._macro_task:
            self._macro_task.cancel()
        if self._monitor_task:
            self._monitor_task.cancel()

        # Stop fee tracker background updates
        await fee_tracker.stop_background_updates()

        # Close all Redis connections to prevent leaks
        logger.info("Closing tracker Redis connections...")
        try:
            await self.position_tracker.close()
            await tp_tracker.close()
            await exit_tracker.close()
            await fee_tracker.close()
            logger.info("All tracker connections closed")
        except Exception as e:
            logger.error(f"Error closing tracker connections: {e}")

        # Stop WebSocket data feed
        try:
            await self.data_feed.close()
            logger.info("WebSocket data feed closed")
        except Exception as e:
            logger.error(f"Error closing data feed: {e}")

        # Print final report
        profit_tracker.print_report()

    async def _macro_loop(self):
        """Main loop - calculate macro indicator and trade"""
        logger.info("Macro calculation loop started (24H timeframe)")

        while self._running:
            try:
                # Calculate macro score across all whitelisted coins
                logger.info("Calculating 24H macro score...")
                score = await self.macro_indicator.calculate(self.whitelisted_symbols)

                # Log current state - INFO level so we can see it
                logger.info(f"24H MACRO: {score.direction.value} | Score: {score.total_score} | "
                            f"Up: {score.coins_up} Down: {score.coins_down} | "
                            f"Avg 24h: {score.avg_velocity:.2f}%")

                # Check for direction change
                if score.direction != self.current_direction:
                    try:
                        await self._handle_direction_change(score)
                    except Exception as e:
                        logger.error(f"Error handling direction change: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                else:
                    # RECOVERY: If direction is LONG/SHORT but we have no positions, re-open them
                    # This handles the case where positions were manually closed
                    if score.direction != MacroDirection.FLAT:
                        try:
                            await self._ensure_positions_open(score.direction.value)
                        except Exception as e:
                            logger.error(f"Error ensuring positions open: {e}")

                await asyncio.sleep(self.config.SCAN_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Macro loop error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)

    async def _handle_direction_change(self, score):
        """
        MANUAL EXIT ONLY - NO AUTOMATIC POSITION CLOSING
        - Opens positions when macro signals LONG or SHORT from FLAT only
        - NEVER closes positions automatically on direction change
        - All exits are manual via close-all endpoint
        """
        old_direction = self.current_direction
        new_direction = score.direction

        # ONLY open positions when going from FLAT to a direction
        if old_direction == MacroDirection.FLAT and new_direction != MacroDirection.FLAT:
            logger.info(f"{'='*60}")
            logger.info(f"📈 MACRO SIGNAL: {new_direction.value}")
            logger.info(f"Opening {new_direction.value} positions on all symbols")
            logger.info(f"{'='*60}")
            await self._open_all_positions(new_direction.value)
            self.current_direction = new_direction

        # ALL OTHER CASES: Log but DO NOT close positions
        elif old_direction != MacroDirection.FLAT and new_direction != old_direction:
            # Direction changed but we IGNORE it - no automatic closing
            logger.info(f"📊 MACRO CHANGED: {old_direction.value} → {new_direction.value} (IGNORED - manual exit only)")
            # DO NOT update direction - keep positions open

        else:
            # Same direction or FLAT → FLAT
            self.current_direction = new_direction

    async def _close_all_positions_for_direction(self, direction: str):
        """Close all positions for a given direction - CRITICAL FIX: Query Binance directly"""
        logger.info(f"Closing all {direction} positions...")

        # CRITICAL FIX: Query Binance DIRECTLY instead of Redis cache
        # Redis cache may be stale, causing positions to be missed during macro flip
        try:
            binance_positions = await self.data_feed.client.futures_position_information()
            open_positions = [p for p in binance_positions if float(p['positionAmt']) != 0]
        except Exception as e:
            logger.error(f"Failed to fetch positions from Binance: {e}")
            # Fallback to Redis if Binance fails (better than nothing)
            open_positions = []
            positions = self.position_tracker.get_all_positions()
            for pos in positions:
                open_positions.append({
                    'symbol': pos.symbol,
                    'positionAmt': str(pos.quantity) if pos.direction == "LONG" else str(-pos.quantity),
                    'entryPrice': str(pos.entry_price)
                })

        closed = 0
        closed_positions_data = []
        total_pnl = 0

        # Get balance BEFORE closing for tracking
        balance_before = await self._get_wallet_balance()

        for position in open_positions:
            # Filter by direction (positionAmt > 0 = LONG, < 0 = SHORT)
            position_amt = float(position['positionAmt'])
            position_direction = "LONG" if position_amt > 0 else "SHORT"

            if position_direction == direction:
                symbol = position['symbol']
                entry_price = float(position['entryPrice'])

                try:
                    if direction == "LONG":
                        result = await self.order_executor.close_long(symbol)
                    else:
                        result = await self.order_executor.close_short(symbol)

                    if result.success:
                        closed += 1
                        # Calculate PnL using safe price fetch
                        current_price = await self.data_feed.get_current_price_safe(symbol)
                        if current_price is None:
                            logger.warning(f"No price for {symbol} after close, using entry price for PnL calc")
                            current_price = entry_price

                        if direction == "LONG":
                            pnl_pct = ((current_price - entry_price) / entry_price) * 100
                        else:
                            pnl_pct = ((entry_price - current_price) / entry_price) * 100

                        # Get margin from Redis tracker (if available) or estimate from position
                        tracked_position = self.position_tracker.get_position(symbol)
                        if tracked_position:
                            margin = tracked_position.margin
                        else:
                            # Estimate margin from position quantity and entry price
                            quantity = abs(position_amt)
                            notional = quantity * entry_price
                            margin = notional / self.config.LEVERAGE

                        pnl_usd = margin * (pnl_pct / 100) * self.config.LEVERAGE
                        total_pnl += pnl_usd

                        # Record in profit tracker
                        profit_tracker.record_exit(
                            symbol=symbol,
                            exit_price=current_price,
                            exit_reason="macro_flip",
                            pnl_percent=pnl_pct * self.config.LEVERAGE,
                            pnl_usd=pnl_usd,
                            peak_profit=0
                        )

                        # Store position data for exit tracker
                        closed_positions_data.append({
                            'symbol': symbol,
                            'direction': direction,
                            'entry_price': entry_price,
                            'exit_price': current_price,
                            'pnl_usd': pnl_usd,
                            'pnl_percent': pnl_pct,
                            'margin': margin
                        })

                        # Record individual fee
                        await fee_tracker.record_trade_fee(
                            symbol=symbol,
                            side=direction,
                            action="CLOSE",
                            notional_value=margin * self.config.LEVERAGE
                        )

                except Exception as e:
                    logger.error(f"Error closing {symbol}: {e}")

                await asyncio.sleep(0.05)  # Small delay between closes

        # Get balance AFTER closing
        balance_after = await self._get_wallet_balance()
        actual_pnl = balance_after - balance_before

        # Record in exit tracker as MACRO_FLIP event
        if closed > 0:
            exit_tracker.record_macro_flip(
                trigger_reason=f"{direction} → Direction Change",
                balance_before=balance_before,
                balance_after=balance_after,
                profit_usd=actual_pnl,
                positions_closed=closed,
                positions=closed_positions_data
            )

        logger.info(f"Closed {closed} {direction} positions (PnL: ${total_pnl:+.2f}, Actual: ${actual_pnl:+.2f})")


    async def _open_all_positions(self, direction: str):
        """Open positions on all whitelisted coins"""
        logger.info(f"Opening {direction} positions on {len(self.whitelisted_symbols)} coins...")

        # Get available balance
        balance = await self.data_feed.get_account_balance()

        # Position limit removed - bot will attempt to open all whitelisted symbols
        MIN_MARGIN = 2.0  # Minimum $2 per position (with 5x leverage = $10 notional)

        # Use ALL whitelisted symbols without balance-based limiting
        symbols_to_trade = self.whitelisted_symbols
        logger.info(f"🚀 Opening positions on ALL {len(symbols_to_trade)} whitelisted symbols (limit removed)")

        # Calculate margin per position (equal weight across affordable positions)
        margin_per_position = balance / len(symbols_to_trade)
        margin_per_position = max(margin_per_position, MIN_MARGIN)  # Ensure minimum

        total_margin_needed = margin_per_position * len(symbols_to_trade)

        logger.info(f"Balance: ${balance:.2f} | Margin per position: ${margin_per_position:.2f} | Total: ${total_margin_needed:.2f}")

        opened = 0
        failed = 0

        for symbol in symbols_to_trade:
            try:
                # Open position (exits handled by Global TP only)
                if direction == "LONG":
                    result = await self.order_executor.open_long(
                        symbol=symbol,
                        margin=margin_per_position,
                        leverage=self.config.LEVERAGE
                    )
                else:  # SHORT
                    result = await self.order_executor.open_short(
                        symbol=symbol,
                        margin=margin_per_position,
                        leverage=self.config.LEVERAGE
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

                    # Record fee for position open
                    notional = margin_per_position * self.config.LEVERAGE
                    await fee_tracker.record_trade_fee(
                        symbol=symbol,
                        side=direction,
                        action="OPEN",
                        notional_value=notional,
                        order_id=result.order_id
                    )
                else:
                    failed += 1
                    logger.debug(f"Failed to open {symbol}: {result.error}")

            except Exception as e:
                failed += 1
                logger.debug(f"Error opening {symbol}: {e}")

            await asyncio.sleep(0.05)  # Small delay between orders

        logger.info(f"Opened {opened}/{len(self.whitelisted_symbols)} {direction} positions (failed: {failed})")

    async def _ensure_positions_open(self, direction: str):
        """
        RECOVERY: Check if positions are actually open on Binance.
        If not, re-open them. This handles manual closes or crashes.
        """
        try:
            # Get actual positions from Binance
            binance_positions = await self.data_feed.client.futures_position_information()
            open_positions = [p for p in binance_positions if float(p['positionAmt']) != 0]

            # If we think we should have positions but Binance shows none, re-open
            if not open_positions:
                logger.warning(f"RECOVERY: No positions on Binance but direction is {direction}. Re-opening...")
                await self._open_all_positions(direction)
            else:
                # Check if positions match expected direction
                expected_side = 1 if direction == "LONG" else -1
                wrong_direction = [p for p in open_positions
                                   if (float(p['positionAmt']) > 0) != (expected_side > 0)]
                if wrong_direction:
                    logger.warning(f"RECOVERY: Found {len(wrong_direction)} positions in wrong direction")

        except Exception as e:
            logger.error(f"Error in position recovery check: {e}")

    async def _monitor_loop(self):
        """Monitor open positions - NO TP/SL (positions held indefinitely)"""
        logger.info("Position monitor loop started - NO AUTOMATED EXITS")
        logger.info("Positions will be held until manual close or macro direction change")
        check_count = 0

        while self._running:
            try:
                # Sync with exchange every minute to keep position tracking accurate
                if check_count % 12 == 0:
                    await self.position_tracker.sync_with_exchange()

                positions = self.position_tracker.get_all_positions()
                check_count += 1

                if not positions:
                    await asyncio.sleep(5)
                    continue

                # Calculate and log PnL for informational purposes only
                total_pnl = 0
                total_margin = 0
                positions_with_price = 0

                for p in positions:
                    price = await self.data_feed.get_current_price_safe(p.symbol, max_age_seconds=10.0)
                    if price is None:
                        continue

                    positions_with_price += 1
                    pos_margin = p.margin if p.margin > 0 else (p.quantity * p.entry_price) / self.config.LEVERAGE

                    if p.direction == "LONG":
                        pnl = ((price - p.entry_price) / p.entry_price) * pos_margin * self.config.LEVERAGE
                    else:
                        pnl = ((p.entry_price - price) / p.entry_price) * pos_margin * self.config.LEVERAGE
                    total_pnl += pnl
                    total_margin += pos_margin

                # Log PnL every minute for monitoring only (no automated action)
                if total_margin > 0 and check_count % 12 == 0:
                    wallet_balance = await self._get_wallet_balance()
                    global_pnl_pct = (total_pnl / wallet_balance) * 100 if wallet_balance > 0 else 0
                    logger.info(f"Portfolio PnL: {global_pnl_pct:+.2f}% (${total_pnl:+.2f} / ${wallet_balance:.2f} balance) | {positions_with_price}/{len(positions)} positions")

                await asyncio.sleep(5)  # Check every 5 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(5)




    async def _get_wallet_balance(self) -> float:
        """Get current account equity (totalMarginBalance) from Binance"""
        try:
            account = await self.data_feed.client.futures_account()
            # Use totalMarginBalance (Account Equity) - works correctly with multi-asset accounts
            return float(account.get('totalMarginBalance', 0))
        except Exception as e:
            logger.error(f"Error getting wallet balance: {e}")
        return 0.0

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


def _init_task_exception_handler(task: asyncio.Task):
    """Handle exceptions from initialization task"""
    try:
        task.result()  # This will raise if task failed
    except asyncio.CancelledError:
        logger.info("Bot initialization cancelled during shutdown")
    except Exception as e:
        logger.exception(f"CRITICAL: Bot initialization failed with exception: {e}")
        import traceback
        logger.error(f"Initialization traceback:\n{traceback.format_exc()}")
        logger.error("Bot failed to start - server is running but bot is inactive")


async def _initialize_bot():
    """Initialize bot in background so server can start accepting requests"""
    global bot
    try:
        await bot.initialize()
        await bot.start()
        logger.info("Bot initialization complete!")
    except Exception as e:
        logger.exception(f"Bot initialization failed: {e}")
        raise  # Re-raise so the task callback can catch it


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, _init_task
    bot = MacroIndexBot()
    # Start initialization in background with exception handler
    _init_task = asyncio.create_task(_initialize_bot(), name="bot_initialization")
    _init_task.add_done_callback(_init_task_exception_handler)
    yield
    # Wait for init to complete before stopping
    if _init_task and not _init_task.done():
        _init_task.cancel()
        try:
            await _init_task
        except asyncio.CancelledError:
            pass
    if bot:
        await bot.stop()


app = FastAPI(lifespan=lifespan, title="Macro Index Bot")


@app.get("/")
async def root():
    return {"status": "running", "strategy": "macro_index"}


@app.get("/health")
async def health():
    """Health endpoint - always returns 200 for Railway healthcheck"""
    if bot and bot._running:
        return {"status": "healthy", **bot.get_status()}
    # Return healthy during initialization so Railway healthcheck passes
    return {"status": "healthy", "initializing": True, "strategy": "macro_index"}


@app.get("/metrics")
async def metrics():
    return profit_tracker.get_metrics().__dict__


@app.get("/debug-sync")
async def debug_sync():
    """Debug endpoint - force sync and show position comparison"""
    try:
        # Get positions from Binance directly
        binance_positions = await bot.data_feed.client.futures_position_information()
        binance_open = [p for p in binance_positions if float(p['positionAmt']) != 0]

        # Get positions from tracker BEFORE sync
        tracker_before = [p.symbol for p in bot.position_tracker.get_all_positions()]

        # Force sync
        await bot.position_tracker.sync_with_exchange()

        # Get positions from tracker AFTER sync
        tracker_after = [p.symbol for p in bot.position_tracker.get_all_positions()]

        return {
            "binance_positions": len(binance_open),
            "binance_symbols": [p['symbol'] for p in binance_open],
            "tracker_before_sync": tracker_before,
            "tracker_after_sync": tracker_after,
            "sync_worked": len(tracker_after) == len(binance_open)
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/report")
async def report():
    return {"report": profit_tracker.print_report()}


@app.get("/positions", response_class=HTMLResponse)
async def positions():
    """HTML dashboard showing all positions"""
    try:
        # Fetch fresh data from Binance
        positions_data = await bot.data_feed.client.futures_position_information()
        open_positions = [p for p in positions_data if float(p['positionAmt']) != 0]

        account = await bot.data_feed.client.futures_account()
        wallet = float(account['totalWalletBalance'])
        margin = float(account['totalMarginBalance'])
        available = float(account['availableBalance'])

        # Process positions
        rows = ""
        total_pnl = 0
        total_margin = 0
        winners = 0

        position_list = []
        for p in open_positions:
            amt = float(p['positionAmt'])
            entry = float(p['entryPrice'])
            mark = float(p['markPrice'])
            pnl = float(p['unRealizedProfit'])
            leverage = int(p['leverage'])
            liq = float(p['liquidationPrice'])

            notional = abs(amt * entry)
            pos_margin = notional / leverage
            side = 'LONG' if amt > 0 else 'SHORT'
            roi = ((mark - entry) / entry * 100) if side == 'LONG' else ((entry - mark) / entry * 100)

            position_list.append({'symbol': p['symbol'], 'side': side, 'roi': roi, 'pnl': pnl, 'margin': pos_margin, 'liq': liq})
            total_pnl += pnl
            total_margin += pos_margin
            if roi >= 0: winners += 1

        position_list.sort(key=lambda x: x['roi'], reverse=True)

        for p in position_list:
            color = "#22c55e" if p['roi'] >= 0 else "#ef4444"
            emoji = "🚀" if p['roi'] >= 5 else "🟢" if p['roi'] >= 2 else "🟡" if p['roi'] >= 0 else "🟠" if p['roi'] > -5 else "🔴"
            rows += f'<tr><td>{emoji} {p["symbol"]}</td><td>{p["side"]}</td><td style="color:{color};font-weight:bold">{p["roi"]:+.2f}%</td><td style="color:{color}">${p["pnl"]:+.2f}</td><td>${p["margin"]:.2f}</td><td style="font-size:11px">{p["liq"]:.6f}</td></tr>'

        if not position_list:
            rows = '<tr><td colspan="6" style="padding:40px;text-align:center;color:#888">No open positions</td></tr>'

        losers = len(position_list) - winners
        portfolio_roi = (total_pnl / total_margin * 100) if total_margin > 0 else 0
        margin_usage = ((margin - available) / margin * 100) if margin > 0 else 0
        pnl_color = "#22c55e" if total_pnl >= 0 else "#ef4444"
        health_color = "#22c55e" if margin_usage < 70 else "#eab308" if margin_usage < 90 else "#ef4444"
        health_text = "HEALTHY" if margin_usage < 70 else "MODERATE" if margin_usage < 90 else "HIGH RISK"

        # TP is disabled - show N/A
        tp_pct = "N/A (disabled)"

        html = f'''<!DOCTYPE html><html><head><title>Position Monitor</title><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="10"><style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e5e5;padding:20px}}.container{{max-width:1200px;margin:0 auto}}.header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:15px;border-bottom:1px solid #333}}.title{{font-size:24px;font-weight:600}}.refresh{{color:#666;font-size:12px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:15px;margin-bottom:20px}}.card{{background:#171717;border-radius:8px;padding:16px;border:1px solid #262626}}.card-label{{color:#888;font-size:12px;margin-bottom:4px}}.card-value{{font-size:24px;font-weight:600}}table{{width:100%;border-collapse:collapse;background:#171717;border-radius:8px;overflow:hidden}}th{{background:#262626;padding:12px;text-align:left;font-weight:500;font-size:13px;color:#888}}td{{padding:12px;border-bottom:1px solid #333}}.status{{display:inline-block;padding:4px 12px;border-radius:4px;font-size:12px;font-weight:600}}.nav{{margin-bottom:20px}}.nav a{{color:#3b82f6;text-decoration:none;margin-right:15px}}.nav a:hover{{text-decoration:underline}}</style></head><body><div class="container"><div class="nav"><a href="/positions">📊 Positions</a><a href="/exits">📋 Exits</a><a href="/fees">💰 Fees</a><a href="/health">❤️ Health</a></div><div class="header"><div class="title">📊 Position Monitor</div><div class="refresh">Auto-refresh: 10s | TP: {tp_pct}%</div></div><div class="cards"><div class="card"><div class="card-label">Positions</div><div class="card-value">{len(position_list)} <span style="font-size:14px;color:#888">({winners}W / {losers}L)</span></div></div><div class="card"><div class="card-label">Portfolio PnL</div><div class="card-value" style="color:{pnl_color}">${total_pnl:+.2f} <span style="font-size:14px">({portfolio_roi:+.1f}%)</span></div></div><div class="card"><div class="card-label">Account Equity</div><div class="card-value">${margin:.2f}</div></div><div class="card"><div class="card-label">Margin Usage</div><div class="card-value" style="color:{health_color}">{margin_usage:.1f}% <span class="status" style="background:{health_color}20;color:{health_color}">{health_text}</span></div></div></div><table><thead><tr><th>Symbol</th><th>Side</th><th>ROI</th><th>PnL</th><th>Margin</th><th>Liq Price</th></tr></thead><tbody>{rows}</tbody></table><div style="margin-top:20px;color:#666;font-size:12px;text-align:center">Available: ${available:.2f} | Margin: ${margin:.2f}</div></div></body></html>'''
        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error</h1><pre>{str(e)}</pre>")


@app.get("/tp-tracker", response_class=HTMLResponse)
async def tp_tracker_ui():
    """HTML dashboard showing Global TP tracker history"""
    try:
        from src.tp_tracker import tp_tracker
        from collections import defaultdict
        from datetime import datetime

        # Ensure initialized
        if not tp_tracker._initialized:
            await tp_tracker.initialize()

        stats = tp_tracker.get_stats()
        events = tp_tracker.events

        # Build event rows for tracked events
        rows = ""
        for event in reversed(events):  # Most recent first
            profit_color = "#22c55e" if event.profit_usd >= 0 else "#ef4444"
            emoji = "🎯" if event.profit_usd >= 0 else "❌"

            # Position details
            pos_details = ""
            for p in event.positions:
                p_color = "#22c55e" if p.get('pnl_usd', 0) >= 0 else "#ef4444"
                p_status = "WIN" if p.get('pnl_usd', 0) >= 0 else "LOSS"
                pos_details += f'<div style="font-size:11px;color:#888;padding:2px 0">{p.get("symbol", "N/A"):15} {p.get("direction", ""):5} <span style="color:{p_color}">${p.get("pnl_usd", 0):+.4f}</span> {p_status}</div>'

            if not pos_details:
                pos_details = '<div style="font-size:11px;color:#666">No position data</div>'

            rows += f'''<tr>
                <td>{emoji} {event.timestamp[:19]}</td>
                <td>{event.trigger_percent:.2f}%</td>
                <td>{event.threshold_percent:.2f}%</td>
                <td>${event.balance_before:.2f}</td>
                <td>${event.balance_after:.2f}</td>
                <td style="color:{profit_color};font-weight:bold">${event.profit_usd:+.2f}</td>
                <td>{event.positions_closed}</td>
                <td style="max-width:200px">{pos_details}</td>
            </tr>'''

        if not events:
            rows = '<tr><td colspan="8" style="padding:40px;text-align:center;color:#888">No Global TP events recorded yet</td></tr>'

        # Fetch last 3 batch closes from Binance (historical reference)
        history_rows = ""
        try:
            income = await bot.data_feed.client.futures_income_history(incomeType='REALIZED_PNL', limit=200)
            income = sorted(income, key=lambda x: int(x.get('time', 0)))

            # Group by minute
            by_minute = defaultdict(list)
            for i in income:
                minute = int(i.get('time', 0)) // 60000
                by_minute[minute].append(i)

            # Find batches with 3+ trades
            batches = []
            for minute, trades in by_minute.items():
                if len(trades) >= 3:
                    total_pnl = sum(float(t.get('income', 0)) for t in trades)
                    ts = datetime.fromtimestamp(minute * 60)
                    batches.append({'timestamp': ts, 'count': len(trades), 'pnl': total_pnl, 'trades': trades})

            batches.sort(key=lambda x: x['timestamp'], reverse=True)

            # Get current balance for calculating before/after
            acc = await bot.data_feed.client.futures_account()
            current_balance = float(acc['totalWalletBalance'])

            for batch in batches[:3]:  # Last 3
                batch_minute = int(batch['timestamp'].timestamp()) // 60
                income_after = sum(float(i.get('income', 0)) for i in income if int(i.get('time', 0)) // 60000 > batch_minute)
                balance_after = current_balance - income_after
                balance_before = balance_after - batch['pnl']

                profit_color = "#22c55e" if batch['pnl'] >= 0 else "#ef4444"
                emoji = "📜"

                # Position details
                pos_details = ""
                for t in batch['trades'][:5]:  # Show max 5
                    pnl = float(t.get('income', 0))
                    p_color = "#22c55e" if pnl >= 0 else "#ef4444"
                    pos_details += f'<div style="font-size:11px;color:#888;padding:2px 0">{t.get("symbol", "N/A")} <span style="color:{p_color}">${pnl:+.4f}</span></div>'
                if len(batch['trades']) > 5:
                    pos_details += f'<div style="font-size:11px;color:#666">+{len(batch["trades"])-5} more</div>'

                history_rows += f'''<tr style="opacity:0.7">
                    <td>{emoji} {batch['timestamp'].strftime('%Y-%m-%d %H:%M')}</td>
                    <td>-</td>
                    <td>-</td>
                    <td>${balance_before:.2f}</td>
                    <td>${balance_after:.2f}</td>
                    <td style="color:{profit_color};font-weight:bold">${batch['pnl']:+.2f}</td>
                    <td>{batch['count']}</td>
                    <td style="max-width:200px">{pos_details}</td>
                </tr>'''
        except Exception as e:
            history_rows = f'<tr><td colspan="8" style="color:#666">Could not load history: {e}</td></tr>'

        # Stats colors
        profit_color = "#22c55e" if stats['total_profit'] >= 0 else "#ef4444"
        win_color = "#22c55e" if stats.get('win_rate', 0) >= 50 else "#eab308" if stats.get('win_rate', 0) >= 30 else "#ef4444"
        storage_type = "Redis" if tp_tracker.redis else "File"

        html = f'''<!DOCTYPE html><html><head><title>Global TP Tracker</title><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30"><style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e5e5;padding:20px}}.container{{max-width:1400px;margin:0 auto}}.header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:15px;border-bottom:1px solid #333}}.title{{font-size:24px;font-weight:600}}.refresh{{color:#666;font-size:12px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:15px;margin-bottom:20px}}.card{{background:#171717;border-radius:8px;padding:16px;border:1px solid #262626}}.card-label{{color:#888;font-size:12px;margin-bottom:4px}}.card-value{{font-size:22px;font-weight:600}}table{{width:100%;border-collapse:collapse;background:#171717;border-radius:8px;overflow:hidden}}th{{background:#262626;padding:12px;text-align:left;font-weight:500;font-size:13px;color:#888}}td{{padding:12px;border-bottom:1px solid #333;vertical-align:top}}.nav{{margin-bottom:20px}}.nav a{{color:#3b82f6;text-decoration:none;margin-right:15px}}.nav a:hover{{text-decoration:underline}}.section-title{{font-size:18px;font-weight:600;margin:30px 0 15px;padding-top:20px;border-top:1px solid #333}}</style></head><body><div class="container">
        <div class="nav"><a href="/positions">📊 Positions</a><a href="/exits">📋 Exits</a><a href="/tp-tracker">🎯 TP Only</a><a href="/health">❤️ Health</a></div>
        <div class="header"><div class="title">🎯 Global Take Profit Tracker</div><div class="refresh">Auto-refresh: 30s | Storage: {storage_type}</div></div>
        <div class="cards">
            <div class="card"><div class="card-label">Total Events</div><div class="card-value">{stats['total_events']}</div></div>
            <div class="card"><div class="card-label">Total Profit</div><div class="card-value" style="color:{profit_color}">${stats['total_profit']:+.2f}</div></div>
            <div class="card"><div class="card-label">Avg Profit</div><div class="card-value">${stats['avg_profit']:+.2f}</div></div>
            <div class="card"><div class="card-label">Best TP</div><div class="card-value" style="color:#22c55e">${stats['best_tp']:+.2f}</div></div>
            <div class="card"><div class="card-label">Worst TP</div><div class="card-value" style="color:#ef4444">${stats['worst_tp']:+.2f}</div></div>
            <div class="card"><div class="card-label">Win Rate</div><div class="card-value" style="color:{win_color}">{stats.get('win_rate', 0):.1f}%</div></div>
            <div class="card"><div class="card-label">Avg Trigger</div><div class="card-value">{stats['avg_trigger_percent']:.2f}%</div></div>
            <div class="card"><div class="card-label">Avg Positions</div><div class="card-value">{stats['avg_positions']:.1f}</div></div>
        </div>
        <div class="section-title">🎯 Tracked Global TP Events</div>
        <table><thead><tr><th>Timestamp</th><th>Trigger %</th><th>Threshold</th><th>Balance Before</th><th>Balance After</th><th>Profit</th><th>Positions</th><th>Details</th></tr></thead><tbody>{rows}</tbody></table>
        <div class="section-title">📜 Recent Batch Closes (Last 3 from Binance)</div>
        <table><thead><tr><th>Timestamp</th><th>Trigger %</th><th>Threshold</th><th>Balance Before</th><th>Balance After</th><th>Profit</th><th>Positions</th><th>Details</th></tr></thead><tbody>{history_rows}</tbody></table>
        </div></body></html>'''
        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error</h1><pre>{str(e)}</pre>")


@app.get("/tp-tracker/json")
async def tp_tracker_json():
    """JSON API for Global TP tracker data"""
    try:
        from src.tp_tracker import tp_tracker
        from dataclasses import asdict

        # Ensure initialized
        if not tp_tracker._initialized:
            await tp_tracker.initialize()

        return {
            "stats": tp_tracker.get_stats(),
            "events": [asdict(e) for e in tp_tracker.events],
            "total_events": len(tp_tracker.events),
            "storage": "redis" if tp_tracker.redis else "file"
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/exits", response_class=HTMLResponse)
async def exits_ui():
    """HTML dashboard showing ALL exit events (Global TP ONLY - no SL)"""
    try:
        from src.exit_tracker import exit_tracker
        from dataclasses import asdict

        # Ensure initialized
        if not exit_tracker._initialized:
            await exit_tracker.initialize()

        stats = exit_tracker.get_stats()
        events = exit_tracker.get_recent_events(50)  # Last 50 events

        # Build event rows
        rows = ""
        for event in events:  # Already sorted most recent first
            # ONLY show GLOBAL_TP and MACRO_FLIP events (skip SL)
            if event.event_type == "GLOBAL_TP":
                emoji = "🎯"
                type_color = "#22c55e"
                type_label = "GLOBAL TP"
            elif event.event_type == "MACRO_FLIP":
                emoji = "🔄"
                type_color = "#f59e0b"
                type_label = "MACRO FLIP"
            else:
                # Skip STOP_LOSS and unknown event types
                continue

            profit_color = "#22c55e" if event.profit_usd >= 0 else "#ef4444"

            # Position details
            pos_details = ""
            for p in event.positions[:5]:  # Max 5 positions shown
                p_color = "#22c55e" if p.get('pnl_usd', 0) >= 0 else "#ef4444"
                pos_details += f'<div style="font-size:11px;color:#888;padding:2px 0">{p.get("symbol", "N/A"):15} <span style="color:{p_color}">${p.get("pnl_usd", 0):+.4f}</span></div>'
            if len(event.positions) > 5:
                pos_details += f'<div style="font-size:11px;color:#666">+{len(event.positions)-5} more</div>'

            if not pos_details:
                pos_details = f'<div style="font-size:11px;color:#666">{event.symbol}</div>'

            rows += f'''<tr>
                <td>{emoji} {event.timestamp[:19]}</td>
                <td style="color:{type_color};font-weight:bold">{type_label}</td>
                <td>{event.symbol}</td>
                <td>{event.trigger_percent:.2f}%</td>
                <td>{event.threshold_percent:.2f}%</td>
                <td>${event.balance_before:.2f}</td>
                <td>${event.balance_after:.2f}</td>
                <td style="color:{profit_color};font-weight:bold">${event.profit_usd:+.2f}</td>
                <td>{event.positions_closed}</td>
                <td style="max-width:200px">{pos_details}</td>
            </tr>'''

        if not events:
            rows = '<tr><td colspan="10" style="padding:40px;text-align:center;color:#888">No exit events recorded yet</td></tr>'

        # Stats colors
        total_color = "#22c55e" if stats['total_profit'] >= 0 else "#ef4444"
        tp_color = "#22c55e" if stats['tp_profit'] >= 0 else "#ef4444"
        storage_type = "Redis" if exit_tracker.redis else "File"

        html = f'''<!DOCTYPE html><html><head><title>Exit Tracker</title><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30"><style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e5e5;padding:20px}}.container{{max-width:1600px;margin:0 auto}}.header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:15px;border-bottom:1px solid #333}}.title{{font-size:24px;font-weight:600}}.refresh{{color:#666;font-size:12px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:15px;margin-bottom:20px}}.card{{background:#171717;border-radius:8px;padding:16px;border:1px solid #262626}}.card-label{{color:#888;font-size:12px;margin-bottom:4px}}.card-value{{font-size:20px;font-weight:600}}table{{width:100%;border-collapse:collapse;background:#171717;border-radius:8px;overflow:hidden}}th{{background:#262626;padding:12px;text-align:left;font-weight:500;font-size:13px;color:#888}}td{{padding:12px;border-bottom:1px solid #333;vertical-align:top}}.nav{{margin-bottom:20px}}.nav a{{color:#3b82f6;text-decoration:none;margin-right:15px}}.nav a:hover{{text-decoration:underline}}</style></head><body><div class="container">
        <div class="nav"><a href="/positions">📊 Positions</a><a href="/exits">📋 Exits</a><a href="/tp-tracker">🎯 TP Only</a><a href="/health">❤️ Health</a></div>
        <div class="header"><div class="title">📋 Exit Tracker (Manual Only)</div><div class="refresh">Auto-refresh: 30s | Storage: {storage_type}</div></div>
        <div class="cards">
            <div class="card"><div class="card-label">Total Events</div><div class="card-value">{stats['total_events']}</div></div>
            <div class="card"><div class="card-label">🎯 TP/Flip Events</div><div class="card-value" style="color:#22c55e">{stats['tp_events']}</div></div>
            <div class="card"><div class="card-label">Net Profit</div><div class="card-value" style="color:{total_color}">${stats['total_profit']:+.2f}</div></div>
            <div class="card"><div class="card-label">TP Profit</div><div class="card-value" style="color:{tp_color}">${stats['tp_profit']:+.2f}</div></div>
            <div class="card"><div class="card-label">Avg Profit</div><div class="card-value">${stats['avg_tp_profit']:+.2f}</div></div>
            <div class="card"><div class="card-label">Win Rate</div><div class="card-value">{stats['tp_win_rate']:.1f}%</div></div>
        </div>
        <table><thead><tr><th>Timestamp</th><th>Type</th><th>Symbol</th><th>Trigger %</th><th>Threshold</th><th>Before</th><th>After</th><th>P&L</th><th>Positions</th><th>Details</th></tr></thead><tbody>{rows}</tbody></table>
        </div></body></html>'''
        return HTMLResponse(content=html)
    except Exception as e:
        import traceback
        return HTMLResponse(content=f"<h1>Error</h1><pre>{traceback.format_exc()}</pre>")


@app.get("/exits/json")
async def exits_json():
    """JSON API for exit tracker data"""
    try:
        from src.exit_tracker import exit_tracker
        from dataclasses import asdict

        # Ensure initialized
        if not exit_tracker._initialized:
            await exit_tracker.initialize()

        return {
            "stats": exit_tracker.get_stats(),
            "events": [asdict(e) for e in exit_tracker.get_recent_events(50)],
            "tp_events": [asdict(e) for e in exit_tracker.get_tp_events()],
            "storage": "redis" if exit_tracker.redis else "file"
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/cancel-all-orders")
async def cancel_all_orders():
    """Cancel ALL open orders on Binance (including SL orders)"""
    try:
        # Get all open orders
        open_orders = await bot.data_feed.client.futures_get_open_orders()

        if not open_orders:
            return {"status": "ok", "message": "No open orders to cancel", "cancelled": 0}

        cancelled = 0
        errors = []

        # Group by symbol for efficient cancellation
        symbols = set(o['symbol'] for o in open_orders)

        for symbol in symbols:
            try:
                await bot.data_feed.client.futures_cancel_all_open_orders(symbol=symbol)
                symbol_orders = len([o for o in open_orders if o['symbol'] == symbol])
                cancelled += symbol_orders
                logger.info(f"Cancelled {symbol_orders} orders for {symbol}")
            except Exception as e:
                errors.append(f"{symbol}: {str(e)}")

        return {
            "status": "ok",
            "cancelled": cancelled,
            "symbols": list(symbols),
            "errors": errors if errors else None
        }
    except Exception as e:
        logger.error(f"Error cancelling orders: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/reset-trackers")
async def reset_trackers():
    """Clear all corrupted tracker data - Redis, files, and memory"""
    try:
        from src.exit_tracker import exit_tracker
        from src.tp_tracker import tp_tracker
        import redis.asyncio as redis
        import os
        import json

        cleared = []
        redis_url = os.getenv('REDIS_URL')

        if not redis_url:
            return {"status": "error", "message": "No REDIS_URL configured"}

        # Connect directly to Redis and clear all tracker keys
        r = redis.from_url(redis_url, decode_responses=True)

        # Clear all known tracker keys
        keys_to_clear = ['exit_tracker_v2', 'global_tp_tracker', 'tp_tracker_v2']
        for key in keys_to_clear:
            existed = await r.delete(key)
            if existed:
                cleared.append(f"redis:{key}")

        # Write empty data to Redis to prevent any reload
        empty_data = json.dumps({'events': [], 'total_events': 0})
        await r.set('exit_tracker_v2', empty_data)
        await r.set('global_tp_tracker', empty_data)
        cleared.append("redis:wrote_empty_data")

        await r.close()

        # Clear file backups to prevent reload from file
        file_backups = ['data/exit_tracker.json', 'data/global_tp_tracker.json']
        for file_path in file_backups:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    cleared.append(f"file:deleted:{file_path}")
                # Write empty file to prevent recreation
                os.makedirs('data', exist_ok=True)
                with open(file_path, 'w') as f:
                    json.dump({'events': [], 'total_events': 0}, f)
                cleared.append(f"file:wrote_empty:{file_path}")
            except Exception as e:
                cleared.append(f"file:error:{file_path}:{str(e)}")

        # Clear in-memory events on the global singletons
        exit_tracker.events = []
        exit_tracker._initialized = True  # Mark as initialized with empty data
        tp_tracker.events = []
        tp_tracker._initialized = True  # Mark as initialized with empty data

        # Also clear the Redis connections to force fresh connection
        if exit_tracker.redis:
            exit_tracker.redis = None
        if tp_tracker.redis:
            tp_tracker.redis = None

        return {
            "status": "success",
            "cleared": cleared,
            "exit_tracker_events": len(exit_tracker.events),
            "tp_tracker_events": len(tp_tracker.events),
            "message": f"Cleared {len(cleared)} items. Both trackers now have 0 events."
        }
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}


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


@app.get("/api/fees")
async def api_fees():
    """JSON API for fee tracking data"""
    try:
        # Get current balance for percentage calculations
        balance = await bot.data_feed.get_account_balance() if bot else 0

        # Get stats
        stats = fee_tracker.get_stats(balance)

        # Get breakdown by symbol
        breakdown = fee_tracker.get_fee_breakdown_by_symbol()

        # Check for alerts
        alerts = fee_tracker.check_alerts(balance)

        return {
            "session_id": fee_tracker.session_id,
            "session_start": fee_tracker.session_start,
            "balance": balance,
            "stats": {
                "total_fees": stats.total_fees,
                "total_commission": stats.total_commission,
                "total_funding": stats.total_funding,
                "total_trades": stats.total_trades,
                "avg_fee_per_trade": stats.avg_fee_per_trade,
                "fee_as_percent_balance": stats.fee_as_percent_balance,
                "expected_fee_rate": stats.expected_fee_rate,
                "actual_avg_fee_rate": stats.actual_avg_fee_rate,
                "fee_efficiency": stats.fee_efficiency,
                "fees_today": stats.fees_today,
                "fees_this_hour": stats.fees_this_hour,
                "hourly_fee_rate": stats.hourly_fee_rate
            },
            "breakdown_by_symbol": breakdown,
            "alerts": alerts,
            "total_records": len(fee_tracker.fee_records)
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/fees", response_class=HTMLResponse)
async def fees_dashboard():
    """HTML dashboard for fee tracking"""
    try:
        from dataclasses import asdict

        # Get current balance
        balance = await bot.data_feed.get_account_balance() if bot else 0

        # Get stats
        stats = fee_tracker.get_stats(balance)

        # Get breakdown by symbol
        breakdown = fee_tracker.get_fee_breakdown_by_symbol()

        # Check for alerts
        alerts = fee_tracker.check_alerts(balance)

        # Build symbol breakdown rows
        breakdown_rows = ""
        for symbol, fees in list(breakdown.items())[:20]:  # Top 20
            breakdown_rows += f'<tr><td>{symbol}</td><td>${fees:.4f}</td></tr>'

        if not breakdown_rows:
            breakdown_rows = '<tr><td colspan="2" style="text-align:center;color:#888">No fee data yet</td></tr>'

        # Alert banner
        alert_html = ""
        if alerts:
            alert_list = "".join([f'<div style="margin:5px 0">{alert}</div>' for alert in alerts])
            alert_html = f'<div style="background:#7f1d1d;border:1px solid #991b1b;border-radius:8px;padding:15px;margin-bottom:20px">{alert_list}</div>'

        # Recent fees (last 10)
        recent_rows = ""
        for record in reversed(fee_tracker.fee_records[-10:]):
            fee_color = "#ef4444" if record.fee_amount > 0 else "#22c55e"
            recent_rows += f'''<tr>
                <td>{record.timestamp[:19]}</td>
                <td>{record.symbol}</td>
                <td>{record.action}</td>
                <td style="color:{fee_color}">${record.fee_amount:.4f}</td>
                <td>{record.fee_rate*100:.3f}%</td>
                <td>${record.notional_value:.2f}</td>
            </tr>'''

        if not recent_rows:
            recent_rows = '<tr><td colspan="6" style="text-align:center;color:#888">No recent fees</td></tr>'

        # Colors for stats
        efficiency_color = "#22c55e" if stats.fee_efficiency >= 90 else "#eab308" if stats.fee_efficiency >= 70 else "#ef4444"
        hourly_color = "#22c55e" if stats.hourly_fee_rate < 1 else "#eab308" if stats.hourly_fee_rate < 2 else "#ef4444"

        html = f'''<!DOCTYPE html><html><head><title>Fee Tracker</title><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30"><style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e5e5;padding:20px}}.container{{max-width:1400px;margin:0 auto}}.header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:15px;border-bottom:1px solid #333}}.title{{font-size:24px;font-weight:600}}.refresh{{color:#666;font-size:12px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:15px;margin-bottom:20px}}.card{{background:#171717;border-radius:8px;padding:16px;border:1px solid #262626}}.card-label{{color:#888;font-size:12px;margin-bottom:4px}}.card-value{{font-size:20px;font-weight:600}}table{{width:100%;border-collapse:collapse;background:#171717;border-radius:8px;overflow:hidden;margin-bottom:20px}}th{{background:#262626;padding:12px;text-align:left;font-weight:500;font-size:13px;color:#888}}td{{padding:12px;border-bottom:1px solid #333}}.nav{{margin-bottom:20px}}.nav a{{color:#3b82f6;text-decoration:none;margin-right:15px}}.nav a:hover{{text-decoration:underline}}.section-title{{font-size:18px;font-weight:600;margin:20px 0 10px}}</style></head><body><div class="container">
        <div class="nav"><a href="/positions">📊 Positions</a><a href="/exits">📋 Exits</a><a href="/fees">💰 Fees</a><a href="/health">❤️ Health</a></div>
        <div class="header"><div class="title">💰 Fee Tracker</div><div class="refresh">Auto-refresh: 30s</div></div>
        {alert_html}
        <div class="cards">
            <div class="card"><div class="card-label">Total Fees</div><div class="card-value" style="color:#ef4444">${stats.total_fees:.4f}</div></div>
            <div class="card"><div class="card-label">Commission</div><div class="card-value" style="color:#ef4444">${stats.total_commission:.4f}</div></div>
            <div class="card"><div class="card-label">Funding</div><div class="card-value" style="color:#ef4444">${stats.total_funding:.4f}</div></div>
            <div class="card"><div class="card-label">Total Trades</div><div class="card-value">{stats.total_trades}</div></div>
            <div class="card"><div class="card-label">Avg Fee/Trade</div><div class="card-value">${stats.avg_fee_per_trade:.4f}</div></div>
            <div class="card"><div class="card-label">Fee % Balance</div><div class="card-value">{stats.fee_as_percent_balance:.2f}%</div></div>
            <div class="card"><div class="card-label">Fee Efficiency</div><div class="card-value" style="color:{efficiency_color}">{stats.fee_efficiency:.1f}%</div></div>
            <div class="card"><div class="card-label">Fees Today</div><div class="card-value" style="color:#ef4444">${stats.fees_today:.4f}</div></div>
            <div class="card"><div class="card-label">Fees This Hour</div><div class="card-value" style="color:#ef4444">${stats.fees_this_hour:.4f}</div></div>
            <div class="card"><div class="card-label">Hourly Fee Rate</div><div class="card-value" style="color:{hourly_color}">{stats.hourly_fee_rate:.3f}%</div></div>
            <div class="card"><div class="card-label">Actual Fee Rate</div><div class="card-value">{stats.actual_avg_fee_rate*100:.4f}%</div></div>
            <div class="card"><div class="card-label">Expected Rate</div><div class="card-value">{stats.expected_fee_rate*100:.2f}%</div></div>
        </div>
        <div class="section-title">💸 Recent Fees (Last 10)</div>
        <table><thead><tr><th>Timestamp</th><th>Symbol</th><th>Action</th><th>Fee</th><th>Rate</th><th>Notional</th></tr></thead><tbody>{recent_rows}</tbody></table>
        <div class="section-title">📊 Fee Breakdown by Symbol (Top 20)</div>
        <table><thead><tr><th>Symbol</th><th>Total Fees</th></tr></thead><tbody>{breakdown_rows}</tbody></table>
        <div style="margin-top:20px;color:#666;font-size:12px;text-align:center">Session: {fee_tracker.session_id} | Started: {fee_tracker.session_start[:19]} | Balance: ${balance:.2f}</div>
        </div></body></html>'''

        return HTMLResponse(content=html)

    except Exception as e:
        import traceback
        return HTMLResponse(content=f"<h1>Error</h1><pre>{traceback.format_exc()}</pre>")


@app.get("/backfill-trackers")
async def backfill_trackers():
    """Repopulate trackers from real Binance income history"""
    try:
        from src.exit_tracker import exit_tracker, ExitEvent
        from src.tp_tracker import tp_tracker, GlobalTPEvent
        from collections import defaultdict
        from datetime import datetime
        from dataclasses import asdict

        # Ensure trackers are initialized
        await exit_tracker.initialize()
        await tp_tracker.initialize()

        # Fetch all realized PnL from Binance
        income = await bot.data_feed.client.futures_income_history(incomeType='REALIZED_PNL', limit=1000)
        income = sorted(income, key=lambda x: int(x.get('time', 0)))

        if not income:
            return {"status": "error", "message": "No income history found"}

        # Get current balance to work backwards
        acc = await bot.data_feed.client.futures_account()
        current_balance = float(acc['totalWalletBalance'])

        # Group by minute to find batch closes
        by_minute = defaultdict(list)
        for i in income:
            minute = int(i.get('time', 0)) // 60000
            by_minute[minute].append(i)

        # Categorize events - ONLY Global TP (no SL tracking)
        global_tp_events = []

        for minute, trades in by_minute.items():
            timestamp = datetime.fromtimestamp(minute * 60)
            total_pnl = sum(float(t.get('income', 0)) for t in trades)

            # Calculate balance at this point
            income_after = sum(
                float(i.get('income', 0))
                for i in income
                if int(i.get('time', 0)) // 60000 > minute
            )
            balance_after = current_balance - income_after
            balance_before = balance_after - total_pnl

            if len(trades) >= 3:
                # Global TP event (batch close)
                positions = []
                for t in trades:
                    pnl = float(t.get('income', 0))
                    positions.append({
                        'symbol': t.get('symbol', 'N/A'),
                        'direction': 'LONG',
                        'entry_price': 0,
                        'exit_price': 0,
                        'pnl_usd': pnl,
                        'pnl_percent': 0,
                        'margin': 0
                    })

                trigger_pct = (total_pnl / balance_before * 100) if balance_before > 0 else 0

                global_tp_events.append({
                    'id': f"TP_{timestamp.strftime('%Y%m%d_%H%M%S')}",
                    'timestamp': timestamp.isoformat(),
                    'trigger_percent': abs(trigger_pct),
                    'threshold_percent': 5.0,
                    'balance_before': balance_before,
                    'balance_after': balance_after,
                    'profit_usd': total_pnl,
                    'positions_closed': len(trades),
                    'positions': positions,
                    'total_margin': 0
                })
            # else: REMOVED - No longer tracking individual SL events

        # Clear existing and add new events
        exit_tracker.events = []
        tp_tracker.events = []

        # Add Global TP events to both trackers
        for e in global_tp_events:
            tp_tracker.events.append(GlobalTPEvent(**e))
            exit_tracker.events.append(ExitEvent(
                id=e['id'],
                timestamp=e['timestamp'],
                event_type='GLOBAL_TP',
                symbol='ALL',
                trigger_percent=e['trigger_percent'],
                threshold_percent=e['threshold_percent'],
                balance_before=e['balance_before'],
                balance_after=e['balance_after'],
                profit_usd=e['profit_usd'],
                positions_closed=e['positions_closed'],
                positions=e['positions'],
                total_margin=e['total_margin']
            ))

        # SL tracking completely removed - only Global TP events

        # Save directly to Redis (bypass tracker's connection issues)
        import redis.asyncio as redis_async
        import json
        redis_url = os.getenv('REDIS_URL')

        if redis_url:
            r = redis_async.from_url(redis_url, decode_responses=True)

            # Save tp_tracker data directly
            tp_data = {
                'events': [asdict(e) for e in tp_tracker.events],
                'total_events': len(tp_tracker.events),
                'total_profit': sum(e.profit_usd for e in tp_tracker.events)
            }
            await r.set('global_tp_tracker', json.dumps(tp_data))

            # Save exit_tracker data directly
            exit_data = {
                'events': [asdict(e) for e in exit_tracker.events],
                'total_events': len(exit_tracker.events)
            }
            await r.set('exit_tracker_v2', json.dumps(exit_data))

            await r.close()

        # Also save to files
        tp_tracker._save_to_file()
        exit_tracker._save_to_file()

        # Verify what's in Redis after save
        redis_verification = {}
        if redis_url:
            r2 = redis_async.from_url(redis_url, decode_responses=True)
            tp_redis_raw = await r2.get('global_tp_tracker')
            exit_redis_raw = await r2.get('exit_tracker_v2')
            if tp_redis_raw:
                tp_redis_data = json.loads(tp_redis_raw)
                redis_verification['tp_tracker_redis_events'] = len(tp_redis_data.get('events', []))
            if exit_redis_raw:
                exit_redis_data = json.loads(exit_redis_raw)
                redis_verification['exit_tracker_redis_events'] = len(exit_redis_data.get('events', []))
            # Also get all keys to check for duplicates
            all_keys = await r2.keys('*tracker*')
            redis_verification['all_tracker_keys'] = all_keys
            await r2.close()

        return {
            "status": "success",
            "global_tp_events": len(global_tp_events),
            "total_income_records": len(income),
            "current_balance": current_balance,
            "tp_total_profit": sum(e.profit_usd for e in tp_tracker.events),
            "redis_verification": redis_verification,
            "tp_tracker_memory_events": len(tp_tracker.events),
            "exit_tracker_memory_events": len(exit_tracker.events),
            "message": f"Backfilled {len(global_tp_events)} Global TP events from Binance history (SL tracking removed)"
        }

    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}


if __name__ == "__main__":
    # Create logs directory
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    logger.info("=" * 60)
    logger.info("STARTING MACRO INDEX BOT")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=PORT)
