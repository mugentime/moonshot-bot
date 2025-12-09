"""
MOMENTUM HUNTER BOT
Detects coins moving +1% in 60 seconds and rides the momentum to 10%+

Strategy:
- Dynamic hot coins list (top 50 by volume * volatility)
- 60-second rolling price buffer for momentum detection
- Enter on +1% velocity, exit on -3% SL or +10% TP
- Trailing stop after +5% profit
"""
import asyncio
import sys
import os

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from loguru import logger
import uvicorn

from config import PORT, LOG_LEVEL, MomentumConfig
from src import DataFeed, OrderExecutor
from src.momentum_scanner import MomentumDetector, PositionManager, MomentumSignal

# Configure logging
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <level>{message}</level>",
    level=LOG_LEVEL
)
logger.add(
    "logs/momentum_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG"
)


class MomentumHunterBot:
    """
    Momentum Hunter Trading Bot
    - Scans top 50 hot coins every 5 seconds
    - Enters on +1% velocity in 60 seconds
    - Exits on SL/TP/trailing
    """

    def __init__(self):
        self.config = MomentumConfig()
        self.data_feed = DataFeed()
        self.order_executor = OrderExecutor(self.data_feed)
        self.detector = MomentumDetector(self.config)
        self.position_manager = PositionManager(self.config)

        self._running = False
        self._scan_task = None
        self._monitor_task = None

        # Stats
        self.trades_opened = 0
        self.trades_closed = 0
        self.total_pnl = 0.0

    async def initialize(self):
        """Initialize the bot"""
        logger.info("=" * 50)
        logger.info("MOMENTUM HUNTER BOT INITIALIZING")
        logger.info("=" * 50)

        # Connect to Binance
        await self.data_feed.initialize()
        logger.info("Connected to Binance Futures")

        # Get initial balance
        balance = await self.data_feed.get_account_balance()
        logger.info(f"Account balance: ${balance:.2f}")

        # Refresh hot coins
        hot_coins = await self.detector.refresh_hot_coins(self.data_feed.client)
        logger.info(f"Loaded {len(hot_coins)} hot coins")

        # Log config
        logger.info("-" * 50)
        logger.info("STRATEGY CONFIG:")
        logger.info(f"  Hot Coins: {self.config.HOT_COINS_COUNT}")
        logger.info(f"  Scan Interval: {self.config.SCAN_INTERVAL_SECONDS}s")
        logger.info(f"  Entry Trigger: +/-{abs(self.config.LONG_VELOCITY_TRIGGER)}% in 60s")
        logger.info(f"  Max Positions: {self.config.MAX_POSITIONS}")
        logger.info(f"  Position Size: ${self.config.POSITION_SIZE_USD}")
        logger.info(f"  Leverage: {self.config.LEVERAGE}x")
        logger.info(f"  Stop Loss: {self.config.STOP_LOSS_PERCENT}%")
        logger.info(f"  Take Profit: {self.config.TAKE_PROFIT_PERCENT}%")
        logger.info(f"  Trailing: {self.config.TRAILING_DISTANCE_PERCENT}% after {self.config.TRAILING_ACTIVATE_PERCENT}%")
        logger.info("=" * 50)

    async def start(self):
        """Start the bot"""
        self._running = True
        logger.info("MOMENTUM HUNTER STARTED")

        # Start scan and monitor loops
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """Stop the bot"""
        self._running = False
        logger.info("Stopping bot...")

        if self._scan_task:
            self._scan_task.cancel()
        if self._monitor_task:
            self._monitor_task.cancel()

        # Print final stats
        logger.info("=" * 50)
        logger.info("SESSION STATS:")
        logger.info(f"  Trades Opened: {self.trades_opened}")
        logger.info(f"  Trades Closed: {self.trades_closed}")
        logger.info(f"  Total PnL: ${self.total_pnl:+.2f}")
        logger.info("=" * 50)

    async def _scan_loop(self):
        """Main scanning loop - detect momentum signals"""
        logger.info("Scan loop started")

        while self._running:
            try:
                # Refresh hot coins if needed
                await self.detector.refresh_hot_coins(self.data_feed.client)

                # Get all tickers
                tickers = await self.data_feed.client.futures_ticker()

                # Update price buffer
                self.detector.update_prices(tickers)

                # Scan for signals
                signals = self.detector.scan_for_signals()

                # Process signals
                for signal in signals:
                    await self._process_signal(signal)

                # Log periodic status
                positions = self.position_manager.count()
                if positions > 0:
                    logger.debug(f"Positions: {positions}/{self.config.MAX_POSITIONS}")

                await asyncio.sleep(self.config.SCAN_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                await asyncio.sleep(5)

    async def _process_signal(self, signal: MomentumSignal):
        """Process a momentum signal - open position if conditions met"""
        symbol = signal.symbol

        # Can we open?
        if not self.position_manager.can_open(symbol):
            return

        logger.info(f"SIGNAL: {signal.direction} {symbol} | Velocity: {signal.velocity:+.2f}%")

        try:
            # Open position
            if signal.direction == "LONG":
                result = await self.order_executor.open_long(
                    symbol=symbol,
                    margin=self.config.POSITION_SIZE_USD,
                    leverage=self.config.LEVERAGE
                )
            else:
                result = await self.order_executor.open_short(
                    symbol=symbol,
                    margin=self.config.POSITION_SIZE_USD,
                    leverage=self.config.LEVERAGE
                )

            if result.success:
                self.position_manager.add_position(
                    symbol=symbol,
                    direction=signal.direction,
                    entry_price=result.entry_price,
                    quantity=result.quantity
                )
                self.trades_opened += 1
                logger.info(f"OPENED {signal.direction} {symbol} @ {result.entry_price:.6f}")
            else:
                logger.warning(f"Failed to open {symbol}: {result.error}")

        except Exception as e:
            logger.error(f"Error opening {symbol}: {e}")

    async def _monitor_loop(self):
        """Monitor open positions for exits"""
        logger.info("Monitor loop started")

        while self._running:
            try:
                positions = self.position_manager.get_all()

                if not positions:
                    await asyncio.sleep(2)
                    continue

                # Get current prices
                tickers = await self.data_feed.client.futures_ticker()
                price_map = {t['symbol']: float(t['lastPrice']) for t in tickers}

                # Check each position
                for pos in positions:
                    symbol = pos.symbol
                    current_price = price_map.get(symbol)

                    if not current_price:
                        continue

                    # Check exit conditions
                    exit_reason = self.position_manager.check_exit(symbol, current_price)

                    if exit_reason:
                        await self._close_position(symbol, current_price, exit_reason)

                await asyncio.sleep(2)  # Check every 2 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(5)

    async def _close_position(self, symbol: str, current_price: float, reason: str):
        """Close a position"""
        pos = self.position_manager.positions.get(symbol)
        if not pos:
            return

        try:
            # Calculate PnL before closing
            pnl_pct = self.position_manager.get_pnl(symbol, current_price)
            pnl_usd = (self.config.POSITION_SIZE_USD * self.config.LEVERAGE) * (pnl_pct / 100)

            # Close the position
            if pos.direction == "LONG":
                result = await self.order_executor.close_long(symbol)
            else:
                result = await self.order_executor.close_short(symbol)

            if result.success:
                self.position_manager.remove_position(symbol)
                self.trades_closed += 1
                self.total_pnl += pnl_usd

                status = "+" if pnl_usd > 0 else ""
                logger.info(f"CLOSED {pos.direction} {symbol} | {reason.upper()} | PnL: ${status}{pnl_usd:.2f} ({pnl_pct:+.1f}%)")
            else:
                logger.error(f"Failed to close {symbol}: {result.error}")

        except Exception as e:
            logger.error(f"Error closing {symbol}: {e}")

    def get_status(self):
        """Get bot status for API"""
        return {
            "running": self._running,
            "strategy": "momentum_hunter",
            "positions": self.position_manager.count(),
            "max_positions": self.config.MAX_POSITIONS,
            "hot_coins": len(self.detector.hot_coins.get_list()),
            "trades_opened": self.trades_opened,
            "trades_closed": self.trades_closed,
            "total_pnl": f"${self.total_pnl:+.2f}"
        }


# FastAPI app
bot = None
_init_task = None


async def _initialize_bot():
    """Initialize bot in background"""
    global bot
    try:
        await bot.initialize()
        await bot.start()
        logger.info("Bot initialization complete!")
    except Exception as e:
        logger.error(f"Bot initialization failed: {e}")
        import traceback
        logger.error(traceback.format_exc())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, _init_task
    bot = MomentumHunterBot()
    _init_task = asyncio.create_task(_initialize_bot())
    yield
    if _init_task and not _init_task.done():
        _init_task.cancel()
    await bot.stop()


app = FastAPI(lifespan=lifespan, title="Momentum Hunter Bot")


@app.get("/")
async def root():
    return {"status": "running", "strategy": "momentum_hunter"}


@app.get("/health")
async def health():
    """Health endpoint for Railway"""
    if bot and bot._running:
        return {"status": "healthy", **bot.get_status()}
    return {"status": "healthy", "initializing": True}


@app.get("/status")
async def status():
    """Get detailed status"""
    if bot:
        return bot.get_status()
    return {"status": "initializing"}


@app.get("/positions")
async def positions():
    """Get open positions"""
    if bot:
        return {
            "positions": [
                {
                    "symbol": p.symbol,
                    "direction": p.direction,
                    "entry_price": p.entry_price,
                    "peak_profit": p.peak_profit,
                    "trailing_active": p.trailing_active
                }
                for p in bot.position_manager.get_all()
            ]
        }
    return {"positions": []}


@app.get("/hot-coins")
async def hot_coins():
    """Get current hot coins list"""
    if bot:
        return {"hot_coins": bot.detector.hot_coins.get_list()}
    return {"hot_coins": []}


if __name__ == "__main__":
    # Create logs directory
    os.makedirs("logs", exist_ok=True)

    logger.info("=" * 50)
    logger.info("STARTING MOMENTUM HUNTER BOT")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 50)

    uvicorn.run(app, host="0.0.0.0", port=PORT)
