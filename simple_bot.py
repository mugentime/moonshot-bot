"""
SIMPLE MOONSHOT BOT
Clean implementation with simplified strategy

Strategy:
- Entry: 2% move in 5 minutes
- Stop Loss: 3%
- Trailing: Activate at 2% profit, 3% distance
"""
import asyncio
import signal
import sys
import os
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from loguru import logger
import uvicorn

from config import PORT, LOG_LEVEL
from src import DataFeed, PairFilter, PositionTracker, OrderExecutor
from src.simple_strategy import SimpleDetector, SimpleExitManager, SimpleConfig
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
    "logs/simple_bot_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG"
)


class SimpleMoonshotBot:
    """
    Simplified Moonshot Bot
    - Scans for 2% moves
    - Enters with 10x leverage
    - 3% stop loss
    - 3% trailing stop (activates at 2% profit)
    """

    def __init__(self):
        self.config = SimpleConfig()
        self.data_feed = DataFeed()
        self.pair_filter = PairFilter(self.data_feed)
        self.position_tracker = PositionTracker(self.data_feed)
        self.order_executor = OrderExecutor(self.data_feed)
        self.detector = None  # Initialize after data_feed
        self.exit_manager = SimpleExitManager(self.config)

        self._running = False
        self._scan_task = None
        self._monitor_task = None

    async def initialize(self):
        """Initialize the bot"""
        logger.info("🚀 Initializing Simple Moonshot Bot...")

        # Initialize data feed
        await self.data_feed.initialize()
        logger.info("✅ Connected to Binance")

        # Initialize detector
        self.detector = SimpleDetector(self.data_feed, self.config)

        # Initialize pairs
        await self.pair_filter.initialize()
        logger.info(f"✅ Loaded {len(self.pair_filter.pairs)} trading pairs")

        # Initialize position tracker
        await self.position_tracker.initialize()
        logger.info(f"✅ Position tracker ready")

        # Get starting balance
        balance = await self.data_feed.get_account_balance()
        profit_tracker.set_start_balance(balance)
        logger.info(f"💰 Starting balance: ${balance:.2f}")

        logger.info("=" * 60)
        logger.info("SIMPLE STRATEGY CONFIG:")
        logger.info(f"  Entry: {self.config.ENTRY_VELOCITY_5M}% move in 5 min")
        logger.info(f"  Stop Loss: {self.config.STOP_LOSS_PERCENT}%")
        logger.info(f"  Trailing: {self.config.TRAILING_DISTANCE}% (activates at {self.config.TRAILING_ACTIVATION}% profit)")
        logger.info(f"  Leverage: {self.config.LEVERAGE}x")
        logger.info(f"  Max Positions: {self.config.MAX_POSITIONS}")
        logger.info("=" * 60)

    async def start(self):
        """Start the bot"""
        self._running = True
        logger.info("🟢 Bot started")

        # Start scan and monitor loops
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """Stop the bot"""
        self._running = False
        logger.info("🔴 Stopping bot...")

        if self._scan_task:
            self._scan_task.cancel()
        if self._monitor_task:
            self._monitor_task.cancel()

        # Print final report
        profit_tracker.print_report()

    async def _scan_loop(self):
        """Main scanning loop - look for entry signals"""
        logger.info("📡 Scan loop started")

        while self._running:
            try:
                # Get current position count
                positions = self.position_tracker.get_all_positions()
                if len(positions) >= self.config.MAX_POSITIONS:
                    await asyncio.sleep(self.config.SCAN_INTERVAL)
                    continue

                # Get pairs sorted by 24h change
                pairs = await self._get_sorted_pairs()

                for symbol in pairs[:100]:  # Top 100 movers
                    if not self._running:
                        break

                    # Already have position?
                    if self.position_tracker.has_position(symbol):
                        continue

                    # Scan for signal
                    signal = await self.detector.scan(symbol)

                    if signal:
                        await self._execute_entry(signal)

                        # Check if max positions reached
                        if len(self.position_tracker.get_all_positions()) >= self.config.MAX_POSITIONS:
                            break

                await asyncio.sleep(self.config.SCAN_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
                await asyncio.sleep(5)

    async def _monitor_loop(self):
        """Monitor open positions for exits"""
        logger.info("👁️ Monitor loop started")

        while self._running:
            try:
                positions = self.position_tracker.get_all_positions()

                for symbol, position in positions.items():
                    try:
                        # Get current price
                        current_price = self.data_feed.get_current_price(symbol)
                        if not current_price:
                            await self.data_feed.get_klines(symbol, '1m', 5)
                            current_price = self.data_feed.get_current_price(symbol)

                        if not current_price:
                            continue

                        # Calculate current profit
                        entry_price = position.entry_price
                        direction = position.direction
                        leverage = position.leverage

                        if direction == "LONG":
                            profit_pct = ((current_price - entry_price) / entry_price) * 100 * leverage
                        else:
                            profit_pct = ((entry_price - current_price) / entry_price) * 100 * leverage

                        # Update peak profit in tracker
                        profit_tracker.update_peak_profit(symbol, profit_pct)

                        # Check exit conditions
                        exit_action = self.exit_manager.check_exit(
                            symbol=symbol,
                            direction=direction,
                            entry_price=entry_price,
                            current_price=current_price
                        )

                        if exit_action:
                            await self._execute_exit(symbol, position, exit_action, current_price)

                    except Exception as e:
                        logger.error(f"Error monitoring {symbol}: {e}")

                await asyncio.sleep(2)  # Check every 2 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(5)

    async def _get_sorted_pairs(self):
        """Get pairs sorted by 24h price change"""
        try:
            tickers = await self.data_feed.client.futures_ticker()

            # Filter and sort by absolute price change
            valid = []
            for t in tickers:
                if t['symbol'].endswith('USDT'):
                    try:
                        change = abs(float(t['priceChangePercent']))
                        valid.append((t['symbol'], change))
                    except:
                        pass

            valid.sort(key=lambda x: x[1], reverse=True)
            return [v[0] for v in valid]

        except Exception as e:
            logger.error(f"Error getting sorted pairs: {e}")
            return list(self.pair_filter.pairs.keys())

    async def _execute_entry(self, signal):
        """Execute entry trade"""
        try:
            symbol = signal.symbol
            direction = signal.direction

            # Get margin
            balance = await self.data_feed.get_account_balance()
            margin = min(balance * 0.05, balance / self.config.MAX_POSITIONS)  # 5% max or equal split
            margin = max(margin, 1.0)  # At least $1

            if margin < 1.0:
                logger.warning(f"Insufficient margin for {symbol}")
                return

            # Calculate stop loss price
            if direction == "LONG":
                sl_price = signal.entry_price * (1 - self.config.STOP_LOSS_PERCENT / 100)
            else:
                sl_price = signal.entry_price * (1 + self.config.STOP_LOSS_PERCENT / 100)

            # Execute trade
            if direction == "LONG":
                result = await self.order_executor.open_long(
                    symbol=symbol,
                    margin=margin,
                    leverage=self.config.LEVERAGE,
                    stop_loss=sl_price
                )
            else:
                result = await self.order_executor.open_short(
                    symbol=symbol,
                    margin=margin,
                    leverage=self.config.LEVERAGE,
                    stop_loss=sl_price
                )

            if result.success:
                # Record in profit tracker
                profit_tracker.record_entry(
                    symbol=symbol,
                    direction=direction,
                    entry_price=result.entry_price,
                    leverage=self.config.LEVERAGE,
                    margin=margin,
                    velocity=signal.velocity_5m
                )

                logger.info(f"✅ ENTRY: {direction} {symbol} @ ${result.entry_price:.6f} | SL: ${sl_price:.6f}")
            else:
                logger.error(f"❌ Entry failed: {symbol} - {result.error}")

        except Exception as e:
            logger.error(f"Error executing entry: {e}")

    async def _execute_exit(self, symbol: str, position, exit_action: dict, current_price: float):
        """Execute exit trade"""
        try:
            direction = position.direction
            entry_price = position.entry_price

            # Calculate PnL
            if direction == "LONG":
                pnl_pct = ((current_price - entry_price) / entry_price) * 100 * position.leverage
            else:
                pnl_pct = ((entry_price - current_price) / entry_price) * 100 * position.leverage

            pnl_usd = position.margin * (pnl_pct / 100)

            # Close position
            if direction == "LONG":
                result = await self.order_executor.close_long(symbol)
            else:
                result = await self.order_executor.close_short(symbol)

            if result.success:
                # Get peak profit from exit manager
                peak = self.exit_manager.peak_prices.get(symbol, entry_price)
                if direction == "LONG":
                    peak_profit = ((peak - entry_price) / entry_price) * 100 * position.leverage
                else:
                    peak_profit = ((entry_price - peak) / peak) * 100 * position.leverage

                # Record in profit tracker
                profit_tracker.record_exit(
                    symbol=symbol,
                    exit_price=current_price,
                    exit_reason=exit_action['reason'],
                    pnl_percent=pnl_pct,
                    pnl_usd=pnl_usd,
                    peak_profit=peak_profit
                )

                # Clean up exit manager tracking
                self.exit_manager.reset(symbol)

                status = "✅" if pnl_usd > 0 else "❌"
                logger.info(f"{status} EXIT: {symbol} | {exit_action['reason']} | PnL: ${pnl_usd:+.2f} ({pnl_pct:+.2f}%)")
            else:
                logger.error(f"❌ Exit failed: {symbol} - {result.error}")

        except Exception as e:
            logger.error(f"Error executing exit: {e}")

    def get_status(self):
        """Get bot status"""
        positions = self.position_tracker.get_all_positions()
        metrics = profit_tracker.get_metrics()

        return {
            "running": self._running,
            "positions": len(positions),
            "total_trades": metrics.total_trades,
            "win_rate": f"{metrics.win_rate:.1f}%",
            "total_pnl": f"${metrics.total_pnl_usd:+.2f}",
            "start_balance": f"${profit_tracker.start_balance:.2f}"
        }


# FastAPI app
bot = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    bot = SimpleMoonshotBot()
    await bot.initialize()
    await bot.start()
    yield
    await bot.stop()


app = FastAPI(lifespan=lifespan, title="Simple Moonshot Bot")


@app.get("/")
async def root():
    return {"status": "running", "strategy": "simple_2pct_velocity"}


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


if __name__ == "__main__":
    # Create logs directory
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    logger.info("=" * 60)
    logger.info("STARTING SIMPLE MOONSHOT BOT")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=PORT)
