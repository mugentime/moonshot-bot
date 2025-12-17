"""
MACRO INDEX BOT - 24H TIMEFRAME
Trade all whitelisted coins in same direction based on 24H macro indicator.

Strategy:
- Uses 24-HOUR price changes (NOT 5-minute noise) for stable trend detection
- Calculate macro score from majority vote + leader-follower + aggregate velocity
- Score >= +1 → LONG all coins
- Score <= -1 → SHORT all coins
- 1 HOUR COOLDOWN between direction changes to prevent whipsaws
- INDIVIDUAL SL: 10% loss per position triggers close (configurable via STOP_LOSS_PERCENT env)
- GLOBAL TP: Portfolio profit target closes ALL positions (configurable via GLOBAL_TP_PERCENT env)
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
    - GLOBAL TP: Close all positions when portfolio profit reaches threshold
    - NO individual SL/TP - only Global TP closes positions
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
        self.last_global_tp_time: float = 0  # Track last Global TP for cooldown

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

        # Initialize data feed
        await self.data_feed.initialize()
        logger.info("Connected to Binance")

        # NOTE: Positions persist across restarts - no longer closing on startup

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

        # Initialize TP tracker with Redis
        await tp_tracker.initialize()
        logger.info("TP tracker ready")

        # Cancel any leftover STOP_MARKET orders from previous code versions
        # This ensures software SL has exclusive control
        await self._cancel_all_stop_orders()

        # Get starting balance
        balance = await self.data_feed.get_account_balance()
        profit_tracker.set_start_balance(balance)
        logger.info(f"Starting balance: ${balance:.2f}")

        logger.info("=" * 60)
        logger.info("MACRO STRATEGY CONFIG (24H TIMEFRAME):")
        logger.info(f"  Coins: {len(self.whitelisted_symbols)}")
        logger.info(f"  Leverage: {self.config.LEVERAGE}x")
        logger.info(f"  Timeframe: 24H (stable trend detection)")
        logger.info(f"  Direction Cooldown: {self.config.DIRECTION_CHANGE_COOLDOWN_SECONDS}s (1 hour)")
        logger.info(f"  Individual SL: {self.config.STOP_LOSS_PERCENT}% (env: STOP_LOSS_PERCENT)")
        logger.info(f"  Global TP: {self.config.GLOBAL_TP_PERCENT}% (env: GLOBAL_TP_PERCENT)")
        logger.info(f"  Global TP Cooldown: {self.config.GLOBAL_TP_COOLDOWN_SECONDS}s (env: GLOBAL_TP_COOLDOWN)")
        logger.info(f"  Long Trigger: Score >= {self.config.LONG_TRIGGER_SCORE}")
        logger.info(f"  Short Trigger: Score <= {self.config.SHORT_TRIGGER_SCORE}")
        logger.info("=" * 60)

    async def start(self):
        """Start the bot"""
        self._running = True
        logger.info("MACRO INDEX BOT STARTED")

        # Start WebSocket ticker stream for real-time prices
        await self.data_feed.start_ticker_stream()
        logger.info("Ticker stream started - Global TP monitoring active")

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
                    await self._handle_direction_change(score)
                else:
                    # RECOVERY: If direction is LONG/SHORT but we have no positions, re-open them
                    # This handles the case where positions were manually closed
                    if score.direction != MacroDirection.FLAT:
                        await self._ensure_positions_open(score.direction.value)

                await asyncio.sleep(self.config.SCAN_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Macro loop error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)

    async def _handle_direction_change(self, score):
        """Handle when macro direction changes - NO LONGER CLOSES POSITIONS"""
        old_direction = self.current_direction
        new_direction = score.direction

        logger.info(f"{'='*60}")
        logger.info(f"MACRO DIRECTION CHANGE: {old_direction.value} -> {new_direction.value}")
        logger.info(f"NOTE: Positions NOT closed - only Global TP can close")
        logger.info(f"{'='*60}")

        # REMOVED: No longer closing positions on macro flip
        # Positions only close via Global TP

        # Open new positions if not flat (additive, not replacing)
        if new_direction != MacroDirection.FLAT:
            await self._open_all_positions(new_direction.value)

        self.current_direction = new_direction

    async def _close_all_positions_for_direction(self, direction: str):
        """Close all positions for a given direction"""
        logger.info(f"Closing all {direction} positions...")

        positions = self.position_tracker.get_all_positions()
        closed = 0

        for position in positions:
            if position.direction == direction:
                symbol = position.symbol
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
                            current_price = position.entry_price
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

    async def _close_all_positions_global_tp(self, trigger_percent: float = 0, total_margin: float = 0):
        """Close ALL positions due to Global TP trigger"""
        logger.info("Closing ALL positions for Global TP...")

        # Get balance BEFORE closing
        balance_before = await self._get_wallet_balance()

        positions = self.position_tracker.get_all_positions()
        closed = 0
        total_pnl = 0
        position_details = []  # For TP tracker

        for position in positions:
            symbol = position.symbol
            try:
                current_price = await self.data_feed.get_current_price_safe(symbol)
                if current_price is None:
                    logger.warning(f"No price for {symbol} in Global TP, using entry price")
                    current_price = position.entry_price

                if position.direction == "LONG":
                    result = await self.order_executor.close_long(symbol)
                    pnl_pct = ((current_price - position.entry_price) / position.entry_price) * 100
                else:
                    result = await self.order_executor.close_short(symbol)
                    pnl_pct = ((position.entry_price - current_price) / position.entry_price) * 100

                if result.success:
                    closed += 1
                    pnl_usd = position.margin * (pnl_pct / 100) * self.config.LEVERAGE
                    total_pnl += pnl_usd

                    # Collect position details for TP tracker
                    position_details.append({
                        'symbol': symbol,
                        'direction': position.direction,
                        'entry_price': position.entry_price,
                        'exit_price': current_price,
                        'pnl_usd': pnl_usd,
                        'pnl_percent': pnl_pct * self.config.LEVERAGE,
                        'margin': position.margin
                    })

                    profit_tracker.record_exit(
                        symbol=symbol,
                        exit_price=current_price,
                        exit_reason="global_tp",
                        pnl_percent=pnl_pct * self.config.LEVERAGE,
                        pnl_usd=pnl_usd,
                        peak_profit=position.peak_profit_pct
                    )

                    await self.position_tracker.remove_position(symbol)
                else:
                    logger.error(f"Failed to close {symbol}: {result.error}")

            except Exception as e:
                logger.error(f"Error closing {symbol}: {e}")

            await asyncio.sleep(0.05)  # Small delay between closes

        # Get balance AFTER closing
        balance_after = await self._get_wallet_balance()

        # Record to TP tracker
        tp_tracker.record_tp(
            trigger_percent=trigger_percent,
            threshold_percent=self.config.GLOBAL_TP_PERCENT,
            balance_before=balance_before,
            balance_after=balance_after,
            positions=position_details,
            total_margin=total_margin
        )

        logger.info(f"{'='*60}")
        logger.info(f"GLOBAL TP COMPLETE: Closed {closed}/{len(positions)} positions")
        logger.info(f"Balance: ${balance_before:.2f} -> ${balance_after:.2f}")
        logger.info(f"PROFIT: ${balance_after - balance_before:+.2f}")
        logger.info(f"Cooldown: {self.config.GLOBAL_TP_COOLDOWN_SECONDS}s before reopening")
        logger.info(f"{'='*60}")

    async def _open_all_positions(self, direction: str):
        """Open positions on all whitelisted coins"""
        # Check Global TP cooldown
        if self.last_global_tp_time > 0:
            time_since_tp = time.time() - self.last_global_tp_time
            if time_since_tp < self.config.GLOBAL_TP_COOLDOWN_SECONDS:
                remaining = int(self.config.GLOBAL_TP_COOLDOWN_SECONDS - time_since_tp)
                logger.info(f"Global TP cooldown active. {remaining}s remaining. Skipping position opening.")
                return

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
        """Monitor open positions - Check Individual SL + Global TP"""
        logger.info(f"Position monitor loop started (SL: {self.config.STOP_LOSS_PERCENT}%, Global TP: {self.config.GLOBAL_TP_PERCENT}%)")
        check_count = 0

        while self._running:
            try:
                # CRITICAL: Sync with exchange every 12 checks (~1 minute) to catch all positions
                if check_count % 12 == 0:
                    await self.position_tracker.sync_with_exchange()

                positions = self.position_tracker.get_all_positions()
                check_count += 1

                if not positions:
                    await asyncio.sleep(5)
                    continue

                # === INDIVIDUAL STOP LOSS CHECK ===
                sl_closed = []
                for p in positions:
                    # Use safe price fetching with REST fallback - NEVER fall back to entry_price
                    price = await self.data_feed.get_current_price_safe(p.symbol, max_age_seconds=10.0)
                    if price is None:
                        logger.warning(f"SL CHECK: No price for {p.symbol}, skipping (WebSocket + REST both failed)")
                        continue

                    if p.direction == "LONG":
                        pnl_pct = ((price - p.entry_price) / p.entry_price) * 100 * self.config.LEVERAGE
                    else:
                        pnl_pct = ((p.entry_price - price) / p.entry_price) * 100 * self.config.LEVERAGE

                    # Check if position hit stop loss
                    if pnl_pct <= -self.config.STOP_LOSS_PERCENT:
                        logger.warning(f"SL TRIGGERED: {p.symbol} at {pnl_pct:.2f}% (threshold: -{self.config.STOP_LOSS_PERCENT}%)")

                        # Calculate actual margin from position (handles synced positions with margin=0)
                        # margin = notional / leverage = (quantity * entry_price) / leverage
                        freed_margin = p.margin if p.margin > 0 else (p.quantity * p.entry_price) / self.config.LEVERAGE
                        logger.info(f"Freed margin from {p.symbol}: ${freed_margin:.2f}")

                        # Close the position
                        await self._execute_exit(p.symbol, p, {'action': 'close', 'reason': 'stop_loss'}, price)
                        sl_closed.append(p.symbol)

                        # Reallocate freed capital to best position IMMEDIATELY
                        if freed_margin > 0.5:  # Only reallocate if margin is meaningful (>$0.50)
                            await self._reallocate_capital(freed_margin, p.symbol)

                        await asyncio.sleep(0.1)  # Small delay between closes

                # Remove SL-closed positions from list for Global TP calculation
                positions = [p for p in positions if p.symbol not in sl_closed]

                if not positions:
                    await asyncio.sleep(5)
                    continue

                # === GLOBAL TP CHECK ===
                total_pnl = 0
                total_margin = 0

                for p in positions:
                    # Use safe price fetching with REST fallback
                    price = await self.data_feed.get_current_price_safe(p.symbol, max_age_seconds=10.0)
                    if price is None:
                        logger.debug(f"TP CHECK: No price for {p.symbol}, excluding from Global TP calc")
                        continue

                    # Calculate margin - handle synced positions with margin=0
                    pos_margin = p.margin if p.margin > 0 else (p.quantity * p.entry_price) / self.config.LEVERAGE

                    if p.direction == "LONG":
                        pnl = ((price - p.entry_price) / p.entry_price) * pos_margin * self.config.LEVERAGE
                    else:
                        pnl = ((p.entry_price - price) / p.entry_price) * pos_margin * self.config.LEVERAGE
                    total_pnl += pnl
                    total_margin += pos_margin

                if total_margin > 0:
                    global_pnl_pct = (total_pnl / total_margin) * 100

                    # Log Global PnL every minute
                    if check_count % 12 == 0:
                        logger.info(f"GLOBAL PnL: {global_pnl_pct:+.2f}% (${total_pnl:+.2f} / ${total_margin:.2f} margin) | SL: -{self.config.STOP_LOSS_PERCENT}% | TP: +{self.config.GLOBAL_TP_PERCENT}%")

                    # Check if Global TP triggered
                    if global_pnl_pct >= self.config.GLOBAL_TP_PERCENT:
                        logger.info(f"{'='*60}")
                        logger.info(f"GLOBAL TP TRIGGERED: +{global_pnl_pct:.2f}% (threshold: {self.config.GLOBAL_TP_PERCENT}%)")
                        logger.info(f"Total PnL: ${total_pnl:.2f} | Margin: ${total_margin:.2f}")
                        logger.info(f"{'='*60}")
                        await self._close_all_positions_global_tp(
                            trigger_percent=global_pnl_pct,
                            total_margin=total_margin
                        )
                        self.last_global_tp_time = time.time()

                await asyncio.sleep(5)  # Check every 5 seconds

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

                # Remove from tracker after successful exit
                await self.position_tracker.remove_position(symbol)
            else:
                logger.error(f"Exit failed: {symbol} - {result.error}")
                # If position doesn't exist on Binance, remove from tracker to stop retry loop
                if "No position found" in str(result.error) or "position" in str(result.error).lower():
                    logger.warning(f"Removing stale position from tracker: {symbol}")
                    await self.position_tracker.remove_position(symbol)

        except Exception as e:
            logger.error(f"Error executing exit: {e}")

    async def _find_best_position(self, exclude_symbols: list = None):
        """
        Find the best performing position (highest PnL %).
        Used for capital reallocation after SL closes a position.

        Args:
            exclude_symbols: List of symbols to exclude (e.g., just-closed position)

        Returns:
            TrackedPosition with highest PnL %, or None if no positions
        """
        exclude_symbols = exclude_symbols or []
        positions = self.position_tracker.get_all_positions()

        # Filter out excluded symbols
        candidates = [p for p in positions if p.symbol not in exclude_symbols]

        if not candidates:
            return None

        best_position = None
        best_pnl_pct = float('-inf')

        for p in candidates:
            price = await self.data_feed.get_current_price_safe(p.symbol)
            if price is None:
                logger.debug(f"No price for {p.symbol}, skipping from best position calc")
                continue
            if p.direction == "LONG":
                pnl_pct = ((price - p.entry_price) / p.entry_price) * 100 * self.config.LEVERAGE
            else:
                pnl_pct = ((p.entry_price - price) / p.entry_price) * 100 * self.config.LEVERAGE

            if pnl_pct > best_pnl_pct:
                best_pnl_pct = pnl_pct
                best_position = p

        return best_position

    async def _reallocate_capital(self, freed_margin: float, closed_symbol: str):
        """
        Reallocate freed margin from closed position to the best performing position.
        Called immediately after SL closes a position.

        Args:
            freed_margin: Margin freed from the closed position
            closed_symbol: Symbol of the position that was just closed
        """
        try:
            # Find best position (excluding the one just closed)
            best_position = await self._find_best_position(exclude_symbols=[closed_symbol])

            if not best_position:
                logger.info(f"💰 No positions to reallocate ${freed_margin:.2f} to (all positions closed)")
                return

            # Calculate current PnL of best position for logging
            price = await self.data_feed.get_current_price_safe(best_position.symbol)
            if price is None:
                logger.warning(f"No price for {best_position.symbol} in reallocation, using entry price")
                price = best_position.entry_price
            if best_position.direction == "LONG":
                best_pnl_pct = ((price - best_position.entry_price) / best_position.entry_price) * 100 * self.config.LEVERAGE
            else:
                best_pnl_pct = ((best_position.entry_price - price) / best_position.entry_price) * 100 * self.config.LEVERAGE

            logger.info(f"💰 REALLOCATING: ${freed_margin:.2f} from {closed_symbol} → {best_position.symbol} (best: {best_pnl_pct:+.2f}%)")

            # Add to best position
            result = await self.order_executor.add_to_position(
                symbol=best_position.symbol,
                margin=freed_margin,
                leverage=self.config.LEVERAGE
            )

            if result.success:
                # Update tracking with new size and entry
                await self.position_tracker.update_position_size(
                    symbol=best_position.symbol,
                    new_quantity=result.quantity,
                    new_entry_price=result.price,
                    added_margin=freed_margin
                )
                logger.info(f"✅ Reallocation complete: {best_position.symbol} now has ${best_position.margin + freed_margin:.2f} margin")
            else:
                logger.error(f"❌ Reallocation failed: {result.error}")

        except Exception as e:
            logger.error(f"Error in capital reallocation: {e}")

    async def _get_wallet_balance(self) -> float:
        """Get current USDT wallet balance from Binance"""
        try:
            account = await self.data_feed.client.futures_account_balance()
            for asset in account:
                if asset['asset'] == 'USDT':
                    return float(asset['balance'])
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
            sl_dist = 10.0 + roi

            position_list.append({'symbol': p['symbol'], 'side': side, 'roi': roi, 'pnl': pnl, 'sl_dist': sl_dist, 'margin': pos_margin, 'liq': liq})
            total_pnl += pnl
            total_margin += pos_margin
            if roi >= 0: winners += 1

        position_list.sort(key=lambda x: x['roi'], reverse=True)

        for p in position_list:
            color = "#22c55e" if p['roi'] >= 0 else "#ef4444"
            emoji = "🚀" if p['roi'] >= 5 else "🟢" if p['roi'] >= 2 else "🟡" if p['roi'] >= 0 else "🟠" if p['roi'] > -5 else "🔴"
            rows += f'<tr><td>{emoji} {p["symbol"]}</td><td>{p["side"]}</td><td style="color:{color};font-weight:bold">{p["roi"]:+.2f}%</td><td style="color:{color}">${p["pnl"]:+.2f}</td><td>{p["sl_dist"]:+.1f}%</td><td>${p["margin"]:.2f}</td><td style="font-size:11px">{p["liq"]:.6f}</td></tr>'

        if not position_list:
            rows = '<tr><td colspan="7" style="padding:40px;text-align:center;color:#888">No open positions</td></tr>'

        losers = len(position_list) - winners
        portfolio_roi = (total_pnl / total_margin * 100) if total_margin > 0 else 0
        margin_usage = ((margin - available) / margin * 100) if margin > 0 else 0
        pnl_color = "#22c55e" if total_pnl >= 0 else "#ef4444"
        health_color = "#22c55e" if margin_usage < 70 else "#eab308" if margin_usage < 90 else "#ef4444"
        health_text = "HEALTHY" if margin_usage < 70 else "MODERATE" if margin_usage < 90 else "HIGH RISK"

        # Get SL and TP from bot config
        sl_pct = bot.config.STOP_LOSS_PERCENT if bot else 10.0
        tp_pct = bot.config.GLOBAL_TP_PERCENT if bot else 1.0

        html = f'''<!DOCTYPE html><html><head><title>Position Monitor</title><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="10"><style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e5e5;padding:20px}}.container{{max-width:1200px;margin:0 auto}}.header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:15px;border-bottom:1px solid #333}}.title{{font-size:24px;font-weight:600}}.refresh{{color:#666;font-size:12px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:15px;margin-bottom:20px}}.card{{background:#171717;border-radius:8px;padding:16px;border:1px solid #262626}}.card-label{{color:#888;font-size:12px;margin-bottom:4px}}.card-value{{font-size:24px;font-weight:600}}table{{width:100%;border-collapse:collapse;background:#171717;border-radius:8px;overflow:hidden}}th{{background:#262626;padding:12px;text-align:left;font-weight:500;font-size:13px;color:#888}}td{{padding:12px;border-bottom:1px solid #333}}.status{{display:inline-block;padding:4px 12px;border-radius:4px;font-size:12px;font-weight:600}}.nav{{margin-bottom:20px}}.nav a{{color:#3b82f6;text-decoration:none;margin-right:15px}}.nav a:hover{{text-decoration:underline}}</style></head><body><div class="container"><div class="nav"><a href="/positions">📊 Positions</a><a href="/tp-tracker">🎯 TP Tracker</a><a href="/health">❤️ Health</a></div><div class="header"><div class="title">📊 Position Monitor</div><div class="refresh">Auto-refresh: 10s | SL: {sl_pct}% | TP: {tp_pct}%</div></div><div class="cards"><div class="card"><div class="card-label">Positions</div><div class="card-value">{len(position_list)} <span style="font-size:14px;color:#888">({winners}W / {losers}L)</span></div></div><div class="card"><div class="card-label">Portfolio PnL</div><div class="card-value" style="color:{pnl_color}">${total_pnl:+.2f} <span style="font-size:14px">({portfolio_roi:+.1f}%)</span></div></div><div class="card"><div class="card-label">Account Equity</div><div class="card-value">${margin:.2f}</div></div><div class="card"><div class="card-label">Margin Usage</div><div class="card-value" style="color:{health_color}">{margin_usage:.1f}% <span class="status" style="background:{health_color}20;color:{health_color}">{health_text}</span></div></div></div><table><thead><tr><th>Symbol</th><th>Side</th><th>ROI</th><th>PnL</th><th>SL Dist</th><th>Margin</th><th>Liq Price</th></tr></thead><tbody>{rows}</tbody></table><div style="margin-top:20px;color:#666;font-size:12px;text-align:center">Available: ${available:.2f} | Margin: ${margin:.2f}</div></div></body></html>'''
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
        <div class="nav"><a href="/positions">📊 Positions</a><a href="/tp-tracker">🎯 TP Tracker</a><a href="/health">❤️ Health</a></div>
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
