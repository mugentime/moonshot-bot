"""
Moonshot Bot - Main Entry Point
Captures moonshot opportunities on Binance Futures
"""
import asyncio
import signal
import sys
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
        logger.info("🚀 Initializing Moonshot Bot...")
        
        # Initialize data feed (Binance connection)
        await self.data_feed.initialize()
        
        # Initialize order executor
        await self.order_executor.initialize()
        
        # Initialize position tracker (Redis)
        await self.position_tracker.initialize()
        
        # Initialize pair filter
        await self.pair_filter.initialize()
        
        # Initial regime evaluation
        await self.market_regime.evaluate()
        
        # Log initial status
        self.position_sizer.log_status()
        self.position_tracker.log_status()
        
        logger.info(f"✅ Bot initialized | Regime: {self.market_regime.current_regime.value}")
    
    async def start(self):
        """Start the bot"""
        self._running = True
        
        logger.info("▶️ Starting Moonshot Bot...")
        
        # Start background tasks
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self._regime_task = asyncio.create_task(self._regime_loop())
        
        logger.info("✅ Bot running!")
    
    async def stop(self):
        """Stop the bot gracefully"""
        logger.info("⏹️ Stopping Moonshot Bot...")
        self._running = False
        
        # Cancel tasks
        for task in [self._scan_task, self._monitor_task, self._regime_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Close connections
        await self.position_tracker.close()
        await self.data_feed.close()
        
        logger.info("✅ Bot stopped")
    
    async def _scan_loop(self):
        """Main loop for scanning moonshots"""
        logger.info("🔍 Scan loop started")
        
        while self._running:
            try:
                # Skip if regime doesn't allow entries
                if not self.market_regime.allows_new_entries():
                    await asyncio.sleep(5)
                    continue
                
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


# Global bot instance
bot = MoonshotBot()


# FastAPI app for health checks
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await bot.initialize()
    await bot.start()
    yield
    # Shutdown
    await bot.stop()


app = FastAPI(title="Moonshot Bot", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "healthy", "bot": bot.get_status()}


@app.get("/status")
async def status():
    return bot.get_status()


@app.get("/positions")
async def positions():
    return [p.to_dict() for p in bot.position_tracker.get_all_positions()]


@app.post("/stop")
async def stop_bot():
    await bot.stop()
    return {"status": "stopped"}


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
