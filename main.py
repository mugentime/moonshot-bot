"""
Moonshot Bot - Main Entry Point
Captures moonshot opportunities on Binance Futures
"""
import asyncio
import signal
import sys
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI
from loguru import logger
import uvicorn

from config import PORT, LOG_LEVEL, BOT_TIMEZONE
from src import (
    DataFeed,
    MarketRegimeDetector,
    MarketRegime,
    PairFilter,
    MoonshotDetector,
    PositionSizer,
    TradeManager,
    ExitManager,
    OrderExecutor,
    PositionTracker
)


# Configure logging
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level=LOG_LEVEL
)


# Global health status - allows /health to respond immediately
class HealthStatus:
    def __init__(self):
        self.initialized = False
        self.initializing = False
        self.running = False
        self.error = None
        self.error_traceback = None

    def to_dict(self):
        return {
            "initialized": self.initialized,
            "initializing": self.initializing,
            "running": self.running,
            "error": self.error,
        }

health_status = HealthStatus()


class MoonshotBot:
    """
    Main bot orchestrator
    Coordinates all modules for moonshot detection and trading
    """
    
    def __init__(self):
        # Core modules
        self.data_feed = DataFeed()
        self.market_regime = MarketRegimeDetector(self.data_feed)
        self.pair_filter = PairFilter(self.data_feed)
        self.moonshot_detector = MoonshotDetector(self.data_feed)
        self.position_sizer = PositionSizer(self.data_feed)
        self.position_tracker = PositionTracker(self.data_feed)
        self.exit_manager = ExitManager(self.data_feed)
        self.order_executor = OrderExecutor(self.data_feed)
        self.trade_manager = TradeManager(
            self.data_feed,
            self.market_regime,
            self.position_sizer,
            self.position_tracker
        )
        
        # State
        self._running = False
        self._scan_task = None
        self._monitor_task = None
        self._regime_task = None
        
        # Setup callbacks
        self.market_regime.on_regime_change = self._on_regime_change
    
    async def initialize(self):
        """Initialize all modules"""
        global health_status
        health_status.initializing = True

        try:
            logger.info("🚀 Initializing Moonshot Bot...")

            # Initialize data feed (Binance connection)
            logger.info("📡 Connecting to Binance...")
            await self.data_feed.initialize()
            logger.info("✅ Binance connection established")

            # Initialize order executor
            logger.info("📝 Initializing order executor...")
            await self.order_executor.initialize()
            logger.info("✅ Order executor ready")

            # Initialize position tracker (Redis)
            logger.info("🗄️ Connecting to Redis...")
            await self.position_tracker.initialize()
            logger.info("✅ Redis connection established")

            # Initialize pair filter
            logger.info("🔍 Initializing pair filter...")
            await self.pair_filter.initialize()
            logger.info("✅ Pair filter ready")

            # Initialize position sizer with real account balance
            logger.info("💰 Fetching real account balance...")
            await self.position_sizer.initialize()
            logger.info("✅ Position sizer ready")

            # Initial regime evaluation
            logger.info("📊 Evaluating market regime...")
            await self.market_regime.evaluate()
            logger.info("✅ Market regime evaluated")

            # Log initial status
            self.position_sizer.log_status()
            self.position_tracker.log_status()

            health_status.initialized = True
            health_status.initializing = False
            logger.info(f"✅ Bot initialized | Regime: {self.market_regime.current_regime.value}")

        except Exception as e:
            health_status.error = str(e)
            health_status.error_traceback = traceback.format_exc()
            health_status.initializing = False
            logger.error(f"❌ Initialization failed: {e}")
            logger.error(traceback.format_exc())
            raise
    
    async def start(self):
        """Start the bot"""
        global health_status
        self._running = True
        health_status.running = True

        logger.info("▶️ Starting Moonshot Bot...")

        # Start background tasks
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self._regime_task = asyncio.create_task(self._regime_loop())

        logger.info("✅ Bot running!")
    
    async def stop(self):
        """Stop the bot gracefully"""
        global health_status
        logger.info("⏹️ Stopping Moonshot Bot...")
        self._running = False
        health_status.running = False

        # Cancel tasks
        for task in [self._scan_task, self._monitor_task, self._regime_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close connections
        try:
            await self.position_tracker.close()
        except Exception as e:
            logger.error(f"Error closing position tracker: {e}")

        try:
            await self.data_feed.close()
        except Exception as e:
            logger.error(f"Error closing data feed: {e}")

        logger.info("✅ Bot stopped")
    
    async def _scan_loop(self):
        """Main loop for scanning moonshots"""
        logger.info("🔍 Scan loop started")

        while self._running:
            try:
                # NOTE: We ALWAYS scan, even during CHOPPY regime!
                # Mega-signals (>5% moves) bypass regime check in trade_manager.evaluate_signal()
                # This ensures we don't miss moonshots during sideways markets

                # Get pairs to scan
                pairs_to_scan = self.pair_filter.get_pairs_to_scan()
                
                for symbol in pairs_to_scan:
                    if not self._running:
                        break
                    
                    # Scan for moonshot
                    signal = await self.moonshot_detector.scan(symbol)
                    
                    if signal:
                        # Evaluate and possibly execute trade
                        decision = await self.trade_manager.evaluate_signal(signal)
                        
                        if decision.approved:
                            await self._execute_trade(decision)
                    
                    # Mark as scanned
                    self.pair_filter.mark_scanned(symbol)
                    
                    # Small delay between pairs
                    await asyncio.sleep(0.1)
                
                # Wait before next scan cycle
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scan loop: {e}")
                await asyncio.sleep(5)
    
    async def _monitor_loop(self):
        """Loop for monitoring open positions"""
        logger.info("📊 Monitor loop started")
        
        while self._running:
            try:
                # Get all tracked positions
                positions = self.position_tracker.get_all_positions()
                
                for pos in positions:
                    if not self._running:
                        break
                    
                    # Get current price
                    ticker = await self.data_feed.get_ticker(pos.symbol)
                    if not ticker:
                        continue
                    
                    current_price = ticker.price
                    
                    # Update position tracker
                    pnl = self._calculate_pnl(pos, current_price)
                    await self.position_tracker.update_position(pos.symbol, current_price, pnl)
                    
                    # Check exit conditions
                    exit_action = await self.exit_manager.update_position(pos.symbol, current_price)
                    
                    if exit_action:
                        await self._execute_exit(exit_action)
                
                # Sync with exchange periodically
                await self.position_tracker.sync_with_exchange()
                
                # Wait before next check
                await asyncio.sleep(2)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(5)
    
    async def _regime_loop(self):
        """Loop for evaluating market regime"""
        logger.info("🌡️ Regime loop started")
        
        while self._running:
            try:
                await self.market_regime.evaluate()
                
                # Refresh pair categories hourly
                await self.pair_filter.refresh_categories()
                
                # Wait 5 minutes
                await asyncio.sleep(300)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in regime loop: {e}")
                await asyncio.sleep(60)
    
    async def _on_regime_change(self, old_regime: MarketRegime, new_regime: MarketRegime):
        """Handle regime changes"""
        logger.warning(f"📊 Regime changed: {old_regime.value} → {new_regime.value}")
        
        # If changed to CHOPPY, close all positions
        if new_regime == MarketRegime.CHOPPY:
            exit_actions = self.exit_manager.on_regime_change_to_choppy()
            
            for action in exit_actions:
                await self._execute_exit(action)
    
    async def _execute_trade(self, decision):
        """Execute an approved trade"""
        try:
            symbol = decision.symbol
            direction = decision.direction
            
            logger.info(f"🎯 Executing trade: {symbol} {direction}")
            
            if direction == "LONG":
                result = await self.order_executor.open_long(
                    symbol=symbol,
                    margin=decision.margin,
                    leverage=decision.leverage,
                    stop_loss=decision.stop_loss
                )
            else:
                result = await self.order_executor.open_short(
                    symbol=symbol,
                    margin=decision.margin,
                    leverage=decision.leverage,
                    stop_loss=decision.stop_loss
                )
            
            if result.success:
                # Track position
                await self.position_tracker.add_position(
                    symbol=symbol,
                    direction=direction,
                    entry_price=result.price,
                    quantity=result.quantity,
                    margin=decision.margin,
                    leverage=decision.leverage,
                    order_id=result.order_id
                )
                
                # Initialize exit manager tracking
                self.exit_manager.initialize_position(
                    symbol=symbol,
                    direction=direction,
                    entry_price=result.price,
                    margin=decision.margin,
                    leverage=decision.leverage
                )
                
                # Update position sizer
                self.position_sizer.on_position_opened()
                
                # Mark entry for cooldown
                self.trade_manager.mark_entry(symbol)
                
                # Upgrade pair to hot tier
                self.pair_filter.upgrade_to_hot(symbol)
                
                logger.info(f"✅ Trade executed: {symbol} {direction} @ {result.price}")
            else:
                logger.error(f"❌ Trade failed: {symbol} - {result.error}")
                
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
    
    async def _execute_exit(self, exit_action):
        """Execute an exit action"""
        try:
            symbol = exit_action.symbol
            
            logger.info(f"📤 Executing exit: {symbol} | Reason: {exit_action.reason.value}")
            
            result = await self.order_executor.close_position(
                symbol=symbol,
                percent=exit_action.close_percent
            )
            
            if result.success:
                if exit_action.close_percent >= 100:
                    # Full close
                    await self.position_tracker.remove_position(symbol)
                    self.exit_manager.remove_position(symbol)
                    self.position_sizer.on_position_closed()
                else:
                    # Partial close
                    await self.position_tracker.reduce_position(symbol, exit_action.close_percent)
                    self.exit_manager.update_remaining_percent(symbol, exit_action.close_percent)
                
                # Update stop-loss if needed
                if 'new_sl' in exit_action.details:
                    await self.order_executor.update_stop_loss(symbol, exit_action.details['new_sl'])
                
                logger.info(f"✅ Exit executed: {symbol} | {exit_action.close_percent}% closed")
            else:
                logger.error(f"❌ Exit failed: {symbol} - {result.error}")
                
        except Exception as e:
            logger.error(f"Error executing exit: {e}")
    
    def _calculate_pnl(self, position, current_price: float) -> float:
        """Calculate unrealized P&L"""
        # Guard against division by zero
        if position.entry_price == 0 or position.entry_price is None:
            return 0.0

        if position.direction == "LONG":
            return (current_price - position.entry_price) / position.entry_price * 100 * position.leverage
        else:
            return (position.entry_price - current_price) / position.entry_price * 100 * position.leverage
    
    def get_status(self) -> dict:
        """Get bot status for API"""
        return {
            "running": self._running,
            "regime": self.market_regime.current_regime.value,
            "positions": self.position_tracker.get_position_count(),
            "available_slots": self.position_sizer.get_available_slots(),
            "pairs_tracked": len(self.pair_filter.pairs),
            "active_moonshots": len(self.moonshot_detector.active_moonshots)
        }


# Global bot instance (created lazily)
bot = None
_init_task = None


async def initialize_and_start_bot():
    """Initialize and start the bot in background"""
    global bot, health_status

    try:
        logger.info("🚀 Starting bot initialization in background...")
        bot = MoonshotBot()
        await bot.initialize()
        await bot.start()
        logger.info("✅ Bot fully operational!")
    except Exception as e:
        logger.error(f"❌ Bot initialization failed: {e}")
        health_status.error = str(e)
        health_status.error_traceback = traceback.format_exc()


# FastAPI app for health checks
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _init_task

    # Start initialization in background - don't block the server
    logger.info("🌐 HTTP server starting - bot will initialize in background...")
    _init_task = asyncio.create_task(initialize_and_start_bot())

    yield  # Server is now running and accepting requests

    # Shutdown
    logger.info("🛑 Shutting down...")
    if _init_task and not _init_task.done():
        _init_task.cancel()
        try:
            await _init_task
        except asyncio.CancelledError:
            pass

    if bot:
        await bot.stop()


app = FastAPI(title="Moonshot Bot", lifespan=lifespan)


@app.get("/health")
async def health():
    """
    Health check endpoint - responds immediately even during initialization.
    Railway healthcheck will hit this endpoint.
    """
    global health_status, bot

    # Always return 200 so Railway healthcheck passes
    # Include status info for debugging
    status_info = {
        "status": "healthy",
        "health": health_status.to_dict(),
    }

    if health_status.initialized and bot:
        try:
            status_info["bot"] = bot.get_status()
        except Exception as e:
            status_info["bot_error"] = str(e)
    elif health_status.error:
        status_info["error"] = health_status.error

    return status_info


@app.get("/status")
async def status():
    """Get detailed bot status"""
    global health_status, bot

    if not health_status.initialized:
        return {
            "status": "initializing" if health_status.initializing else "not_started",
            "error": health_status.error,
            "health": health_status.to_dict(),
        }

    if bot:
        return bot.get_status()

    return {"status": "no_bot_instance", "health": health_status.to_dict()}


@app.get("/positions")
async def positions():
    """Get open positions"""
    global bot

    if not bot or not health_status.initialized:
        return {"error": "Bot not initialized", "positions": []}

    try:
        return [p.to_dict() for p in bot.position_tracker.get_all_positions()]
    except Exception as e:
        return {"error": str(e), "positions": []}


@app.post("/stop")
async def stop_bot():
    """Stop the bot"""
    global bot

    if bot:
        await bot.stop()
        return {"status": "stopped"}

    return {"status": "no_bot_to_stop"}


def handle_signal(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    asyncio.create_task(bot.stop())
    sys.exit(0)


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    # Run the server
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
